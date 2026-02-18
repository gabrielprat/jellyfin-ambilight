// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// C# port of the Python FileBasedStorage logic.
/// Metadata and binary files are stored in the plugin data folder only (no media storage).
/// Paths: {DataFolder}/{itemId}.ambilight.json and {DataFolder}/{itemId}.bin.
/// </summary>
public class AmbilightStorageService
{
    private readonly ILogger<AmbilightStorageService> _logger;
    private readonly PluginConfiguration _config;
    private readonly Dictionary<string, (ulong current, ulong total)> _extractionProgressCache = new();

    public AmbilightStorageService(ILogger<AmbilightStorageService> logger, PluginConfiguration config)
    {
        _logger = logger;
        _config = config;
        _logger.LogInformation("Ambilight storage initialized - metadata and binaries in {Folder}", GetDataFolder());
    }

    private string GetDataFolder()
    {
        var folder = _config?.AmbilightDataFolder?.Trim();
        return string.IsNullOrEmpty(folder) ? "/data/ambilight" : folder;
    }

    private string GetMetadataPath(string itemId)
    {
        return Path.Combine(GetDataFolder(), itemId + ".ambilight.json");
    }

    /// <summary>Gets metadata by Jellyfin item id (no dashes).</summary>
    public AmbilightItem? GetItem(string itemId)
    {
        if (string.IsNullOrEmpty(itemId)) return null;

        var metadataPath = GetMetadataPath(itemId);
        if (!File.Exists(metadataPath))
        {
            return null;
        }

        try
        {
            var json = File.ReadAllText(metadataPath);
            if (string.IsNullOrWhiteSpace(json))
            {
                // Zero-byte or whitespace file – treat as corrupt and delete so we can recreate cleanly.
                try
                {
                    File.Delete(metadataPath);
                }
                catch
                {
                    // Ignore delete failures; we'll just skip this item.
                }

                _logger.LogWarning("Ambilight metadata file for item {ItemId} was empty. Deleted corrupt file.", itemId);
                return null;
            }

            var item = JsonSerializer.Deserialize<AmbilightItem>(json);
            
            // If we have a cached progress for this item, use it instead of disk value
            if (item != null)
            {
                lock (_extractionProgressCache)
                {
                    if (_extractionProgressCache.TryGetValue(itemId, out var cachedProgress))
                    {
                        item.ExtractionFramesCurrent = cachedProgress.current;
                        item.ExtractionFramesTotal = cachedProgress.total;
                        // Also update percentage for backwards compatibility
                        if (cachedProgress.total > 0)
                        {
                            item.ExtractionProgress = (int)Math.Min(99, (cachedProgress.current * 100) / cachedProgress.total);
                        }
                    }
                }
            }
            
            return item;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read ambilight metadata for item {ItemId}", itemId);
            return null;
        }
    }

    public void SaveOrUpdateItem(AmbilightItem item)
    {
        if (string.IsNullOrEmpty(item.Id)) return;

        var metadataPath = GetMetadataPath(item.Id);
        try
        {
            var folder = Path.GetDirectoryName(metadataPath);
            if (!string.IsNullOrEmpty(folder) && !Directory.Exists(folder))
            {
                Directory.CreateDirectory(folder);
            }

            item.UpdatedAt = DateTimeOffset.UtcNow;
            if (item.CreatedAt == default)
            {
                item.CreatedAt = DateTimeOffset.UtcNow;
            }

            var json = JsonSerializer.Serialize(item, new JsonSerializerOptions
            {
                WriteIndented = true
            });
            File.WriteAllText(metadataPath, json);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to write ambilight metadata for item {ItemId}", item.Id);
        }
    }
    
    public void UpdateExtractionProgress(string itemId, ulong currentFrame, ulong totalFrames)
    {
        // Update in-memory cache only - avoid expensive disk I/O on every progress update
        lock (_extractionProgressCache)
        {
            _extractionProgressCache[itemId] = (currentFrame, totalFrames);
        }
    }
    
    public void ClearExtractionProgress(string itemId)
    {
        // Remove from cache when extraction is complete
        lock (_extractionProgressCache)
        {
            _extractionProgressCache.Remove(itemId);
        }
    }

    /// <summary>Enumerates all ambilight items stored in the data folder.</summary>
    public IEnumerable<AmbilightItem> EnumerateItems()
    {
        var folder = GetDataFolder();
        if (!Directory.Exists(folder))
        {
            yield break;
        }

        foreach (var path in Directory.EnumerateFiles(folder, "*.ambilight.json", SearchOption.TopDirectoryOnly))
        {
            var fileName = Path.GetFileName(path);
            // fileName is "{itemId}.ambilight.json" -> itemId is before ".ambilight.json"
            var itemId = fileName.EndsWith(".ambilight.json", StringComparison.OrdinalIgnoreCase)
                ? fileName.Substring(0, fileName.Length - ".ambilight.json".Length)
                : Path.GetFileNameWithoutExtension(path);
            if (string.IsNullOrEmpty(itemId)) continue;
            var item = GetItem(itemId);
            if (item != null)
            {
                yield return item;
            }
        }
    }

    /// <summary>Gets the full path for an item's binary file: {DataFolder}/{itemId}.bin</summary>
    public string GetBinaryPath(string itemId)
    {
        var folder = GetDataFolder();
        var fileName = itemId + ".bin";
        return Path.Combine(folder, fileName);
    }

    public bool BinaryExists(string itemId)
    {
        if (string.IsNullOrEmpty(itemId)) return false;
        return File.Exists(GetBinaryPath(itemId));
    }

    public StorageStatistics GetStatistics()
    {
        var items = EnumerateItems().ToList();
        var totalVideos = items.Count;
        var extracted = items.Count(i => i.ExtractionStatus == "completed" && BinaryExists(i.Id));
        var failed = items.Count(i => i.ExtractionStatus == "failed");

        return new StorageStatistics
        {
            TotalVideos = totalVideos,
            ExtractedVideos = extracted,
            FailedVideos = failed
        };
    }
}

public class AmbilightItem
{
    public string Id { get; set; } = string.Empty;
    public string LibraryId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Type { get; set; } = "Video";
    public string Kind { get; set; } = "Video";
    public int? Season { get; set; }
    public int? Episode { get; set; }
    public string FilePath { get; set; } = string.Empty;
    public string? JellyfinDateCreated { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public string ExtractionStatus { get; set; } = "pending";
    public string? ExtractionError { get; set; }
    public int ExtractionAttempts { get; set; }
    public bool Viewed { get; set; }
    public int ExtractionProgress { get; set; } = 0; // 0-100 percentage (deprecated, use frames)
    public ulong ExtractionFramesCurrent { get; set; } = 0; // Current frame count
    public ulong ExtractionFramesTotal { get; set; } = 0; // Total estimated frames
}

public class StorageStatistics
{
    public int TotalVideos { get; set; }
    public int ExtractedVideos { get; set; }
    public int FailedVideos { get; set; }
}

