# Feature 002: Extraction Pipeline

## Summary

Extract per-LED-zone colors from video files using ffmpeg/ffprobe, compute edge-weighted dominant colors via Sobel + Gaussian, and write AMb3 binary files with compressed chapters.

## Problem

Users add media to Jellyfin and want ambient lighting data extracted automatically. The extraction must run server-side in the background, use hardware acceleration when available, and produce accurate per-frame LED colors that match the video's visual content.

## Acceptance criteria

### Video probing

1. FPS is probed from `avg_frame_rate` via `ffprobe -show_entries stream=avg_frame_rate` — parsed as fraction (e.g. `24000/1001` → 23.976fps). Fallback: 24.0fps if probing fails.
2. Duration is probed from `format=duration` via `ffprobe -show_entries format=duration`. Fallback: 60.0s if probing fails.
3. Hardware acceleration is configurable: `auto`, `none`, `vaapi`, `qsv`, `cuda`, `videotoolbox`.

### Frame extraction

4. ffmpeg is invoked as a subprocess with args: `-hwaccel {mode} -i {path} -vf "scale=320:180,format=rgb24" -f rawvideo -pix_fmt rgb24 pipe:1`
5. Working resolution is 320×180 — sufficient for LED color extraction, fast to process.
6. Raw RGB24 frames are read from ffmpeg stdout in a blocking loop.

### Color extraction

7. LED zones are computed by `ComputeLedZones(width, height, top, right, bottom, left)` — divides screen edges into rectangular zones.
8. Zone ordering: Top (L→R), Right (T→B), Bottom (R→L), Left (B→T) — clockwise from viewer.
9. Per-zone color is computed by `ExtractEdgeDominantColor()` — Sobel edge detection (3×3 kernel on grayscale) + Gaussian center weighting (70% edge + 30% center).
10. Zone dimensions are clamped: minimum 12px, maximum 12% of frame dimension.

### AMb3 writing

11. Frames are buffered into chapters of configurable size (default 48 frames).
12. Each chapter is flushed as either:
    - **Keyframe:** consecutive identical frames grouped via RLE (frame data + repeat count)
    - **Delta:** only changed LEDs encoded against last keyframe (threshold >10 RGB units)
13. Delta fallback to keyframe when >50% of LEDs changed (configurable).
14. Chapter payload is compressed with `DeflateStream(CompressionLevel.Fastest)`.
15. After all chapters, seeking index is written (IDX3) and header is backpatched.
16. Atomic write: output to `.tmp`, then `File.Move(overwrite: true)`.

### Concurrency

17. Extraction concurrency is bounded by a manual semaphore (lock + counter) based on `MaxConcurrentExtractions` config.
18. Items queue when at capacity (status set to "queued").
19. Cancellation via per-item `CancellationTokenSource`.

### Error handling

20. ffmpeg path resolved from: PATH → `/usr/lib/jellyfin-ffmpeg/ffmpeg` → `/usr/bin/ffmpeg` → fallback string.
21. Stuck extractions ("extracting"/"queued") are reset to "pending" on plugin startup.
22. Extraction failure sets status to "failed" with error message.

## Implementation file

`Services/AmbilightInProcessExtractor.cs` — 871 lines.
