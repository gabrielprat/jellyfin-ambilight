# Changelog

All notable changes to the Jellyfin Ambilight Plugin will be documented in this file.

## [2.0.0] - Unreleased

### Changed
- **Smoothing window default** — Changed from 0.12s to 0.06s for more responsive color transitions.
- **Removed Brightness target, Min LED brightness, and R/G/B boost settings** — These settings caused blue color tint in dark scenes. Visual tuning now consists of gamma (global + per-channel), saturation, and smoothing only.

### Added
- **LED strip gap configuration** — Per-device `Gap Length` and `Gap Position` settings to handle physical LED strips with a data cable gap at any position. Gap LEDs are zeroed out in the output frame after Input Position rotation, matching HyperHDR's gap feature.

## [1.7.0] - 2026-03-07

### Changed
- **RGB-only extraction pipeline** - Removed the RGBW extraction configuration option and all RGBW extraction/runtime paths so AMb2 generation and playback consistently use RGB (3 channels).
- **Configuration and docs cleanup** - Removed RGBW references from settings/docs and clarified `Input Position` ordering from the viewer perspective (`0` top-left, then clockwise).

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
