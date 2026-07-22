# Plan: Orchestration

## Architecture

### Service creation order

```
AmbilightEntryPoint.StartAsync()
│
├── 1. Create AmbilightStorageService
│   └── CleanupStuckExtractions() — reset stuck items
│
├── 2. Create AmbilightInProcessExtractor
│   └── ResolveFfmpegPath() — find ffmpeg binary
│
├── 3. Create AmbilightExtractorService
│   └── Initialize concurrency semaphore
│
├── 4. Create AmbilightPlaybackService
│   └── Initialize _sessionPlayers dictionary
│
└── 5. Subscribe to Jellyfin events
    ├── ISessionManager.PlaybackStart
    ├── ISessionManager.PlaybackStopped
    ├── ISessionManager.PlaybackProgress
    ├── ILibraryManager.ItemAdded
    ├── ILibraryManager.ItemUpdated
    └── ILibraryManager.ItemRemoved
```

### Event flow

```
Jellyfin Event
    │
    ▼
AmbilightEntryPoint (event handler)
    │
    ├── Library events → ExtractorService
    │   ├── ItemAdded → TriggerExtraction (if auto-extract enabled)
    │   └── ItemRemoved → Delete binary
    │
    └── Playback events → PlaybackService
        ├── PlaybackStart → Resolve devices + Start players
        ├── PlaybackProgress → Forward pause/seek
        └── PlaybackStopped → Stop players
```

### Library exclusion flow

```
OnItemAdded(item)
├── Check item.Type == "Movie" || "Episode"
├── GetLibraryId(item) → walk parent chain
├── Check libraryId NOT in ExcludedLibraryIds
│   ├── Normalize: remove dashes, lowercase
│   └── Compare against normalized excluded list
└── If passes: queue extraction in Task.Run
```

### Scheduled task flow

```
ExtractPendingAmbilightTask.ExecuteAsync()
├── Initialize services (storage, extractor)
├── GetItemsNeedingExtraction()
│   ├── Enumerate allowed libraries
│   ├── Query Movies + Episodes
│   ├── Filter: no binary file exists
│   └── Sort by configured priority
├── Parallel.ForEachAsync(items, maxParallelism)
│   └── RunExtractorForItemAsync(item)
└── Return TaskResultStatus.Completed
```

## Thread safety

- Event handlers run on Jellyfin's thread pool
- `Task.Run` for library events (non-blocking)
- `Parallel.ForEachAsync` for batch extraction (bounded parallelism)
- `_sessionPlayers` is `ConcurrentDictionary` — safe for concurrent access
- Storage service has no internal locking (single-writer assumption)
