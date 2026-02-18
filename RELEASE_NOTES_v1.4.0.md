# Release Notes - v1.4.0

## 🎉 Major Features

### WLED Visual Feedback
- **Loading indicator**: Rotating ochre/amber segment on WLED strip while ambilight data is loading
- **Failure notification**: Three red flashes if ambilight fails to start, then returns WLED to original state
- **User awareness**: Know immediately when ambilight is loading or if something went wrong
- **Seamless experience**: Loading effect stops automatically when ambilight broadcast begins

### Jellyfin Scheduled Tasks Integration
- **Server-side extraction queue**: "Extract All Pending" now uses Jellyfin's native scheduled task system
- **Dashboard integration**: View extraction progress in Jellyfin Dashboard → Scheduled Tasks
- **Persistent processing**: Extractions continue even if browser is closed
- **Cancellable tasks**: Stop bulk extractions from the Jellyfin dashboard
- **Progress tracking**: Real-time progress bar (0-100%) in scheduled tasks UI
- **Proper task management**: No more frontend-dependent extraction sequencing

### Improved Extractor Quality
- **Sobel edge detection**: C# extractor now matches Rust quality with edge-dominant color extraction
- **Weighted averaging**: 70% edge-based, 30% center-based color calculation
- **Accurate FPS detection**: Uses ffprobe to detect actual video FPS instead of assuming 24fps
- **Better sync**: Timestamps calculated using actual video framerate for perfect synchronization
- **Perceptually accurate**: Colors extracted based on visual saliency, not simple averaging

### Automatic Binary Cleanup
- **Library sync**: Automatically deletes `.bin` files when media items are removed from Jellyfin
- **Clean storage**: No orphaned ambilight data consuming disk space
- **Event-driven**: Uses Jellyfin's `ItemRemoved` event for instant cleanup

### Auto-Extraction Control
- **New setting**: "Extract newly added items" (default: true)
- **Granular control**: Choose whether new media triggers automatic extraction
- **Library-aware**: Respects excluded libraries configuration
- **Instant feedback**: Setting applied immediately without restart

### Enhanced Series Management
- **Series-level ordering**: Series sorted by most recently added episode, not just series creation date
- **Mixed sorting**: Movies and series properly interleaved chronologically
- **Better UX**: Series collapsed by default when extraction manager loads

### Improved Configuration UI
- **Excluded libraries as checkboxes**: Multi-select dropdown replaced with checkbox list for better visibility
- **Always visible selection**: Users can see which libraries are excluded without clicking or focusing
- **Clear visual state**: Checkmarks clearly indicate excluded libraries at a glance

## 🐛 Bug Fixes

- **Fixed "Extract All Pending"**: Now properly processes all items sequentially using scheduled tasks instead of unreliable frontend-based sequencing
- **Scheduled task API compatibility**: Fixed `MissingMethodException` by using correct Jellyfin 10.10.x API (`GetItemsResult` instead of deprecated methods)
- **Excluded libraries filtering**: Now filters at database query level for better performance and reliability
- **Extraction priority respected**: Scheduled task now properly sorts items according to user's priority setting (newest first, oldest first, alphabetical, movies first)
- **Loading effect timing**: Loading indicator now displays for the actual duration of file loading
- **FPS sync issues**: Corrected hardcoded 24fps assumption, now probes actual video framerate
- **ffprobe path**: Fixed incorrect path construction for ffprobe binary location
- **Extraction manager ordering**: Series now correctly ordered by newest episode date

## 🏗️ Technical Improvements

### Backend
- **New scheduled task**: `ExtractPendingAmbilightTask` implements `IScheduledTask` interface
- **Task API endpoint**: `POST /Ambilight/ExtractAllPending` triggers the scheduled task
- **Library filtering optimization**: Queries only allowed libraries using `Parent` parameter at database level
- **Extraction priority sorting**: Collects and sorts pending items according to user preference before processing
- **API compatibility**: Uses `GetItemsResult()` for Jellyfin 10.10.x compatibility
- **WLED effects**: `SendLoadingEffectAsync()` and `SendFailureFlashAsync()` methods for visual feedback
- **Cancellation token passing**: Loading effect CTS passed to player for proper cleanup timing
- **FPS probing**: `ProbeVideoFps()` method using ffprobe with fraction parsing (e.g., "24000/1001")
- **Edge detection**: `ExtractEdgeDominantColor()` with Sobel operator implementation
- **Item deletion handler**: `OnItemRemoved` event subscription in `AmbilightEntryPoint`
- **Configuration property**: `ExtractNewlyAddedItems` boolean in `PluginConfiguration`

### Frontend
- **Checkbox UI for exclusions**: Replaced multi-select dropdown with checkbox list for excluded libraries
- **Simplified extraction**: Frontend triggers scheduled task, server handles sequencing
- **Removed client-side queue**: No more `waitForExtractionComplete()` or frontend-based sequencing
- **Task status messages**: UI guides users to Jellyfin dashboard for progress monitoring

### API Changes
- `POST /Ambilight/ExtractAllPending`: Returns task status, triggers scheduled task
- Task manager integration for proper background processing

## 📊 Performance & Quality Improvements

- **Extraction quality**: C# extractor now matches Rust perceptual accuracy with edge detection
- **Sync accuracy**: Proper FPS detection eliminates A/V drift issues
- **Query optimization**: Excluded libraries filtered at database level instead of post-processing
- **Smart sorting**: Extraction priority applied efficiently to collected items before processing
- **Loading feedback**: Minimal overhead (~10 UDP packets/second during load)
- **Scheduled task efficiency**: No frontend memory leaks from long-running operations
- **Automatic cleanup**: Instant binary deletion on item removal

## 🔄 Migration Notes

### Breaking Changes
None. All existing configurations and data remain compatible.

### Behavioral Changes
- **"Extract All Pending" workflow**: Now triggers a Jellyfin scheduled task
  - Check Dashboard → Scheduled Tasks for progress
  - Can be cancelled from dashboard
- **Auto-extraction**: New installations auto-extract by default (configurable)
- **Extraction quality**: Re-extraction recommended for better color accuracy

### Recommended Actions
1. Review "Extract newly added items" setting in plugin configuration
2. Monitor bulk extractions via Dashboard → Scheduled Tasks
3. Consider re-extracting important content for improved quality

## 📝 Documentation Updates

- Added scheduled task integration guide
- Documented WLED visual feedback features
- Clarified auto-extraction behavior
- Added AMB3 format roadmap (`AMB3_FORMAT_ROADMAP.md`)

## 🐛 Known Issues

- Loading effect may briefly appear even for cached files (cosmetic only)
- Scheduled task progress shows item count percentage, not time-based progress

## 🙏 Acknowledgments

This release brings production-grade reliability with Jellyfin's scheduled task system, significantly improved extraction quality matching the original Rust implementation, and better user experience through visual WLED feedback. Thanks to all users for testing and feedback!

---

**Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.3.1...v1.4.0
