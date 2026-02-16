using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight.Services;
using MediaBrowser.Common.Configuration;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Session;
using MediaBrowser.Model.Session;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Server;

/// <summary>
/// Background service that wires Ambilight into the Jellyfin lifecycle:
/// - Initializes storage and services
/// - Periodically runs extraction in the background
/// - Subscribes to playback events to drive the Rust player.
/// </summary>
public class AmbilightEntryPoint : IHostedService
{
    private readonly ILogger<AmbilightEntryPoint> _logger;
    private readonly ILibraryManager _libraryManager;
    private readonly ISessionManager _sessionManager;
    private readonly IApplicationPaths _appPaths;

    private readonly PluginConfiguration _config;

    private AmbilightStorageService? _storage;
    private AmbilightExtractorService? _extractor;
    private AmbilightPlaybackService? _playback;

    private CancellationTokenSource? _cts;

    public static AmbilightEntryPoint? Instance { get; private set; }

    public AmbilightEntryPoint(
        ILogger<AmbilightEntryPoint> logger,
        ILibraryManager libraryManager,
        ISessionManager sessionManager,
        IApplicationPaths appPaths)
    {
        _logger = logger;
        _libraryManager = libraryManager;
        _sessionManager = sessionManager;
        _appPaths = appPaths;
        _config = Plugin.Instance?.Configuration ?? new PluginConfiguration();
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("[Ambilight] Background service starting...");
        
        Instance = this;
        
        // Create logger factory for services (we're already using Microsoft.Extensions.Logging)
        var loggerFactory = LoggerFactory.Create(builder => builder.AddConsole());
        var storageLogger = loggerFactory.CreateLogger<AmbilightStorageService>();
        var extractorLogger = loggerFactory.CreateLogger<AmbilightExtractorService>();
        var playbackLogger = loggerFactory.CreateLogger<AmbilightPlaybackService>();
        var extractorCoreLogger = loggerFactory.CreateLogger<AmbilightInProcessExtractor>();

        _storage = new AmbilightStorageService(storageLogger, _config);
        var extractorCore = new AmbilightInProcessExtractor(extractorCoreLogger, _config);
        _extractor = new AmbilightExtractorService(extractorLogger, _libraryManager, _storage, _config, extractorCore);
        _playback = new AmbilightPlaybackService(playbackLogger, _sessionManager, _libraryManager, _storage, _config);

        _cts = new CancellationTokenSource();

        // Subscribe to playback events
        _sessionManager.PlaybackStart += OnPlaybackStart;
        _sessionManager.PlaybackStopped += OnPlaybackStopped;
        _sessionManager.PlaybackProgress += OnPlaybackProgress;

        // Subscribe to library scan events instead of polling
        _libraryManager.ItemAdded += OnItemAdded;
        _libraryManager.ItemUpdated += OnItemUpdated;
        _libraryManager.ItemRemoved += OnItemRemoved;

        _logger.LogInformation("[Ambilight] Subscribed to library events");

        return Task.CompletedTask;
    }
    
    public Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("[Ambilight] Background service stopping...");

        Instance = null;
        _cts?.Cancel();

        _sessionManager.PlaybackStart -= OnPlaybackStart;
        _sessionManager.PlaybackStopped -= OnPlaybackStopped;
        _sessionManager.PlaybackProgress -= OnPlaybackProgress;
        
        _libraryManager.ItemAdded -= OnItemAdded;
        _libraryManager.ItemUpdated -= OnItemUpdated;
        _libraryManager.ItemRemoved -= OnItemRemoved;

        _cts?.Dispose();

