# Roadmap

## Phase history

### v1.x (shipped)

| Version | Feature |
|---|---|
| 1.0 | Initial release — AMb2 format, single-device, basic extraction |
| 1.6 | Gamma calculation fix, input position clarification |
| 1.7 | Remove RGBW extraction, runtime config loading, extraction manager polish |
| 1.8 | Parallel extractions, extract-all-pending in series, stop queued extractions |

### v2.0 (shipped)

AMb3 compressed binary format with compression, delta encoding, RLE dedup, scene change detection, and per-zone brightness.

| # | Feature | Status |
|---|---|---|
| F001 | AMb3 binary format specification (`Amb3Format.cs`) | DONE |
| F002 | Extraction pipeline rewrite (AMb3 writer) | DONE |
| F003 | Playback pipeline (AMb2/AMb3 auto-detect + reader) | DONE |
| F004 | Storage metadata (`BinaryFormat` field) | DONE |
| F005 | Version bump to 2.0.0, docs update | DONE |
| F006 | Scene change detection (hard cut → keyframe) | DONE |
| F007 | Per-zone brightness scaling during extraction | DONE |

## Future nice-to-have (not planned for now)

- VFR support — variable frame rate videos, irregular timestamps
- AMb2 → AMb3 migration tool

## Non-goals

- Client-side plugins or browser extensions
- Third-party compression libraries (stay on .NET BCL)
- Database storage (file-based is a feature, not a limitation)
- Perceptual color encoding, adaptive precision, multi-resolution extraction (over-engineering for plugin context)
- Chunk error recovery or chunk prefetching (low value for plugin context — Deflate catches corruption, disk failures are systemic)
