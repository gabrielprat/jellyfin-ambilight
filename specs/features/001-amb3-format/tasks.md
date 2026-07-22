# Tasks: AMB3 Binary Format

## Done

- [x] Define 96-byte header struct (version, flags, duration, fps, LED counts, compression, index_offset, chunk_count, reserved)
- [x] Define 32-byte chunk header struct (timestamp, type, sizes, frame_count, brightness, flags, checksum)
- [x] Define index header + entry structs (IDX3 magic, count, entries)
- [x] Implement `IsAm3Magic()` and `IsAm2Magic()` for format detection
- [x] Implement `WriteHeader()` and `ReadHeader()`
- [x] Implement `BackpatchHeaderIndexOffset()` for post-write header fixup
- [x] Implement `WriteChunkHeader()` and `ReadChunkHeader()`
- [x] Implement `WriteIndex()` and `ReadIndex()`
- [x] Implement `ComputeAverageBrightness()` for chunk metadata
- [x] Implement `FramesEqual()` for RLE dedup
- [x] Implement `CountChangedLeds()` for delta threshold
- [x] Implement `EncodeDelta()` — changed_count + per-LED (index, RGB)
- [x] Implement `DecodeDelta()` — apply delta on keyframe copy
- [x] Implement `DecodeRleFrame()` — extract frame + repeat count
- [x] Define flag/compression/chunk-type/color/quality constants

## TODO

- [x] Scene change detection — force keyframe on hard cuts
- [ ] Chunk error recovery — detect incomplete header backpatch, fall back to sequential read

## Future nice-to-have

- [ ] VFR support — variable frame rate videos, irregular timestamps
- [ ] Migration tool — AMb2 → AMb3 in-place conversion
