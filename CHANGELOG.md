# Changelog

All notable changes to the Jellyfin Ambilight Plugin will be documented in this file.

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
- **Configurable visual tuning** - Gamma, saturation, brightness, color boosts, and smoothing
- **RGBW support** - Full support for RGBW LED strips
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
