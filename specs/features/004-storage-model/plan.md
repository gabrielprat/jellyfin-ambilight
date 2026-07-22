# Plan: Storage Model

## Architecture decisions

### Why file-based (not SQLite/EF Core)

- Simplicity: JSON files are human-readable, easy to debug, easy to backup
- No migrations: adding fields to `AmbilightItem` doesn't break existing files
- Jellyfin already manages its own database — plugin shouldn't add another
- File count is bounded by media library size (thousands, not millions)
- Binary data (`.bin`) is inherently file-based — can't store 200MB blobs in SQLite efficiently

### Why in-memory progress cache

- Extraction updates progress every frame (24-60 times/second)
- Writing JSON to disk 24-60x/sec would be I/O thrash
- Cache is cleared when extraction completes
- `GetItem()` merges cache on read — no stale data

## Data model

### JSON metadata file structure

```json
{
  "Id": "b3f6b4c7-...",
  "LibraryId": "abc123...",
  "Name": "Movie Title",
  "Type": "Movie",
  "Kind": "Movie",
  "Season": null,
  "Episode": null,
  "FilePath": "/media/movies/title.mkv",
  "JellyfinDateCreated": "2024-01-15T10:30:00Z",
  "CreatedAt": "2024-01-15T12:00:00+00:00",
  "UpdatedAt": "2024-01-15T12:05:30+00:00",
  "ExtractionStatus": "completed",
  "ExtractionError": null,
  "ExtractionAttempts": 1,
  "ExtractionFramesCurrent": 0,
  "ExtractionFramesTotal": 0,
  "ExtractedByPluginVersion": "2.0.0",
  "BinaryFormat": "amb3",
  "ExtractionTopLedCount": 89,
  "ExtractionRightLedCount": 49,
  "ExtractionBottomLedCount": 89,
  "ExtractionLeftLedCount": 49,
  "Viewed": false
}
```

### Storage operations

```
GetItem(id)         → read JSON + merge cache → AmbilightItem?
SaveOrUpdateItem()  → set timestamps → serialize JSON → write to disk
UpdateExtractionProgress()  → update in-memory cache only
ClearExtractionProgress()   → remove from cache
EnumerateItems()    → scan *.ambilight.json → yield AmbilightItem[]
GetBinaryPath(id)   → return path string
BinaryExists(id)    → File.Exists check
GetStatistics()     → count total/extracted/failed
CleanupStuckExtractions()  → reset "extracting"/"queued" → "pending"
```

### Concurrency

- `AmbilightStorageService` is instantiated once per `AmbilightEntryPoint` lifetime
- No internal locking — file operations are atomic enough for single-writer
- Extraction service is the only writer during extraction
- Playback service is read-only
- REST API is read-only (except config updates)
