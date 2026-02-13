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
    private readonly string _extractorPath;

    public AmbilightExtractorService(
        ILogger<AmbilightExtractorService> logger,
        ILibraryManager libraryManager,
        AmbilightStorageService storage,
        PluginConfiguration config,
        string? extractorPathOverride = null)
    {
        _logger = logger;
        _libraryManager = libraryManager;
        _storage = storage;
        _config = config;
        _extractorPath = !string.IsNullOrWhiteSpace(extractorPathOverride)
            ? extractorPathOverride
            : (string.IsNullOrWhiteSpace(config.RustExtractorPath)
                ? "/usr/local/bin/ambilight-extractor"
                : config.RustExtractorPath!);
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

        foreach (var item in _libraryManager.GetItemList(new InternalItemsQuery
                 {
                     IncludeItemTypes = new[] { BaseItemKind.Movie, BaseItemKind.Episode },
                     Recursive = true
                 }))
        {
            // Skip items from excluded libraries (by parent library Id)
            if (excluded.Count > 0 && item.ParentId != Guid.Empty)
            {
                var libId = item.ParentId.ToString("N");
                if (excluded.Contains(libId))
                {
                    continue;
                }
            }

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
        }
    }

    /// <summary>
    /// Returns items that need extraction, roughly equivalent to
    /// get_videos_needing_extraction in the Python storage layer.
    /// </summary>
    public IEnumerable<AmbilightItem> GetItemsNeedingExtraction()
    {
        var now = DateTimeOffset.UtcNow;
        var extractionMaxAgeDays = _config.ExtractionMaxAgeDays;
        var extractViewed = _config.ExtractViewed;
        var excluded = _config.ExcludedLibraryIds ?? new List<string>();

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

            if (excluded.Count > 0 && jellyfinItem.ParentId != Guid.Empty)
            {
                var libId = jellyfinItem.ParentId.ToString("N");
                if (excluded.Contains(libId))
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

            if (!extractViewed && item.Viewed)
            {
                continue;
            }

            if (extractionMaxAgeDays > 0 && item.JellyfinDateCreated is not null)
            {
                if (DateTimeOffset.TryParse(item.JellyfinDateCreated, out var created))
                {
                    var age = now - created;
                    if (age.TotalDays > extractionMaxAgeDays)
                    {
                        continue;
                    }
                }
            }

            if (_storage.BinaryExists(item.Id))
            {
                continue;
            }

            yield return item;
        }
    }

    /// <summary>
    /// Runs the Rust extractor for a single item.
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

        if (!System.IO.File.Exists(_extractorPath))
        {
            var msg = $"Ambilight extractor binary not found at: {_extractorPath}. Install the binary or set RustExtractorPath in plugin settings.";
            _logger.LogError("[Ambilight] {Msg}", msg);
            item.ExtractionStatus = "failed";
            item.ExtractionError = msg;
            item.ExtractionAttempts += 1;
            _storage.SaveOrUpdateItem(item);
            return;
        }

        var videoDir = Path.GetDirectoryName(item.FilePath);
        if (string.IsNullOrEmpty(videoDir)) videoDir = Path.GetTempPath();

        var startInfo = new ProcessStartInfo
        {
            FileName = _extractorPath,
            WorkingDirectory = videoDir,
            ArgumentList =
            {
                "--input", item.FilePath,
                "--output", binPath
            },
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        _logger.LogInformation("[Ambilight] Starting Rust extractor for {ItemName}", item.Name);

        try
        {
            using var process = new Process { StartInfo = startInfo };
            process.Start();

            // Optional: read output for logging
            _ = Task.Run(async () =>
            {
                while (!process.StandardError.EndOfStream)
                {
                    var line = await process.StandardError.ReadLineAsync().ConfigureAwait(false);
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        _logger.LogDebug("[ambilight-extractor] {Line}", line);
                    }
                }
            }, cancellationToken);

            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);

            if (process.ExitCode == 0 && File.Exists(binPath))
            {
                item.ExtractionStatus = "completed";
                item.ExtractionError = null;
                _logger.LogInformation("[Ambilight] Extraction completed for {ItemName}", item.Name);
            }
            else
            {
                item.ExtractionStatus = "failed";
                item.ExtractionError = $"ExitCode={process.ExitCode}";
                _logger.LogWarning("[Ambilight] Extraction failed for {ItemName} (exit code {ExitCode})", item.Name, process.ExitCode);
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
}

