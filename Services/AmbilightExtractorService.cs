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

        foreach (var item in _libraryManager.GetItemList(new InternalItemsQuery
                 {
                     IncludeItemTypes = new[] { BaseItemKind.Movie, BaseItemKind.Episode },
                     Recursive = true
                 }))
        {
            if (item.Path is null)
            {
                continue;
            }

            // Get the library ID by walking up the parent chain
            var libraryId = GetLibraryId(item);

            // Skip items from excluded libraries (normalize for comparison)
            if (normalizedExcluded.Count > 0 && !string.IsNullOrEmpty(libraryId))
            {
                if (normalizedExcluded.Contains(NormalizeLibraryId(libraryId)))
                {
                    continue;
                }
            }

            var itemIdStr = item.Id.ToString("N");
            var ambiItem = _storage.GetItem(itemIdStr);
            if (ambiItem == null)
            {
                ambiItem = new AmbilightItem
                {
                    Id = itemIdStr,
                    LibraryId = libraryId ?? item.ParentId.ToString("N"),
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

    /// <summary>
    /// Returns items that need extraction, roughly equivalent to
    /// get_videos_needing_extraction in the Python storage layer.
    /// </summary>
    public IEnumerable<AmbilightItem> GetItemsNeedingExtraction()
    {
        var now = DateTimeOffset.UtcNow;
        var excluded = _config.ExcludedLibraryIds ?? new List<string>();
        var normalizedExcluded = excluded.Select(NormalizeLibraryId).ToHashSet();

        var videoItems = _libraryManager.GetItemList(new InternalItemsQuery
        {
            IncludeItemTypes = new[] { BaseItemKind.Movie, BaseItemKind.Episode },
            Recursive = true
        });

        foreach (var jellyfinItem in videoItems)
        {
            if (jellyfinItem.Path == null)
            {
                continue;
            }

            // Get the library ID by walking up the parent chain
            var libraryId = GetLibraryId(jellyfinItem);

            // Skip items from excluded libraries (normalize for comparison)
            if (normalizedExcluded.Count > 0 && !string.IsNullOrEmpty(libraryId))
            {
                if (normalizedExcluded.Contains(NormalizeLibraryId(libraryId)))
                {
                    continue;
                }
            }

            var itemIdStr = jellyfinItem.Id.ToString("N");
            var item = _storage.GetItem(itemIdStr);
            if (item == null)
            {
                item = new AmbilightItem
                {
                    Id = itemIdStr,
                    LibraryId = jellyfinItem.ParentId.ToString("N"),
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

            yield return item;
        }
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

            var ok = await _extractorCore.ExtractAsync(item.FilePath, binPath, cancellationToken).ConfigureAwait(false);

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