        return Task.CompletedTask;
    }

    /// <summary>
    /// Manually trigger extraction for a specific item.
    /// </summary>
    public async Task TriggerExtractionAsync(Guid itemId)
    {
        if (_extractor == null || _storage == null)
        {
            _logger.LogWarning("[Ambilight] Cannot trigger extraction - services not initialized");
            return;
        }

        var item = _libraryManager.GetItemById(itemId);
        if (item == null || string.IsNullOrEmpty(item.Path))
        {
            _logger.LogWarning("[Ambilight] Cannot trigger extraction - item {ItemId} not found", itemId);
            return;
        }

        _logger.LogInformation("[Ambilight] Manual extraction triggered for {ItemName}", item.Name);

        try
        {
            // Get or create ambilight item (metadata stored in plugin data folder by item id)
            var itemIdStr = item.Id.ToString("N");
            var ambiItem = _storage.GetItem(itemIdStr);
            if (ambiItem == null)
            {
                ambiItem = new Services.AmbilightItem
                {
                    Id = itemIdStr,
                    LibraryId = item.ParentId.ToString("N"),
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

            // Run extraction
            await _extractor.RunExtractorForItemAsync(ambiItem, _cts?.Token ?? CancellationToken.None);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[Ambilight] Error during manual extraction for {ItemName}", item.Name);
        }
    }

    private void OnItemAdded(object? sender, ItemChangeEventArgs e)
    {
        if (_extractor == null || _storage == null || e.Item.Path == null) return;
        
        // Check if auto-extraction is enabled
        if (!_config.ExtractNewlyAddedItems)
        {
            if (_config.Debug)
            {
                _logger.LogDebug("[Ambilight] Auto-extraction disabled, skipping new item: {ItemName}", e.Item.Name);
            }
            return;
        }
        
        // Only process movies and episodes
        if (e.Item is not MediaBrowser.Controller.Entities.Movies.Movie && 
            e.Item is not MediaBrowser.Controller.Entities.TV.Episode) return;
        
        // Check if item is from an excluded library
        var libraryId = GetLibraryId(e.Item);
        var excluded = _config.ExcludedLibraryIds ?? new List<string>();
        var normalizedExcluded = excluded.Select(id => id.Replace("-", string.Empty).ToLowerInvariant()).ToHashSet();
        
        if (!string.IsNullOrEmpty(libraryId) && normalizedExcluded.Count > 0)
        {
            var normalizedLibraryId = libraryId.Replace("-", string.Empty).ToLowerInvariant();
            if (normalizedExcluded.Contains(normalizedLibraryId))
            {
                if (_config.Debug)
                {
                    _logger.LogDebug("[Ambilight] Item {ItemName} is from excluded library, skipping extraction", e.Item.Name);
                }
                return;
            }
        }

        if (_config.Debug)
        {
            _logger.LogInformation("[Ambilight] New item added: {ItemName} - queueing for extraction", e.Item.Name);
        }
        
        // Queue extraction in background - extract ONLY the new item, not all pending items
        _ = Task.Run(async () =>
        {
            try
            {
                // Create or update the ambilight item for this specific new item
                var itemIdStr = e.Item.Id.ToString("N");
                var ambiItem = _storage.GetItem(itemIdStr);
                
                if (ambiItem == null)
                {
                    ambiItem = new Services.AmbilightItem
                    {
                        Id = itemIdStr,
                        LibraryId = e.Item.ParentId.ToString("N"),
                        Name = e.Item.Name ?? "Unknown",
                        Type = e.Item.GetType().Name,
                        Kind = e.Item.GetType().Name == "Episode" ? "Serie" : (e.Item.GetType().Name == "Movie" ? "Movie" : "Video"),
                        FilePath = e.Item.Path,
                        JellyfinDateCreated = e.Item.DateCreated.ToString("O"),
                        Viewed = false
                    };
                    _storage.SaveOrUpdateItem(ambiItem);
                }
                
                // Check if extraction is needed (binary doesn't exist)
                if (!_storage.BinaryExists(itemIdStr))
                {
                    if (_config.Debug)
                    {
                        _logger.LogInformation("[Ambilight] Starting extraction for new item: {ItemName}", e.Item.Name);
                    }
                    await _extractor.RunExtractorForItemAsync(ambiItem, _cts?.Token ?? CancellationToken.None);
                }
                else
                {
                    if (_config.Debug)
                    {
                        _logger.LogDebug("[Ambilight] Binary already exists for new item: {ItemName}", e.Item.Name);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[Ambilight] Error extracting new item: {ItemName}", e.Item.Name);
            }
        }, _cts?.Token ?? CancellationToken.None);
    }

    private void OnItemUpdated(object? sender, ItemChangeEventArgs e)
    {
        // Could handle updated items here if needed
        // For now, we'll only extract new items
    }

    private void OnItemRemoved(object? sender, ItemChangeEventArgs e)
    {
        if (_storage == null || e.Item == null) return;
        
        // Only process movies and episodes
        if (e.Item is not MediaBrowser.Controller.Entities.Movies.Movie && 
            e.Item is not MediaBrowser.Controller.Entities.TV.Episode) return;

        var itemIdStr = e.Item.Id.ToString("N");
        var itemName = e.Item.Name ?? "Unknown";
        
        try
        {
            // Check if binary file exists
            var binPath = _storage.GetBinaryPath(itemIdStr);
            if (File.Exists(binPath))
            {
                File.Delete(binPath);
                _logger.LogInformation("[Ambilight] Deleted binary file for removed item: {ItemName} ({Path})", itemName, binPath);
            }
            else
            {
                if (_config.Debug)
                {
                    _logger.LogDebug("[Ambilight] No binary file found for removed item: {ItemName}", itemName);
                }
            }
            
            // Clean up metadata (optional - keeps database smaller)
            var ambiItem = _storage.GetItem(itemIdStr);
            if (ambiItem != null)
            {
                // Mark as deleted rather than removing entirely (preserves history if needed)
                // Or you could delete: _storage.DeleteItem(itemIdStr);
                _logger.LogInformation("[Ambilight] Item removed from library: {ItemName}", itemName);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[Ambilight] Error cleaning up binary for removed item: {ItemName}", itemName);
        }
    }

    private void OnPlaybackStart(object? sender, PlaybackProgressEventArgs e)
    {
        if (_playback == null || e.Session == null || e.Item == null)
        {
            return;
        }

        var info = new PlaybackProgressInfo
        {
            ItemId = e.Item.Id,
            PositionTicks = e.PlaybackPositionTicks
        };
        
        _playback.OnPlaybackStart(e.Session, info);
    }

    private void OnPlaybackStopped(object? sender, PlaybackStopEventArgs e)
    {
        if (_playback == null || e.Session == null || e.Item == null)
        {
            return;
        }

        var info = new PlaybackStopInfo
        {
            ItemId = e.Item.Id,
            PositionTicks = e.PlaybackPositionTicks
        };
        
        _playback.OnPlaybackStopped(e.Session, info);
    }

    private void OnPlaybackProgress(object? sender, PlaybackProgressEventArgs e)
    {
        if (_playback == null || e.Session == null || e.Item == null)
        {
            return;
        }

        var info = new PlaybackProgressInfo
        {
            ItemId = e.Item.Id,
            PositionTicks = e.PlaybackPositionTicks
        };
        
        _playback.OnPlaybackProgress(e.Session, info);
    }

    /// <summary>
    /// Gets the library ID for an item by walking up the parent chain.
    /// Returns the ID in "N" format (without dashes) for consistent comparison.
    /// </summary>
    private string? GetLibraryId(MediaBrowser.Controller.Entities.BaseItem item)
    {
        var current = item;
        
        // Walk up the parent chain until we find a CollectionFolder (library root)
        while (current != null)
        {
            // Check if this is a library root (CollectionFolder)
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

}

