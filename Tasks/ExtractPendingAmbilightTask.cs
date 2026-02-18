using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight.Services;
using MediaBrowser.Controller.Library;
using MediaBrowser.Model.Tasks;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Tasks;

/// <summary>
/// Scheduled task to extract ambilight data for all pending videos.
/// This task can be triggered manually from the Jellyfin dashboard or via API.
/// </summary>
public class ExtractPendingAmbilightTask : IScheduledTask
{
    private readonly ILogger<ExtractPendingAmbilightTask> _logger;
    private readonly ILibraryManager _libraryManager;
    private readonly PluginConfiguration _config;
    
    private AmbilightStorageService? _storage;
    private AmbilightExtractorService? _extractor;

    public ExtractPendingAmbilightTask(
        ILogger<ExtractPendingAmbilightTask> logger,
        ILibraryManager libraryManager)
    {
        _logger = logger;
        _libraryManager = libraryManager;
        _config = Plugin.Instance?.Configuration ?? new PluginConfiguration();
    }

    public string Name => "Extract Pending Ambilight Data";

    public string Key => "ExtractPendingAmbilight";

    public string Description => "Extracts ambilight data for all videos that don't have it yet. Videos are processed sequentially.";

    public string Category => "Ambilight";

    public async Task ExecuteAsync(IProgress<double> progress, CancellationToken cancellationToken)
    {
        _logger.LogInformation("[Ambilight] Starting scheduled extraction task");

        // Initialize services if needed
        if (_storage == null || _extractor == null)
        {
            var loggerFactory = LoggerFactory.Create(builder => builder.AddConsole());
            var storageLogger = loggerFactory.CreateLogger<AmbilightStorageService>();
            var extractorLogger = loggerFactory.CreateLogger<AmbilightExtractorService>();
            var extractorCoreLogger = loggerFactory.CreateLogger<AmbilightInProcessExtractor>();

            _storage = new AmbilightStorageService(storageLogger, _config);
            var extractorCore = new AmbilightInProcessExtractor(extractorCoreLogger, _config);
            _extractor = new AmbilightExtractorService(extractorLogger, _libraryManager, _storage, _config, extractorCore);
        }

        // Get all items needing extraction
        var pendingItems = _extractor.GetItemsNeedingExtraction().ToList();
        
        if (pendingItems.Count == 0)
        {
            _logger.LogInformation("[Ambilight] No pending items to extract");
            progress.Report(100);
            return;
        }

        _logger.LogInformation("[Ambilight] Found {Count} items needing extraction", pendingItems.Count);

        var total = pendingItems.Count;
        var completed = 0;

        foreach (var item in pendingItems)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                _logger.LogInformation("[Ambilight] Extraction task cancelled by user");
                break;
            }

            try
            {
                _logger.LogInformation("[Ambilight] Extracting {Current}/{Total}: {ItemName}", 
                    completed + 1, total, item.Name);

                await _extractor.RunExtractorForItemAsync(item, cancellationToken);
                
                completed++;
                var progressPercent = (double)completed / total * 100.0;
                progress.Report(progressPercent);
            }
            catch (OperationCanceledException)
            {
                _logger.LogInformation("[Ambilight] Extraction cancelled for {ItemName}", item.Name);
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[Ambilight] Failed to extract {ItemName}, continuing with next item", item.Name);
                completed++;
                var progressPercent = (double)completed / total * 100.0;
                progress.Report(progressPercent);
            }
        }

        _logger.LogInformation("[Ambilight] Extraction task completed: {Completed}/{Total} items processed", 
            completed, total);
        
        progress.Report(100);
    }

    public IEnumerable<TaskTriggerInfo> GetDefaultTriggers()
    {
        // Don't run automatically - only when triggered manually or via API
        return Array.Empty<TaskTriggerInfo>();
    }
}
