# Tasks: Extraction Pipeline

## Done

- [x] Implement `ProbeVideoFps()` — ffprobe avg_frame_rate, fraction parsing, 24fps fallback
- [x] Implement `ProbeVideoDuration()` — ffprobe format=duration, 60s fallback
- [x] Implement `ResolveFfmpegPath()` — PATH → `/usr/lib/jellyfin-ffmpeg/` → `/usr/bin/` → fallback
- [x] Implement `BuildFfmpegArguments()` — hw accel, scale=320:180, format=rgb24, rawvideo pipe
- [x] Implement `ComputeLedZones()` — divide screen edges into rectangular zones
- [x] Implement `ComputeFrameColors()` — per-zone `ExtractEdgeDominantColor()`
- [x] Implement `ExtractEdgeDominantColor()` — Sobel + Gaussian center weighting
- [x] Implement chapter buffering (48-frame default)
- [x] Implement `FlushChapter()` — keyframe vs delta, RLE dedup, Deflate compression
- [x] Implement AMb3 header write with placeholder fields
- [x] Implement seeking index construction and header backpatch
- [x] Implement atomic write (`.tmp` + `File.Move`)
- [x] Wire extraction to use real probed fps for timestamps

## TODO

- [x] Scene change detection — force keyframe on hard cuts (uses Amb3Format chunk type)

## Future nice-to-have

- [ ] VFR support — handle irregular timestamps from variable frame rate sources
