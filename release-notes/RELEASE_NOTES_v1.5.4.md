# Release Notes - v1.5.4

## 🐛 Critical Hardware Acceleration Fix

This patch release fixes the hardware acceleration issues that persisted in v1.5.1 and v1.5.3.

### Fixed Hardware Acceleration for Real

**Problem:** Previous attempts to fix hardware acceleration (v1.5.0, v1.5.1, v1.5.3) still failed with errors:

**QSV Error:**
```
[hwdownload @ 0x...] Invalid output format yuv420p for hwframe download.
[hwdownload @ 0x...] Invalid output format nv12 for hwframe download.
```

**VAAPI Error:**
```
Impossible to convert between the formats supported by the filter
```

**Root Cause:** The issue was with specifying an explicit pixel format after `hwdownload`. Both `nv12` and `yuv420p` are not valid output formats for the `hwdownload` filter in FFmpeg. The filter needs to auto-negotiate the correct format.

**Solution:** Removed the explicit format specification entirely and let FFmpeg automatically negotiate the correct format:

```bash
# v1.5.3 and earlier (broken):
-hwaccel qsv -i "video.mkv" -vf hwdownload,format=yuv420p,scale=320:180 ...

# v1.5.4 (fixed):
-hwaccel qsv -i "video.mkv" -vf hwdownload,scale=320:180 ...
```

By removing the `format=` specification, FFmpeg automatically selects the appropriate intermediate format between the hardware decoder and software scale filter.

**Impact:**
- ✅ Intel Quick Sync (QSV) now works correctly on N100 and other Intel CPUs
- ✅ VAAPI fully functional on Intel/AMD GPUs
- ✅ CUDA acceleration fixed for NVIDIA GPUs
- ✅ VideoToolbox acceleration fixed for macOS systems
- ✅ "Auto" mode remains unchanged (CPU-only decoding)

**Tested On:**
- Intel N100 with Linux + QSV ✅
- Intel iGPU with VAAPI ✅

## 📝 What Changed from v1.5.3

**Code Changes:**
- Removed explicit pixel format specification in hardware acceleration filter chain
- FFmpeg now auto-negotiates the correct format

**No other changes:**
- Workflow fixes from v1.5.3 remain in place
- `manifest.json` properly tracked and updated by CI/CD
- GPLv3 licensing from v1.5.0

## 🔄 Version History Summary

- **v1.5.0**: First attempt - used `format=nv12` (failed)
- **v1.5.1**: Second attempt - used `format=yuv420p` (failed)
- **v1.5.3**: Workflow fixes, no code changes to acceleration (still broken)
- **v1.5.4**: Final fix - removed format specification (working!)

## 📝 Migration Notes

### For Users

**HIGHLY RECOMMENDED UPGRADE** if you're using or want to use hardware acceleration:

1. Download v1.5.4 from the releases page
2. Replace `Jellyfin.Plugin.Ambilight.dll` in your plugins folder
3. Restart Jellyfin
4. Enable hardware acceleration in plugin settings (QSV, VAAPI, CUDA, or VideoToolbox)
5. Re-run any failed extractions

### Expected Behavior

After upgrading:
- Hardware-accelerated extraction should complete successfully
- No more "Invalid output format" or "Impossible to convert" errors
- Extraction speed should be significantly faster with hardware acceleration enabled

## 🔗 Links

- **Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.5.3...v1.5.4
- **Previous Release**: [v1.5.3](RELEASE_NOTES_v1.5.3.md)
- **Installation Guide**: [README.md](../README.md#installation)

---

**Third time's the charm! Hardware acceleration finally works! 🎉🚀**
