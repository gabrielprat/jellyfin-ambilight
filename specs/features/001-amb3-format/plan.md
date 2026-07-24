# Plan: AMB3 Binary Format

## Architecture decisions

### Why Deflate (not LZ4/Zstd)

- `System.IO.Compression.DeflateStream` is built into .NET 8 — zero NuGet dependencies
- AMb3 targets server-side extraction where CPU is less constrained than embedded
- Deflate ratio is sufficient for the ~60-75% reduction target
- LZ4/Zstd would add a NuGet dependency, violating the no-external-dependencies principle

### Why chapter-based, not flat frames

- Deflate works on contiguous byte streams — chapter boundaries create independent compression blocks
- Independent chunks enable seeking via the index (jump to chunk, decompress, scan frames)
- Chapter granularity (48 frames) is small enough for seeking precision, large enough for compression ratio
- Delta encoding is bounded to the last keyframe within the chapter chain

### Why fixed frame count (not time-based) for chapters

- Frame-level timestamps are the sync primitive — chapter size affects compression, not sync
- Fixed frame count (48) is simpler than time-based calculation (no fps multiplication)
- At 24fps: ~2s per chapter. At 30fps: ~1.6s. At 60fps: ~0.8s. All acceptable.
- RLE dedup groups consecutive identical frames regardless of chapter boundaries

### Why backpatch the header

- The extractor doesn't know total frame count or chunk count until extraction completes
- Writing the header first with placeholder values, then seeking back to fill them, avoids buffering the entire header in memory
- Atomic write via `.tmp` + `File.Move(overwrite: true)` ensures no partial files on crash

## Data flow

```
ffprobe → fps, duration
    ↓
ffmpeg → raw RGB24 frames (320×180)
    ↓
ComputeLedZones() → LED zone rectangles
    ↓
ComputeFrameColors() → per-LED RGB (Sobel + Gaussian)
    ↓
Buffer frames into chapter (48 frames)
    ↓
FlushChapter():
    ├── Keyframe path: RLE dedup → timestamp + RGB + repeat_count
    └── Delta path: EncodeDelta() → timestamp + changed LEDs
    ↓
DeflateStream.Compress() → compressed chapter data
    ↓
Write chunk header + compressed data
    ↓
After all frames:
    ├── Write seeking index (IDX3)
    └── Backpatch header (index_offset, chunk_count)
```

## Key algorithms

### Delta encoding (`Amb3Format.EncodeDelta`)

1. Compare current frame to last keyframe
2. For each LED, if any channel diff > threshold (default 10): mark as changed
3. Write changed_count + (index, RGB) for each changed LED
4. If >50% LEDs changed: discard delta, write keyframe instead (fallback)

### RLE dedup (`Amb3Format.DecodeRleFrame`)

1. Consecutive frames with identical RGB data are grouped
2. Each group stores the frame data once + a repeat count (int32)
3. Player expands: `for (int i = 0; i < repeatCount; i++) yield frame`

### Seeking index construction

1. During extraction, record `(timestampUs, fileOffset, chunkIndex)` per chapter
2. After all chapters written, seek to end of file
3. Write IDX3 magic + entry count + entries
4. Backpatch header `index_offset` with the file position where index starts

## File layout

```
[0..3]      Magic "AMb3"
[4..99]     Header (96 bytes)
[100..]     Chunk 0 (32B header + compressed data)
            Chunk 1 (32B header + compressed data)
            ...
            Chunk N-1
            IDX3 index (8 + 20*N bytes)
```

## Risk: header backpatch failure

If the process crashes between writing chunks and backpatching the header, the file has valid chunks but `index_offset=0` and `chunk_count=0`. The player should detect this and fall back to sequential chunk reading (scan from header offset until EOF).
