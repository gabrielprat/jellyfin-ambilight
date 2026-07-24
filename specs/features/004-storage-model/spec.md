# Feature 004: Storage Model

## Summary

File-based storage for ambilight data: JSON metadata per video item + binary data files (AMb2 or AMb3). No database, no migrations — just files on disk.

## Problem

Each video item needs metadata (extraction status, LED counts, format, progress) and binary data (the actual LED color frames). This must survive plugin restarts, support progress tracking during extraction, and be simple to debug/inspect.

## Acceptance criteria

### Storage layout

1. Default data folder: `/data/ambilight` (configurable via `AmbilightDataFolder`).
2. Metadata: `{DataFolder}/{itemId}.ambilight.json` — one JSON file per video item.
3. Binary data: `{DataFolder}/{itemId}.bin` — AMb2 or AMb3 format, auto-detected by magic bytes.
4. File names use Jellyfin item GUID as identifier.

### AmbilightItem model (26 properties)

5. Identity: `Id`, `LibraryId`, `Name`, `Type`, `Kind`, `Season?`, `Episode?`, `FilePath`, `JellyfinDateCreated?`
6. Timestamps: `CreatedAt`, `UpdatedAt` (DateTimeOffset)
7. Extraction: `ExtractionStatus` (pending/queued/extracting/completed/failed), `ExtractionError?`, `ExtractionAttempts`
8. Progress: `ExtractionFramesCurrent`, `ExtractionFramesTotal` (ulong)
9. Metadata: `ExtractedByPluginVersion?`, `BinaryFormat?` ("amb2" or "amb3")
10. LED config: `ExtractionTopLedCount?`, `ExtractionRightLedCount?`, `ExtractionBottomLedCount?`, `ExtractionLeftLedCount?`
11. State: `Viewed` (bool)

### In-memory progress cache

12. Extraction progress (current/total frames) is cached in-memory to avoid disk I/O on every progress update.
13. `UpdateExtractionProgress()` updates cache only.
14. `GetItem()` merges disk JSON with cached progress.
15. `ClearExtractionProgress()` removes from cache.

### Startup cleanup

16. `CleanupStuckExtractions()` runs on startup.
17. Items with status "extracting" or "queued" are reset to "pending".
18. Prevents stuck state after plugin crash or server restart during extraction.

### Error resilience

19. Corrupt/empty JSON files are detected and deleted.
20. `GetItem()` returns null for missing items (no crash).
21. `SaveOrUpdateItem()` handles directory creation if needed.

## Implementation file

`Services/AmbilightStorageService.cs` — 288 lines (includes `AmbilightItem` and `StorageStatistics` classes).
