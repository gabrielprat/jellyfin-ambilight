# Changelog

All notable changes to the Jellyfin Ambilight Plugin will be documented in this file.

## [Unreleased]

### Fixed
- **LEDs flickered roughly once per second during normal playback** — Seek detection compared each playback progress report against the *previous* report, so the difference during steady playback was simply the reporting interval (~1s) and always exceeded the 0.5s threshold. Every progress report was therefore treated as a seek. This misclassification dates back to 1.0.0 but was harmless until 2.3.0 added an EMA reset to the seek path, at which point each false seek began discarding the smoothing accumulator and producing a visible jump. Seek detection now compares the client's reported position against the player's own position, which is independent of the reporting interval.
- **Sync lead was lost on every seek** — `AmbilightSyncLeadSeconds` was applied only when playback started, so any seek left the ambilight running behind the picture by that amount. It is now applied on seek as well.
- **Scene change snapping used the wrong LED count** — The changed-LED percentage was taken against the target (device mapping) LED count while the count itself was measured over the source frame, skewing the snap rate whenever a `.bin`'s LED counts differed from the mapping's.

## [2.4.0] - 2026-07-22

### Fixed
- **Mixed library support** — The Extraction Manager now correctly lists items from "mixed movies and shows" libraries. The config page previously filtered libraries to only `movies` and `tvshows` collection types, excluding mixed libraries. The filter has been removed since the API query already specifies `IncludeItemTypes: Movie,Episode`.

### Changed
- Added centered plugin thumbnail to the README.
- Updated plugin settings screenshot.

## [2.3.0] - 2026-07-21

### Fixed
- **Improved bright spot colors** — Per-zone luminance scaling now applies gamma correction (power 0.45) and clamps the scale factor to a safe range (0.25–3.0×), preventing oversaturation on bright zones and artificial boost on dark zones. Individual color channels are capped at 255 to prevent clipping.

### Added
- **Scene change snapping during playback** — When a hard cut is detected (≥40% of LEDs changed between consecutive frames), the temporal smoothing accumulator resets immediately so LED colors snap to the new scene instead of blending from the previous one. Also resets on seek for instant color recovery. Threshold is configurable via `Scene Change Threshold` in plugin settings.
- **RGBW documentation** — README now documents that RGBW LED strips are not supported through port 19446 and explains the protocol limitation.

## [2.2.0] - 2026-07-20

### Added
- **LED strip gap configuration** — Per-device `Gap Length` and `Gap Position` settings to handle physical LED strips with a data cable gap at any position. Gap LEDs are zeroed out in the output frame after Input Position rotation, matching HyperHDR's gap feature.
- **WLED network requirements documentation** — README now documents UDP port 19446, the 490-LED per-packet limit, and why Hyperion raw RGB is used over notifier/UDP realtime.

### Changed
- **Removed per-device port configuration** — The Port field in device mappings has been removed. The plugin now always targets WLED's Hyperion raw-RGB handler on UDP port 19446, which is hardcoded in WLED and cannot be changed. This eliminates misconfiguration issues where users set the wrong port (e.g. 21324) resulting in no ambilight effects.

## [2.0.0] - 2026-07-20

### Changed
- **Smoothing window default** — Changed from 0.12s to 0.06s for more responsive color transitions.
- **Removed Brightness target, Min LED brightness, and R/G/B boost settings** — These settings caused blue color tint in dark scenes. Visual tuning now consists of gamma (global + per-channel), saturation, and smoothing only.

## [1.7.0] - 2026-03-07

### Changed
- **RGB-only extraction pipeline** - Removed the RGBW extraction configuration option and all RGBW extraction/runtime paths so AMb2 generation and playback consistently use RGB (3 channels).
- **Configuration and docs cleanup** - Removed RGBW references from settings/docs and clarified `Input Position` ordering from the viewer perspective (`0` top-left, then clockwise).

## [1.8.0] - 2026-03-12

### Added
- **Concurrent extractions** - New setting to allow multiple simultaneous extractions (up to 10). Removed sequential limitations in the scheduled background task.
- **Stop/cancel extraction** - Stop button during active extractions in the plugin configuration UI. Cancel an ongoing extraction for an item, returning it to pending status.
- **Queueing mechanics** - Excess extractions triggered manually are queued and show a `Queued` status until a concurrency slot frees up. Queued items can also be cancelled.
- **Extract Pending batch buttons** - Extract Pending buttons on series and season headers in the Extraction Manager to quickly queue an entire series or season.

### Fixed
- **Stuck extraction states** - Videos stuck in `Extracting` or `Queued` state due to a server restart now correctly revert to `Pending` on startup.

### Changed
- **Extraction Manager layout** - Episodes are now explicitly identified with their number in a left-aligned column for better readability within a series hierarchy. Removed redundant "Movie" labels.

