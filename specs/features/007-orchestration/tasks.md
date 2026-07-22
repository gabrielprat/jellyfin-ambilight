# Tasks: Orchestration

## Done

- [x] Implement `AmbilightEntryPoint : IHostedService` (StartAsync/StopAsync)
- [x] Implement `AmbilightServiceRegistrator : IPluginServiceRegistrator` (DI wiring)
- [x] Create service instances in StartAsync (storage, extractor, extractor service, playback)
- [x] Subscribe to ISessionManager events (PlaybackStart/Stopped/Progress)
- [x] Subscribe to ILibraryManager events (ItemAdded/Updated/Removed)
- [x] Implement `OnItemAdded` — auto-extract check (type, library exclusion)
- [x] Implement `OnItemRemoved` — delete binary file
- [x] Implement `OnPlaybackStart/Stopped/Progress` — forward to PlaybackService
- [x] Implement `GetLibraryId()` — walk parent chain to library root
- [x] Implement `NormalizeLibraryId()` — strip dashes, lowercase
- [x] Implement `TriggerExtractionAsync()` — manual extraction trigger
- [x] Implement `CancelExtraction()` — cancel in-progress extraction
- [x] Implement `ExtractPendingAmbilightTask : IScheduledTask`
- [x] Implement `SyncLibraryFromJellyfin()` — enumerate libraries and items
- [x] Implement `CleanupStuckExtractions()` on startup

## TODO

- [ ] Library change detection — re-sync items on library scan events
