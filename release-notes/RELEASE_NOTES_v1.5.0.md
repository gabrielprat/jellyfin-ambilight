# Release Notes - v1.5.0

## 🎯 Overview

This release focuses on fixing hardware acceleration issues and improving project licensing transparency.

## 🐛 Bug Fixes

### Fixed Hardware Acceleration Crashes (QSV, CUDA, VideoToolbox)

**Problem:** When using Intel Quick Sync (QSV), NVIDIA CUDA, or Apple VideoToolbox hardware acceleration, the extraction process would crash with FFmpeg filter errors:

```
Impossible to convert between the formats supported by the filter 'graph -1 input from stream 0:0' and the filter 'auto_scale_0'
Error reinitializing filters!
```

**Root Cause:** Hardware-accelerated decoders output frames in GPU memory (hardware surfaces), but the `scale` filter is a software filter that expects frames in CPU memory. FFmpeg couldn't automatically convert between these incompatible formats.

**Solution:** Modified the FFmpeg filter chain to explicitly transfer frames from GPU to CPU memory before applying software filters:

```bash
# Before (broken):
-hwaccel qsv -i "video.mkv" -vf scale=320:180 ...

# After (fixed):
-hwaccel qsv -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 ...
```

The `hwdownload,format=nv12` pipeline:
1. Downloads frames from GPU to CPU memory
2. Converts to NV12 pixel format (software-compatible)
3. Allows the scale filter to work correctly

**Impact:**
- ✅ Intel Quick Sync (QSV) now works reliably on Intel CPUs (N100, etc.)
- ✅ CUDA acceleration fixed for NVIDIA GPUs
- ✅ VideoToolbox acceleration fixed for macOS systems
- ✅ VAAPI continues to work as before
- ℹ️ "Auto" mode remains unchanged (CPU-only decoding)

**Tested On:**
- Intel N100 with Linux + QSV
- Jellyfin transcoding environment

## 📄 Licensing

### Added GPLv3 License

The project is now officially licensed under the **GNU General Public License v3.0**:

- ✅ Added complete LICENSE file with GPLv3 text
- ✅ Added SPDX license headers to all source files
- ✅ Updated project metadata in `.csproj` file
- ✅ Documented license terms and freedoms in README
- ✅ Added copyright attribution to "Jellyfin Ambilight Contributors"

**What this means:**
- You're free to use, modify, and distribute this software
- Any distributed modifications must also be licensed under GPLv3
- Source code must remain available

For details, see the [LICENSE](../LICENSE) file or visit https://www.gnu.org/licenses/gpl-3.0.html

## 🔧 Project Improvements

### Reorganized Release Notes

- Created dedicated `release-notes/` folder for all version release notes
- Updated GitHub Actions workflow to read from new location
- Improved workflow robustness when release notes are missing
- Release notes now automatically included in GitHub releases

## 📝 Migration Notes

### For Users

**No action required** - simply update to v1.5.0:

1. Download the latest plugin from the releases page
2. Replace `Jellyfin.Plugin.Ambilight.dll` in your plugins folder
3. Restart Jellyfin

If you were previously unable to use QSV/CUDA/VideoToolbox acceleration, you can now enable it in the plugin settings.

### For Developers

If you're forking or contributing to this project, please note:
- The project is now GPLv3-licensed
- All source files include SPDX license headers
- Any contributions must be compatible with GPLv3

## 🔗 Links

- **Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.4.2...v1.5.0
- **License**: [LICENSE](../LICENSE)
- **Installation Guide**: [README.md](../README.md#installation)

---

**Upgrade Today!** 🚀
