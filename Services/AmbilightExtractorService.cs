// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Data.Enums;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Library;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// Background extraction service that mirrors the behavior of the Python extractor daemon:
/// - Enumerates Jellyfin library items
/// - Decides which ones need extraction
/// - Calls the Rust ambilight-extractor binary to produce .bin files.
/// </summary>
public class AmbilightExtractorService
{
    private readonly ILogger<AmbilightExtractorService> _logger;
    private readonly ILibraryManager _libraryManager;
    private readonly AmbilightStorageService _storage;
    private readonly PluginConfiguration _config;
    private readonly AmbilightInProcessExtractor _extractorCore;

    public AmbilightExtractorService(
        ILogger<AmbilightExtractorService> logger,
        ILibraryManager libraryManager,
        AmbilightStorageService storage,
        PluginConfiguration config,
        AmbilightInProcessExtractor extractorCore)
    {
        _logger = logger;
        _libraryManager = libraryManager;
        _storage = storage;
        _config = config;
        _extractorCore = extractorCore;
    }

    /// <summary>
    /// Enumerate items from Jellyfin and sync them into AmbilightStorage.
    /// This mirrors perform_incremental_library_update in the Python daemon,
    /// but relies on Jellyfin's internal library manager instead of HTTP.
    /// </summary>
    public void SyncLibraryFromJellyfin()
    {
        _logger.LogInformation("[Ambilight] Syncing library items from Jellyfin...");

        var excluded = _config.ExcludedLibraryIds ?? new List<string>();
        var normalizedExcluded = excluded.Select(NormalizeLibraryId).ToHashSet();

        // Get all user views (libraries)
        var userViews = _libraryManager.GetUserRootFolder().Children
            .Where(v => v is MediaBrowser.Controller.Entities.CollectionFolder)
            .ToList();

        // Filter to only allowed libraries
        var allowedLibraries = userViews
            .Where(lib => !normalizedExcluded.Contains(NormalizeLibraryId(lib.Id.ToString())))
            .ToList();

        _logger.LogInformation("[Ambilight] Syncing {Count} libraries (excluding {ExcludedCount} libraries)", 
            allowedLibraries.Count, excluded.Count);

        // Query each allowed library separately
        foreach (var library in allowedLibraries)
        {
            var query = new InternalItemsQuery
            {
                IncludeItemTypes = new[] { BaseItemKind.Movie, BaseItemKind.Episode },
                Recursive = true,
                Parent = library
            };

            var result = _libraryManager.GetItemsResult(query);
            foreach (var item in result.Items)
            {
                if (item.Path is null)
                {
                    continue;
                }

                var itemIdStr = item.Id.ToString("N");
                var ambiItem = _storage.GetItem(itemIdStr);
                if (ambiItem == null)
                {
                    ambiItem = new AmbilightItem
                    {
                        Id = itemIdStr,
                        LibraryId = library.Id.ToString("N"),
                        Name = item.Name ?? "Unknown",
                        Type = item.GetType().Name,
                        Kind = item.GetType().Name == "Episode" ? "Serie" : (item.GetType().Name == "Movie" ? "Movie" : "Video"),
                        FilePath = item.Path,
                        JellyfinDateCreated = item.DateCreated.ToString("O"),
                        Viewed = false
                    };
                }
                else
                {
                    ambiItem.FilePath = item.Path;
                    ambiItem.Name = item.Name ?? ambiItem.Name;
                }

                _storage.SaveOrUpdateItem(ambiItem);
            }
        }
    }

    /// <summary>
    /// Returns items that need extraction, roughly equivalent to
    /// get_videos_needing_extraction in the Python storage layer.
    /// </summary>
    public IEnumerable<AmbilightItem> GetItemsNeedingExtraction()
    {
        var now = DateTimeOffset.UtcNow;
        var excluded = _config.ExcludedLibraryIds ?? new List<string>();
        var normalizedExcluded = excluded.Select(NormalizeLibraryId).ToHashSet();

        // Get all user views (libraries)
        var userViews = _libraryManager.GetUserRootFolder().Children
            .Where(v => v is MediaBrowser.Controller.Entities.CollectionFolder)
            .ToList();

        // Filter to only allowed libraries
        var allowedLibraries = userViews
            .Where(lib => !normalizedExcluded.Contains(NormalizeLibraryId(lib.Id.ToString())))
            .ToList();

        _logger.LogDebug("[Ambilight] Checking {Count} libraries for pending extractions (excluding {ExcludedCount} libraries)", 
            allowedLibraries.Count, excluded.Count);

        // Collect all pending items first (before sorting)
        var pendingItems = new List<AmbilightItem>();

        // Query each allowed library separately
        foreach (var library in allowedLibraries)
        {
            var query = new InternalItemsQuery
            {
                IncludeItemTypes = new[] { BaseItemKind.Movie, BaseItemKind.Episode },
                Recursive = true,
                Parent = library
            };

            var result = _libraryManager.GetItemsResult(query);
            foreach (var jellyfinItem in result.Items)
            {
                if (jellyfinItem.Path == null)
                {
                    continue;
                }

                var itemIdStr = jellyfinItem.Id.ToString("N");
                var item = _storage.GetItem(itemIdStr);
                if (item == null)
                {
                    item = new AmbilightItem
                    {
                        Id = itemIdStr,
                        LibraryId = library.Id.ToString("N"),
                        Name = jellyfinItem.Name ?? "Unknown",
                        Type = jellyfinItem.GetType().Name,
                        Kind = jellyfinItem.GetType().Name == "Episode" ? "Serie" : (jellyfinItem.GetType().Name == "Movie" ? "Movie" : "Video"),
                        FilePath = jellyfinItem.Path,
                        JellyfinDateCreated = jellyfinItem.DateCreated.ToString("O"),
                        Viewed = false
                    };
                    _storage.SaveOrUpdateItem(item);
                }

                if (string.IsNullOrEmpty(item.FilePath) || !File.Exists(item.FilePath))
                {
                    continue;
                }

                if (item.ExtractionStatus == "failed")
                {
                    continue;
                }

                if (_storage.BinaryExists(item.Id))
                {
                    continue;
                }

                pendingItems.Add(item);
            }
        }

        // Sort according to extraction priority
        var priority = _config.ExtractionPriority ?? "newest_first";
        _logger.LogDebug("[Ambilight] Sorting {Count} pending items by priority: {Priority}", 
            pendingItems.Count, priority);

        switch (priority.ToLowerInvariant())
        {
            case "oldest_first":
                pendingItems = pendingItems
                    .OrderBy(i => DateTime.TryParse(i.JellyfinDateCreated, out var date) ? date : DateTime.MinValue)
                    .ToList();
                break;

            case "alphabetical":
                pendingItems = pendingItems
                    .OrderBy(i => i.Name)
                    .ToList();
                break;

            case "movies_newest_first":
                pendingItems = pendingItems
                    .OrderByDescending(i => i.Kind == "Movie" ? 1 : 0)
                    .ThenByDescending(i => DateTime.TryParse(i.JellyfinDateCreated, out var date) ? date : DateTime.MinValue)
                    .ToList();
                break;

            case "newest_first":
            default:
                pendingItems = pendingItems
                    .OrderByDescending(i => DateTime.TryParse(i.JellyfinDateCreated, out var date) ? date : DateTime.MinValue)
                    .ToList();
                break;
        }

        return pendingItems;
    }

