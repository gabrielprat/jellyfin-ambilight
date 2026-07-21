# Release Notes - v2.3.0

## Improved Bright Spot Colors

Per-zone luminance scaling in the extractor now applies gamma correction (power 0.45) and clamps the scale factor to a safe range (0.25–3.0×). Individual color channels are also capped at 255 to prevent clipping. Bright areas of the video now produce vibrant but non-washed-out LED colors, and dark zones no longer get artificially boosted.

## Scene Change Snapping During Playback

When a hard cut is detected during playback (≥40% of LEDs changed between consecutive frames, configurable via **Scene Change Threshold**), the temporal smoothing accumulator resets immediately so LED colors snap to the new scene instead of blending from the previous one for several frames. EMA is also reset on seek for instant color recovery.

## RGBW Documentation

The README now documents that RGBW LED strips are not supported through the plugin's UDP port 19446, and explains the protocol limitation for users with RGBW hardware.
