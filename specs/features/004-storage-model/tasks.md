# Tasks: Storage Model

## Done

- [x] Define `AmbilightItem` class (26 properties)
- [x] Define `StorageStatistics` class (total/extracted/failed)
- [x] Implement `GetItem()` — read JSON + merge cache
- [x] Implement `SaveOrUpdateItem()` — set timestamps, serialize, write
- [x] Implement `UpdateExtractionProgress()` — in-memory cache update
- [x] Implement `ClearExtractionProgress()` — cache removal
- [x] Implement `EnumerateItems()` — scan `*.ambilight.json` files
- [x] Implement `GetBinaryPath()` — return `.bin` path
- [x] Implement `BinaryExists()` — file existence check
- [x] Implement `GetStatistics()` — count items by status
- [x] Implement `CleanupStuckExtractions()` — reset stuck items on startup
- [x] Add `BinaryFormat` field to `AmbilightItem` ("amb2" or "amb3")
- [x] Handle corrupt/empty JSON files (delete + return null)

## TODO

(none)

## Future nice-to-have

- [ ] File integrity validation — check `.bin` magic bytes on read
- [ ] Migration support — update `BinaryFormat` after AMb2 → AMb3 conversion
