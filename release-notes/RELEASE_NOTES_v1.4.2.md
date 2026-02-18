# Release Notes - v1.4.2

## 🐛 Bug Fixes

### Hardware Acceleration Fix
- **Fixed Intel Quick Sync (qsv) extraction crashes**: Hardware-accelerated decoding now properly transfers frames from GPU to CPU before filtering
- **Fixed VAAPI extraction issues**: Corrected filter chain to use `hwdownload` for proper format conversion
- **Fixed CUDA extraction issues**: Added proper GPU-to-CPU transfer for NVIDIA hardware acceleration
- **Fixed VideoToolbox extraction issues**: Added proper GPU-to-CPU transfer for Apple hardware acceleration

## 🏗️ Technical Details

### The Problem
When hardware acceleration was enabled (QSV, VAAPI, CUDA, VideoToolbox), FFmpeg would decode frames directly into GPU memory (hardware surfaces). The standard `scale` filter expected CPU memory (software frames), causing this error:

```
Impossible to convert between the formats supported by the filter 'graph -1 input from stream 0:0' and the filter 'auto_scale_0'
Error reinitializing filters!
```

### The Solution
Updated FFmpeg filter chains to explicitly transfer frames from GPU to CPU before scaling:

**Intel Quick Sync (qsv)**:
```bash
-hwaccel qsv -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 -pix_fmt rgb24
```

**VAAPI (Intel/AMD on Linux)**:
```bash
-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 -pix_fmt rgb24
```

**CUDA (NVIDIA)**:
```bash
-hwaccel cuda -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 -pix_fmt rgb24
```

**VideoToolbox (Apple)**:
```bash
-hwaccel videotoolbox -i "video.mkv" -vf hwdownload,format=nv12,scale=320:180 -pix_fmt rgb24
```

The filter chain now:
1. `hwdownload`: Transfers frames from GPU memory to CPU memory
2. `format=nv12`: Converts to a software-compatible pixel format
3. `scale=320:180`: Performs standard software scaling (now works!)
4. `-pix_fmt rgb24`: Final output format for color extraction

### Impact
- Hardware acceleration now works correctly for all supported modes
- Extraction speed benefits from GPU decoding while maintaining compatibility
- Auto mode (CPU-only) remains unchanged and most compatible

## 🔄 Migration Notes

No configuration changes needed. If you previously had hardware acceleration enabled but extraction was failing, it will now work correctly.

### Recommended Actions
If you disabled hardware acceleration due to crashes, you can now safely re-enable it:
1. Go to plugin settings → Hardware acceleration
2. Select your hardware (QSV, VAAPI, CUDA, or VideoToolbox)
3. Save settings
4. Extraction will now use GPU decoding for better performance

## 🙏 Acknowledgments

Thanks to users who reported the hardware acceleration crashes and provided detailed error logs. This fix ensures reliable extraction across all acceleration modes!

---

**Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.4.1...v1.4.2
