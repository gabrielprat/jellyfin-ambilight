# Feature 008: Orchestration

## Summary

Central orchestration layer that ties together extraction, playback, storage, and Jellyfin events. Runs as a hosted service, subscribes to playback/library events, manages service lifecycles, and provides the entry point for all plugin operations.

## Problem

The plugin needs to react to Jellyfin events (playback start/stop/progress, library add/remove), coordinate extraction and playback services, and manage the plugin lifecycle (startup cleanup, shutdown disposal).

## Acceptance criteria

### Hosted service

1. `AmbilightEntryPoint` implements `IHostedService`.
2. Registered via `AmbilightServiceRegistrator` (implements `IPluginServiceRegistrator`).
3. Singleton pattern: `AmbilightEntryPoint.Instance` static property.

### Startup (`StartAsync`)

4. Creates `AmbilightStorageService` and calls `CleanupStuckExtractions()`.
5. Creates `AmbilightInProcessExtractor` (resolves ffmpeg path).
6. Creates `AmbilightExtractorService` (concurrency management).
7. Creates `AmbilightPlaybackService` (multi-player management).
8. Subscribes to `PlaybackStart`, `PlaybackStopped`, `PlaybackProgress` on `ISessionManager`.
9. Subscribes to `ItemAdded`, `ItemUpdated`, `ItemRemoved` on `ILibraryManager`.

### Shutdown (`StopAsync`)

10. Unsubscribes all events.
11. Disposes `CancellationTokenSource`.
12. Does not force-stop active players (they finish naturally or are cancelled).

### Event handling

13. **OnItemAdded:** If `ExtractNewlyAddedItems` enabled, check item is Movie/Episode, check not in excluded libraries, queue extraction in background `Task.Run`.
14. **OnItemRemoved:** Delete binary file for removed Movie/Episode items.
15. **OnPlaybackStart:** Forward to `AmbilightPlaybackService.OnPlaybackStart()`.
16. **OnPlaybackStopped:** Forward to `AmbilightPlaybackService.OnPlaybackStopped()`.
17. **OnPlaybackProgress:** Forward to `AmbilightPlaybackService.OnPlaybackProgress()`.

### Library integration

18. `SyncLibraryFromJellyfin()` — enumerate CollectionFolder libraries, query Movies+Episodes, create/update AmbilightItem metadata.
19. `GetLibraryId()` — walk up parent chain to find CollectionFolder/UserView (library root).
20. Library exclusion via normalized ID comparison (dashes stripped, lowercase).

### Manual triggers

21. `TriggerExtractionAsync(Guid itemId)` — create/update AmbilightItem, call extractor.
22. `CancelExtraction(string itemId)` — delegate to extractor service.

### Scheduled task

23. `ExtractPendingAmbilightTask` implements `IScheduledTask`.
24. No default triggers — manual or API triggered only.
25. Uses `Parallel.ForEachAsync` with `MaxDegreeOfParallelism` from config.

## Implementation files

- `Server/AmbilightEntryPoint.cs` — 410 lines (orchestrator)
- `Server/AmbilightServiceRegistrator.cs` — 26 lines (DI registration)
- `Tasks/ExtractPendingAmbilightTask.cs` — 129 lines (scheduled task)
