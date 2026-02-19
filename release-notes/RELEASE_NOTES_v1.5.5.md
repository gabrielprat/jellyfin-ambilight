# Release Notes - v1.5.5

## 🔄 Hardware Acceleration Fix - Reverted to v1.4.2 Approach

This release fixes the hardware acceleration issues that were introduced in v1.5.0 and persisted through v1.5.4 by reverting to the proven v1.4.2 implementation.

## 🐛 Problem Summary

Versions v1.5.0 through v1.5.4 attempted to fix hardware acceleration but introduced breaking changes:

### What Went Wrong

**v1.5.0-v1.5.4 Errors:**

With **QSV** (Intel Quick Sync):
```
[hwdownload @ 0x...] Invalid output format nv12 for hwframe download.
[hwdownload @ 0x...] Invalid output format yuv420p for hwframe download.
Failed to configure output pad on Parsed_hwdownload_0
```

With **VAAPI**:
```
Impossible to convert between the formats supported by the filter
Error reinitializing filters!
```

### Root Cause

The v1.5.0-v1.5.4 releases tried to explicitly manage frame transfers from GPU to CPU using FFmpeg's `hwdownload` filter with various format specifications. This approach didn't work correctly with FFmpeg in Jellyfin's environment.

**v1.4.2 (working)** used a simpler approach: enable hardware acceleration for decoding only and let FFmpeg automatically handle any necessary format conversions.

## ✅ Solution - Reverted to v1.4.2

This release reverts the hardware acceleration implementation to match v1.4.2 exactly:

```bash
# v1.5.0-v1.5.4 (broken):
-hwaccel vaapi -i "video.mkv" -vf hwdownload,format=...,scale=320:180 ...

# v1.4.2 & v1.5.5 (working):
-hwaccel vaapi -i "video.mkv" -vf scale=320:180 ...
```

### What Changed

**Code Changes:**
- Removed all `hwdownload` filter logic
- Removed explicit format specifications (`format=nv12`, `format=yuv420p`)
- Restored simple filter chain: just `scale=` for resizing
- Hardware acceleration is used **only for video decoding**
- FFmpeg automatically transfers frames to CPU memory as needed

**Result:**
- ✅ VAAPI working correctly (tested on Intel N100)
- ✅ Intel Quick Sync (QSV) should work as it did in v1.4.2
- ✅ CUDA acceleration should work
- ✅ VideoToolbox acceleration should work
- ✅ "Auto" mode unchanged (CPU-only decoding)

## 📊 Version History

| Version | Approach | Status |
|---------|----------|--------|
| v1.4.2 | Simple hardware decoding | ✅ Working |
| v1.5.0 | Added `hwdownload,format=nv12` | ❌ Failed |
| v1.5.1 | Changed to `format=yuv420p` | ❌ Failed |
| v1.5.3 | Workflow fixes only | ❌ Still broken |
| v1.5.4 | Removed format, kept hwdownload | ❌ Still failed |
| **v1.5.5** | **Reverted to v1.4.2 approach** | **✅ Working** |

## 📝 What's Included

This release includes:
- ✅ Hardware acceleration fix (reverted to v1.4.2)
- ✅ GPLv3 licensing (from v1.5.0)
- ✅ Workflow fixes for manifest.json (from v1.5.3)
- ✅ All features from v1.4.0+ (scheduled tasks, extraction priority, etc.)

## 🔧 Migration Notes

### For Users

**Highly Recommended Upgrade** if you want to use hardware acceleration:

1. Download v1.5.5 from the releases page
2. Replace `Jellyfin.Plugin.Ambilight.dll` in your plugins folder: `/config/plugins/Ambilight/`
3. Restart Jellyfin
4. Enable hardware acceleration in plugin settings (VAAPI, QSV, CUDA, or VideoToolbox)
5. Run extractions - they should now work with hardware acceleration

### Expected Behavior

After upgrading to v1.5.5:
- Hardware-accelerated extraction should complete successfully
- No more "Invalid output format" or "Impossible to convert" errors
- Extraction speed should be significantly faster with hardware acceleration
- Works exactly as v1.4.2 did with hardware acceleration

### If You're on v1.4.2

You can safely upgrade to v1.5.5 to get:
- GPLv3 licensing
- Improved GitHub workflow
- All the features from v1.4.0-v1.4.2
- Same reliable hardware acceleration you already have

## 🙏 Apologies

We apologize for the issues with hardware acceleration in v1.5.0-v1.5.4. The attempt to improve hardware acceleration handling actually broke it. This release restores the proven, working implementation from v1.4.2.

## 🔗 Links

- **Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.4.2...v1.5.5
- **Previous Working Release**: [v1.4.2](https://github.com/gabrielprat/jellyfin-ambilight/releases/tag/v1.4.2)
- **Installation Guide**: [README.md](../README.md#installation)

---

**Hardware acceleration restored to working state!** 🎉✅
