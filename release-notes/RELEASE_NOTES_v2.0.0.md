# Release Notes - v2.0.0

## AMb3 Binary Format

New compressed binary format that dramatically reduces storage requirements while improving seeking performance.

- **Deflate compression** — 30-50% smaller files on top of encoding gains
- **Delta encoding** — only changed LEDs are stored between keyframes (every ~2 seconds)
- **RLE deduplication** — static scenes (credits, pauses) stored once with a repeat count
- **Chunk-based structure** — frames grouped into independently compressed chapters
- **Seeking index** — instant seeking in long files via timestamp→offset index at EOF
- **Scene change detection** — hard cuts automatically trigger keyframes to maintain accuracy
- **Per-zone brightness** — LED brightness now reflects the actual brightness of each zone in the source video

**Typical file sizes:**
| Content type | AMb2 | AMb3 |
|---|---|---|
| Typical movie (2h) | ~850 MB | 200-350 MB |
| Dialogue/slow | ~850 MB | 150-250 MB |
| Anime (limited animation) | ~850 MB | 100-200 MB |

## Backward Compatibility

- Existing AMb2 binary files continue to work unchanged
- Plugin automatically detects and plays both AMb2 (legacy) and AMb3 files
- No migration required — new extractions use AMb3, old files play as before

## Extraction Pipeline

- Rewrote extraction to produce AMb3 format with compression and delta encoding
- Added scene change detection to force keyframes on hard cuts
- Added per-zone brightness scaling based on source video luminance
- Improved atomic file writes to prevent corruption on crash

## Playback Pipeline

- Added AMb3 format detection and decompression
- Maintained full backward compatibility with AMb2 format
- Improved seeking accuracy with index-based lookup
- Added graceful handling of format detection

## Storage

- Added `BinaryFormat` field to metadata to track AMb2 vs AMb3 files
- Added runtime format detection for files without metadata
- Improved stuck extraction cleanup on startup

## Simplified Visual Settings

Removed settings that caused blue color tint in dark scenes with no practical benefit:

- **Removed Brightness target** — automatic brightness normalization was amplifying blue bias in dark scenes
- **Removed Min LED brightness** — non-zero floor forced LEDs to emit light, tinting dark scenes blue
- **Removed Red/Green/Blue boost** — dependent on Min LED brightness, removed together
- **Smoothing window default changed** from 0.12s to 0.06s for more responsive color transitions

Visual tuning now consists of: gamma (global + per-channel), saturation, and smoothing — all color-neutral settings that don't introduce bias in dark content.

## Bug Fixes

- Fixed plugin icon display in Jellyfin
- Fixed AMb3 header size calculation (96→85 bytes)
- Fixed chunk count backpatch offset (53→49)
- Fixed player seeking before header read
- Added missing RLE chunk type handling in player