## [1.6.4] - 2026-03-07

### Fixed
- **Blue/white washed colors during playback** - Hardened player-side color math by clamping per-channel gamma and saturation-adjusted values before power operations, preventing invalid channel values from collapsing color output.
- **Extractor RGB consistency** - Made RGB output format explicit in the FFmpeg filter graph (`format=rgb24`) to avoid driver-dependent color conversion quirks in raw frame extraction.
- **Manifest version duplication cleanup** - Removed duplicate historical entries in `manifest.json` so each released version is listed once.

## [1.6.3] - 2026-03-06

### Fixed
- **Installed plugin thumbnail 404** - Added/validated release metadata packaging so Jellyfin can resolve `/Plugins/{id}/{version}/Image` after install.
- **Release package completeness** - Both workflows now ship `thumb.png` and `meta.json` together for every release.

## [1.6.2] - 2026-03-06

### Fixed
- **Plugin thumbnail packaging** - Release assets now always include `thumb.png` in the plugin folder so the installed plugin card can display the icon correctly in Jellyfin.
- **Installed image endpoint metadata** - Release assets now include `meta.json` with `imagePath` pointing to `thumb.png`, enabling Jellyfin's `/Plugins/{id}/{version}/Image` endpoint to locate the file.
- **Workflow parity** - Updated both release workflows to package the thumbnail consistently and fail early if the image is missing.

## [1.6.0] - 2026-03-05

### Changed
- **Serialized extraction pipeline** - Automatic extraction triggered by new library items now runs strictly one item at a time across the plugin, preventing parallel extraction jobs and reducing host CPU pressure.
- **Extraction manager storage summary** - Added a total binary disk usage counter in the manager UI with automatic unit formatting (MB/GB/TB).
- **Version bump and release metadata refresh** - Updated plugin version to `1.6.0` across build and documentation assets, and prepared release notes/manifest metadata for the new release.

## [1.5.9] - 2026-03-03

### Fixed
- **Improved pause behavior** - When playback is paused, Ambilight now continuously re-sends the last video frame to WLED so the LEDs stay frozen on that frame instead of reverting to the controller's previous effect or color. On resume, playback timing is preserved so Ambilight continues in sync with the video.

## [1.5.8] - 2026-02-27

### Changed
- **Live device mapping reload** - Device mappings created or edited in the Ambilight settings UI now take effect immediately, without requiring a Jellyfin restart. The playback service reads the latest plugin configuration on each playback event.

## [1.5.7] - 2026-02-27

### Fixed
- **Device mapping matching** - Device mappings now store the human-readable device name instead of Jellyfin internal device ID. Playback matching uses session DeviceName so mappings remain stable across sessions.

## [1.5.6] - 2026-02-27

### Fixed
- **Pause/resume ambilight sync** - Ambilight now pauses and resumes in sync with Jellyfin playback.

### Added
- **Scheduled task retries failed extractions** - Extract Pending Ambilight Data now includes previously failed items for retry.
- **Improved debug logging for device mappings** - Debug logs show device ID and mappings at play start.

## [1.5.5] - 2026-02-19

### Fixed
- **Hardware acceleration fix** - Reverted to v1.4.2 approach for VAAPI/QSV. Hardware acceleration for decoding only with simple scale filter chain.

## [1.0.0.0] - 2026-02-16

### Added
- **In-process C# implementation** - Complete rewrite from Rust daemon to C# plugin
- **Per-device WLED mappings** - Configure different WLED instances for different playback devices
- **Per-mapping LED configuration** - Each WLED mapping can have its own LED layout
- **Multi-zone support** - Map one device to multiple WLED controllers for synchronized effects
- **Automatic extraction** - Background service continuously processes new videos
- **Extraction manager** - Built-in UI to view extraction status and manually trigger extraction
- **Device ID normalization** - Automatic handling of Jellyfin web client device ID timestamps
- **Real-time playback synchronization** - Pause, resume, and seek support
- **Loading and failure effects** - Visual feedback when starting playback or on errors
- **Configurable visual tuning** - Gamma, saturation, and smoothing
- **AMb2 binary format** - Efficient compressed format for ambilight data

### Technical Details
- Target: Jellyfin 10.10+ (.NET 8)
- In-process ffmpeg-based video frame extraction
- Sobel edge detection with Gaussian center weighting
- UDP streaming to WLED controllers
- Temporal smoothing with configurable window
- Automatic LED count scaling from extraction to playback

### Migration Notes
- This version replaces the external Rust daemon approach
- Old `old-daemon-approach/` folder contains legacy implementation for reference
- Configuration is now managed entirely through Jellyfin's plugin settings UI
