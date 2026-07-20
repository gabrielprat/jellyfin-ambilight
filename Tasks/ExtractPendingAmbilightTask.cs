// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

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
    private readonly ILoggerFactory _loggerFactory;
    private readonly ILibraryManager _libraryManager;
    private readonly PluginConfiguration _config;

    private AmbilightStorageService? _storage;
    private AmbilightExtractorService? _extractor;

    public ExtractPendingAmbilightTask(
        ILogger<ExtractPendingAmbilightTask> logger,
        ILoggerFactory loggerFactory,
        ILibraryManager libraryManager)
    {
        _logger = logger;
        _loggerFactory = loggerFactory;
        _libraryManager = libraryManager;
        _config = Plugin.Instance?.Configuration ?? new PluginConfiguration();
    }

    private PluginConfiguration Config => Plugin.Instance?.Configuration ?? _config;

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
            // Use Jellyfin's injected logger factory (see AmbilightEntryPoint) so extraction
            // logs reach the server log rather than a private stdout-only pipeline.
            var storageLogger = _loggerFactory.CreateLogger<AmbilightStorageService>();
            var extractorLogger = _loggerFactory.CreateLogger<AmbilightExtractorService>();
            var extractorCoreLogger = _loggerFactory.CreateLogger<AmbilightInProcessExtractor>();

            _storage = new AmbilightStorageService(storageLogger, Config);
            var extractorCore = new AmbilightInProcessExtractor(extractorCoreLogger, Config);
            _extractor = new AmbilightExtractorService(extractorLogger, _libraryManager, _storage, Config, extractorCore);
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

        var maxConcurrent = Config.MaxConcurrentExtractions > 0 ? Config.MaxConcurrentExtractions : 1;
        var parallelOptions = new ParallelOptions
        {
            MaxDegreeOfParallelism = maxConcurrent,
            CancellationToken = cancellationToken
        };

        await Parallel.ForEachAsync(pendingItems, parallelOptions, async (item, token) =>
        {
            try
            {
                _logger.LogInformation("[Ambilight] Queueing extraction for: {ItemName}", item.Name);

                await _extractor.RunExtractorForItemAsync(item, token);
                
                var currentCompleted = Interlocked.Increment(ref completed);
                var progressPercent = (double)currentCompleted / total * 100.0;
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
                var currentCompleted = Interlocked.Increment(ref completed);
                var progressPercent = (double)currentCompleted / total * 100.0;
                progress.Report(progressPercent);
            }
        });

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
