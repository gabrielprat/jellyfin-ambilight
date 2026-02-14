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

            return JsonSerializer.Deserialize<AmbilightItem>(json);
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
}

public class StorageStatistics
{
    public int TotalVideos { get; set; }
    public int ExtractedVideos { get; set; }
    public int FailedVideos { get; set; }
}

