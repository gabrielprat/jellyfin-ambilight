# Release Notes - v1.3.0

## 🎉 Major Features

### Real-Time Extraction Progress
- **Frame-based progress tracking**: See exactly how many frames have been extracted (e.g., "12,345 / 180,173")
- **Live progress updates**: Progress refreshes every 5 seconds during extraction
- **Visual indicators**: Animated spinning icon for active extractions
- **Persistent state**: In-memory cache ensures progress persists across UI refreshes

### Batch API for Performance
- **Single batch request**: Extraction Manager loads all video statuses with one API call instead of hundreds
- **Optimized polling**: Only polls videos that are currently extracting
- **Reduced server load**: Progress reports every 200 frames instead of every frame
- **Faster UI**: Dramatically improved load times for libraries with 1000+ videos

### Hardware Acceleration Support
- **Configurable acceleration**: Choose between Auto (CPU), VAAPI, CUDA, QSV, VideoToolbox, and more
- **Better error reporting**: ffmpeg stderr output logged when extraction fails
- **Improved compatibility**: Simplified hardware acceleration implementation for better reliability

### Enhanced UI/UX
- **Tree state preservation**: Expanded series/seasons stay expanded during status updates
- **Sequential extraction queue**: Videos extract one at a time to prevent resource exhaustion
- **Color-coded status**: Blue for extracting, green for extracted, red for failed
- **Statistics dashboard**: See extraction counts by status at a glance

## 🐛 Bug Fixes

- **Graceful cancellation handling**: No more error logs when restarting Jellyfin during extraction
- **Fixed status persistence**: Extracting videos correctly show their status after page reload
- **Automatic extraction efficiency**: Only processes newly added items instead of scanning entire library
- **Minimal logging**: Debug mode disabled now produces minimal logs as expected

## 🏗️ Technical Improvements

### Backend
- Added `POST /Ambilight/Status/Batch` API endpoint for efficient batch status retrieval
- Implemented in-memory progress cache to avoid excessive disk writes
- Extended `AmbilightItem` model with `ExtractionFramesCurrent` and `ExtractionFramesTotal`
- Added `OperationCanceledException` handling in extraction service
- Improved ffmpeg argument builder for hardware acceleration

### Frontend
- Removed unused `managerPage.html` (293 lines)
- Consolidated all extraction manager logic into `configPage.html`
- Implemented session-based tree state tracking with `Set` objects
- Added thousands separator formatting for frame counts
- Optimized polling to only track actively extracting videos

### Code Quality
- Added hardware acceleration setting to `PluginConfiguration`
- Improved error logging with debug mode checks throughout codebase
- Cleaned up obsolete localStorage usage
- Enhanced progress reporting with `IProgress<(ulong, ulong)>` pattern

## 📊 Performance Metrics

- **UI Load Time**: Reduced from ~1000 requests to 1 batch request for initial load
- **Progress Overhead**: Reduced from 50-frame to 200-frame reporting intervals
- **Polling Frequency**: Optimized from 2s to 5s to reduce server load
- **DLL Size**: 182KB (increased from 173KB due to new features)

## 🔄 Migration Notes

No breaking changes. Existing configurations and extracted data remain fully compatible.

## 📝 Updated Documentation

- Updated README.md with hardware acceleration options
- Clarified extraction manager behavior and queueing system
- Added release workflow documentation in PUBLISHING.md

## 🙏 Acknowledgments

This release includes significant performance optimizations and UX improvements based on real-world usage feedback. Special thanks to all users who reported issues and tested early builds.

---

**Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.2.3...v1.3.0