    /// <summary>
    /// Runs the in-process extractor for a single item.
    /// </summary>
    public async Task RunExtractorForItemAsync(AmbilightItem item, CancellationToken cancellationToken)
    {
        var binPath = _storage.GetBinaryPath(item.Id);
        
        // Ensure data folder exists
        var binDir = Path.GetDirectoryName(binPath);
        if (!string.IsNullOrEmpty(binDir) && !Directory.Exists(binDir))
        {
            Directory.CreateDirectory(binDir);
        }

        try
        {
            _logger.LogInformation("[Ambilight] Starting in-process extractor for {ItemName}", item.Name);

            // Set status to extracting
            item.ExtractionStatus = "extracting";
            item.ExtractionProgress = 0;
            item.ExtractionFramesCurrent = 0;
            item.ExtractionFramesTotal = 0;
            _storage.SaveOrUpdateItem(item);

            // Create a progress callback that receives (currentFrame, totalFrames)
            var progressCallback = new Progress<(ulong current, ulong total)>(progress =>
            {
                item.ExtractionFramesCurrent = progress.current;
                item.ExtractionFramesTotal = progress.total;
                item.ExtractionProgress = progress.total > 0 ? (int)Math.Min(99, (progress.current * 100) / progress.total) : 0;
                _storage.UpdateExtractionProgress(item.Id, progress.current, progress.total);
            });

            var ok = await _extractorCore.ExtractAsync(item.FilePath, binPath, cancellationToken, progressCallback).ConfigureAwait(false);

            if (ok && File.Exists(binPath))
            {
                item.ExtractionStatus = "completed";
                item.ExtractionError = null;
                if (_config.Debug)
                {
                    _logger.LogInformation("[Ambilight] Extraction completed for {ItemName}", item.Name);
                }
            }
            else
            {
                item.ExtractionStatus = "failed";
                item.ExtractionError = "Extractor returned failure";
                _logger.LogWarning("[Ambilight] Extraction failed for {ItemName}", item.Name);
            }
        }
        catch (OperationCanceledException)
        {
            // Gracefully handle cancellation (e.g., during Jellyfin shutdown)
            item.ExtractionStatus = "pending";
            item.ExtractionError = null;
            item.ExtractionProgress = 0;
            item.ExtractionFramesCurrent = 0;
            item.ExtractionFramesTotal = 0;
            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Extraction cancelled for {ItemName}", item.Name);
            }
            _storage.ClearExtractionProgress(item.Id);
        }
        catch (Exception ex)
        {
            item.ExtractionStatus = "failed";
            item.ExtractionError = ex.Message;
            _logger.LogError(ex, "[Ambilight] Extraction exception for {ItemName}", item.Name);
        }
        finally
        {
            item.ExtractionAttempts += 1;
            _storage.SaveOrUpdateItem(item);
        }
    }

    /// <summary>
    /// Gets the library ID for an item by walking up the parent chain.
    /// Returns the ID in "N" format (without dashes) for consistent comparison.
    /// </summary>
    private string? GetLibraryId(BaseItem item)
    {
        var current = item;
        
        // Walk up the parent chain until we find a CollectionFolder (library root)
        while (current != null)
        {
            // Check if this is a library root (CollectionFolder)
            // The type name check is a simple way to identify library folders
            var typeName = current.GetType().Name;
            if (typeName == "CollectionFolder" || typeName == "UserView")
            {
                return current.Id.ToString("N");
            }

            // Move to parent
            if (current.ParentId != Guid.Empty)
            {
                current = _libraryManager.GetItemById(current.ParentId);
            }
            else
            {
                break;
            }
        }

        // Fallback: use ParentId if we couldn't find a library
        return item.ParentId != Guid.Empty ? item.ParentId.ToString("N") : null;
    }

    /// <summary>
    /// Normalizes a library ID for comparison by removing dashes and converting to lowercase.
    /// Handles both "D" format (with dashes) and "N" format (without dashes).
    /// </summary>
    private static string NormalizeLibraryId(string id)
    {
        return id.Replace("-", string.Empty).ToLowerInvariant();
    }
}

