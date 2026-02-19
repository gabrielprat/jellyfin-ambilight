# Release Notes - v1.5.1

## 🐛 Critical Bug Fix

This is a patch release that fixes a hardware acceleration regression introduced in v1.5.0.

### Fixed Hardware Acceleration Format Issue

**Problem:** In v1.5.0, we attempted to fix hardware acceleration by using `format=nv12` after `hwdownload`, but this caused failures on Intel Quick Sync and other hardware accelerators:

```
[hwdownload @ 0x...] Invalid output format nv12 for hwframe download.
```

Additionally, VAAPI stopped working with the error:
```
Impossible to convert between the formats supported by the filter
```

**Root Cause:** The `nv12` format is not a valid output format for the `hwdownload` filter in many FFmpeg configurations. It's a hardware surface format that cannot be directly used as a software filter input.

**Solution:** Changed the pixel format from `nv12` to `yuv420p`, which is the standard planar YUV 4:2:0 format universally supported by software filters:

```bash
# v1.5.0 (broken):
-hwaccel qsv -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 ...

# v1.5.1 (fixed):
-hwaccel qsv -i "video.mkv" -vf hwdownload,format=yuv420p,scale=320:180 ...
```

**Impact:**
- ✅ Intel Quick Sync (QSV) now works correctly
- ✅ VAAPI restored to working state
- ✅ CUDA acceleration fixed
- ✅ VideoToolbox acceleration fixed

**Tested On:**
- Intel N100 with Linux + QSV
- Intel iGPU with VAAPI

## 📝 What Changed from v1.5.0

This is a minimal patch release with only one change:
- Pixel format in hardware acceleration filter chain: `nv12` → `yuv420p`

All other features and improvements from v1.5.0 remain unchanged:
- GPLv3 licensing
- Reorganized release notes structure
- Updated GitHub Actions workflow

## 📝 Migration Notes

### For Users

**Highly Recommended Upgrade** if you're using hardware acceleration:

1. Download v1.5.1 from the releases page
2. Replace `Jellyfin.Plugin.Ambilight.dll` in your plugins folder
3. Restart Jellyfin

If you experienced extraction failures with v1.5.0, this release should resolve them.

### For v1.5.0 Users

If you installed v1.5.0 and hardware acceleration wasn't working:
- Simply upgrade to v1.5.1
- Re-run any failed extractions from the Manager tab

## 🔗 Links

- **Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.5.0...v1.5.1
- **Previous Release**: [v1.5.0](RELEASE_NOTES_v1.5.0.md)
- **Installation Guide**: [README.md](../README.md#installation)

---

**Sorry for the inconvenience in v1.5.0!** This patch should resolve all hardware acceleration issues. 🚀
