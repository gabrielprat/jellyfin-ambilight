# Plan: Extraction Pipeline

## Architecture

### Process model

The extractor spawns ffmpeg as a child process and reads raw video frames from its stdout via a pipe. This avoids managed memory overhead for video decoding and leverages ffmpeg's hardware acceleration.

### Resolution choice (320×180)

- LED strips have 49-89 LEDs per side — 276 total max
- 320×180 provides ~57,600 pixels for color extraction
- Each LED zone gets ~200+ pixels — sufficient for edge-weighted dominant color
- Higher resolution would slow extraction without improving LED color accuracy

### Color extraction algorithm

1. **Grayscale conversion** — Sobel operates on luminance
2. **Sobel edge detection** — 3×3 kernel (horizontal + vertical), magnitude = edge strength
3. **Gaussian center weighting** — center pixels get 30% bonus weight
4. **Combined weight** — 70% edge weight + 30% center weight
5. **Weighted average** — final LED color is weighted average of all pixels in the zone

This prioritizes edge colors (bright outlines, subtitles, text) over uniform backgrounds, producing more visually interesting ambilight effects.

### Chapter flushing logic

```
for each frame:
    buffer.append(frame)
    if buffer.size == chapterSize:
        flushChapter(buffer)
        buffer.clear()

flushChapter(buffer)  // last partial chapter
```

### Keyframe vs delta decision

```
if deltaEnabled AND lastKeyframe exists:
    changedLeds = countChangedLeds(lastKeyframe, currentFrame, threshold)
    if changedLeds > totalLeds * 0.5:
        → keyframe (too many changes for delta to be efficient)
    else:
        → delta (encode only changed LEDs)
else:
    → keyframe (no previous keyframe or delta disabled)
```

### RLE dedup within keyframes

```
group = []
for frame in chapter:
    if group.isEmpty OR framesEqual(group.last, frame):
        group.append(frame)
    else:
        writeGroup(group)  // timestamp + RGB + repeat_count
        group = [frame]
writeGroup(group)  // final group
```

## Data flow diagram

```
                    ┌─────────────┐
                    │   ffprobe   │
                    │ fps, dur    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    ffmpeg   │
                    │ RGB24 320×180│
                    └──────┬──────┘
                           │ raw frames
                    ┌──────▼──────┐
                    │  ComputeLED │
                    │    Zones    │
                    └──────┬──────┘
                           │ zone rects
                    ┌──────▼──────┐
                    │  ComputeFrame│
                    │    Colors   │
                    │ Sobel+Gauss │
                    └──────┬──────┘
                           │ LED RGB data
                    ┌──────▼──────┐
                    │  Chapter    │
                    │  Buffer     │
                    │ (48 frames) │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ FlushChapter│
                    │ key/delta   │
                    │ RLE + Deflate│
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Write .bin │
                    │ + backpatch │
                    └─────────────┘
```

## Thread safety

- `ExtractAsync` is the only public method, called from `AmbilightExtractorService`
- Concurrency is managed externally by the extractor service (semaphore + counter)
- No internal locking — single-threaded extraction per item
- Cancellation checked via `CancellationToken` in the frame reading loop
