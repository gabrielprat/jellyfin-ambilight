# Tasks: Playback Pipeline

## Done

- [x] Implement AMb2/AMb3 magic detection dispatch
- [x] Implement AMb3 header reading
- [x] Implement AMb3 seeking index reading from EOF
- [x] Implement AMb3 chunk decompression (DeflateStream)
- [x] Implement AMb3 keyframe expansion (RLE decode)
- [x] Implement AMb3 delta reconstruction (DecodeDelta against lastKeyframe)
- [x] Implement AMb2 backward-compatible path (unchanged)
- [x] Implement per-frame timestamp calculation from probed fps
- [x] Implement start frame calculation (startSeconds + syncLead)
- [x] Implement main playback loop with frame pacing
- [x] Implement adaptive gamma based on luminance
- [x] Implement per-channel gamma correction (clamped 0.1-5.0)
- [x] Implement saturation adjustment
- [x] Implement EMA smoothing (frame-rate-independent)
- [x] Implement brightness target + min LED brightness + per-channel boost
- [x] Implement LED rotation (InputPosition)
- [x] Implement UDP streaming to WLED
- [x] Implement pause handling (200ms keepalive)
- [x] Implement seek handling (position jump detection + binary search)
- [x] Implement blank-on-stop (3 zero frames)
- [x] Implement loading effect (rotating ochre segment)
- [x] Implement failure flash (3 red flashes)
- [x] Implement multi-player per session (AmbilightPlaybackService)

## Discarded

- Chunk prefetching — low value, Deflate catches corruption, disk failures are systemic
- Graceful degradation on corrupt chunks — same rationale
