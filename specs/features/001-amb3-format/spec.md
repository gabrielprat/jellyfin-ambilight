# Feature 001: AMB3 Binary Format Specification

## Summary

Define the AMb3 binary format that replaces AMb2 for all new extractions. AMb3 adds Deflate compression, delta encoding, RLE dedup, and a seeking index — reducing file sizes by ~60-75% while maintaining frame-accurate sync.

## Problem

AMb2 stores raw RGB per frame with no compression. A 2-hour movie at 24fps produces ~850 MB of binary data. This wastes disk I/O during extraction and playback, and limits how much media can be pre-extracted.

## Acceptance criteria

### Binary structure

1. **File starts with 4-byte magic `"AMb3"`** (0x41, 0x4D, 0x62, 0x33).
2. **96-byte header** immediately follows magic, containing:
   - `version` (byte) — currently `1`
   - `flags` (byte) — bitfield: compression, VFR, multi-res, HDR, scene-change, perceptual, delta, RLE
   - `duration_us` (ulong) — total video duration in microseconds
   - `total_frames` (uint) — total frame count
   - `fps` (float) — probed average frame rate
   - `led_count_top`, `led_count_right`, `led_count_bottom`, `led_count_left` (ushort each)
   - `compression` (byte) — 0=none, 1=Deflate
   - `index_offset` (ulong) — byte offset to seeking index (backpatched after write)
   - `chunk_count` (uint) — number of chapters (backpatched after write)
   - 26 bytes reserved (zero-filled)
3. **Chapters (chunks)** follow header sequentially:
   - 32-byte chunk header per chapter
   - Deflate-compressed payload
4. **Seeking index** at EOF:
   - 4-byte magic `"IDX3"`
   - 4-byte entry count (uint)
   - 20-byte entries: `timestamp_us` (ulong) + `file_offset` (ulong) + `chunk_index` (uint)

### Chunk header (32 bytes)

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | `timestamp_us` — first frame timestamp |
| 8 | 1 | `chunk_type` — 0=keyframe, 1=delta, 2=RLE |
| 9 | 8 | `compressed_size` — payload size after Deflate |
| 17 | 8 | `uncompressed_size` — payload size before Deflate |
| 25 | 4 | `frame_count` — frames in this chapter |
| 29 | 1 | `brightness` — average frame brightness (0-255) |
| 30 | 1 | `flags` — reserved |
| 31 | 4 | `checksum` — reserved (zero) |

### Keyframe payload

Each keyframe entry:
- `timestamp_us` (ulong) — frame timestamp in microseconds
- RGB data (N bytes = total_leds × 3)
- `repeat_count` (int) — consecutive identical frames (RLE dedup)

### Delta payload

Each delta entry:
- `timestamp_us` (ulong) — frame timestamp in microseconds
- `changed_count` (ushort) — number of changed LEDs
- Per changed LED: `led_index` (ushort) + RGB (3 bytes)

### Seeking index

- Magic `"IDX3"` (4 bytes)
- Entry count (uint, 4 bytes)
- Entries: `timestamp_us` (8) + `file_offset` (8) + `chunk_index` (4) = 20 bytes each

## File size comparison

| Content | AMb2 | AMb3 | Savings |
|---|---|---|---|
| Movie (2h, 24fps, 276 LEDs) | ~850 MB | ~200-350 MB | 59-76% |
| Episode (45min, 24fps) | ~190 MB | ~50-90 MB | 53-74% |

## Sync invariant

**Every frame retains its own timestamp.** Chapter boundaries do not affect timing. The player reconstructs the full timestamp list from chunks and uses it for seeking, identical to AMb2's linear scan. Chapter size (default 48 frames) affects compression, not sync.

## Backward compatibility

- AMb3 files are **only written** by new extractions
- AMb2 files continue to be **fully supported** for playback
- Format detection is by 4-byte magic: `IsAm3Magic()` / `IsAm2Magic()` in `Amb3Format.cs`
- The `.bin` file extension is shared by both formats

## Implementation file

`Services/Amb3Format.cs` — 349 lines, static class with format structs, read/write helpers, delta encode/decode, RLE helpers.
