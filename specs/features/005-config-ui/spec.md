# Feature 006: Configuration UI

## Summary

Embedded vanilla HTML/JS page served by Jellyfin's plugin system. Provides settings management and an extraction manager with video list, progress tracking, and batch operations.

## Problem

Users need a way to configure the plugin (LED counts, WLED devices, visual tuning, AMB3 settings) and manage extractions (trigger, monitor, cancel) without leaving the Jellyfin web interface.

## Acceptance criteria

### Page structure

1. Single HTML file: `Configuration/configPage.html`, embedded as a resource.
2. Two tabs: **Settings** and **Extraction Manager** (switched via select dropdown).
3. Vanilla JS — no frameworks, no build step, no external dependencies.
4. Plugin GUID in JS: `b3f6b4c7-0a3d-4bd4-a7e3-c8d5a0a1e3f0` (for Jellyfin API auth).

### Settings tab sections

5. **Extraction:** ExtractNewlyAddedItems (checkbox), ExtractionPriority (select), MaxConcurrentExtractions (number), ExcludedLibraries (dynamic checkboxes from Jellyfin user views), HardwareAcceleration (select).
6. **AMB3 Format Settings:** Amb3ChapterSizeFrames (number, default 48), Amb3DeltaThreshold (number, default 10), Amb3DeltaFallbackToKeyframe (checkbox, default true).
7. **Extraction LED Configuration:** Top/Bottom/Left/Right LED counts, AmbilightDataFolder with folder browser modal (uses Jellyfin `Environment/Drives` + `DirectoryContents` + `ParentPath` APIs).
8. **WLED Device Mappings:** Dynamic card-based UI. Each card: device select (from Jellyfin Devices API), host input, port input, remove button, LED config grid (Top/Bottom/Left/Right LEDs, InputPosition). Duplicate detection by device+host+port.
9. **Lightning Tuning:** SmoothSeconds, Gamma, Saturation, BrightnessTarget, per-channel gamma (R/G/B), per-channel boost (R/G/B), MinLedBrightness.
10. **Debug:** Enable debug logging checkbox.

### Extraction Manager tab

11. Video list with tree view (Series > Season > Episodes).
12. Batch status via `/Ambilight/Status/Batch` API.
13. Type filter (Movie/Episode), status filter (extracted/pending/failed), search filter.
14. Extract/Delete/Cancel buttons per video.
15. Extract All Pending button.
16. Progress polling every 5 seconds during active extractions.
17. Statistics display (extracted/pending/failed/disk usage).

### Folder browser

18. Modal dialog for selecting AmbilightDataFolder.
19. Uses Jellyfin `Environment/Drives` to list available drives.
20. Uses `Environment/DirectoryContents` to list folder contents.
21. Uses `Environment/ParentPath` for navigation.

### Device mapping

22. Device select populated from Jellyfin `Devices` API.
23. Stores `DeviceIdentifier` as device name.
24. Duplicate detection prevents same device+host+port combination.
25. LED config grid shows per-side counts and InputPosition.

## Implementation file

`Configuration/configPage.html` — 1814 lines.
