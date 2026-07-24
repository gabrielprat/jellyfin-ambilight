# Feature 003: Playback Pipeline

## Summary

Detect binary format (AMb2/AMb3) via magic bytes, reconstruct per-frame LED data, apply visual processing (gamma, saturation, smoothing, rotation), and stream raw RGB over UDP to WLED devices — all frame-synchronized with the Jellyfin player.

## Problem

Extracted ambilight data must be played back in real-time, perfectly synchronized with video playback. The player must handle seeking, pausing, multi-device output, and two binary formats transparently.

## Acceptance criteria

### Format detection and dispatch

1. Player reads first 4 bytes of `.bin` file and dispatches via `IsAm3Magic()` / `IsAm2Magic()`.
2. Unknown format: log warning, return cleanly (no crash).
3. AMb2 path unchanged: read fps + LED counts + per-frame (timestamp + RGB).
4. AMb3 path: read header, read seeking index from EOF, then read all chunks sequentially.

### AMb3 reconstruction

5. Each chunk is decompressed with `DeflateStream`.
6. **Keyframe chunks:** parse entries (timestamp + RGB + repeat_count), expand RLE, update `lastKeyframe`.
7. **Delta chunks:** parse entries (timestamp + changed_count + delta payload), decode via `Amb3Format.DecodeDelta()` against `lastKeyframe`, advance `lastKeyframe`.
8. All frames are reconstructed into in-memory lists: `frames` (RGB data) + `timestampsUs` (per-frame timestamps).

### Timing and sync

9. Per-frame timestamps are `ulong` microseconds, derived from probed fps.
10. Start frame calculated from `startSeconds + syncLead` (configurable lead time, default 0.2s).
11. Main loop calculates `frameDt = (timestampsUs[next] - timestampsUs[current]) / 1_000_000.0` for real-time pacing.
12. Seek detected by position jump >0.5s — player binary-searches `timestampsUs` list for target frame.
13. Pause: sends last frame every 200ms to prevent WLED timeout.

### Visual processing

14. Adaptive gamma based on average frame luminance.
15. Per-channel gamma correction (Red, Green, Blue — clamped 0.1-5.0).
16. Saturation adjustment.
17. Inverse gamma normalization.
18. Brightness target factor.
19. **EMA smoothing:** `k = 1 - exp(-frameDt / smoothTau)`, accumulates per-LED with rounding.
20. Min LED brightness with per-channel boost.
21. Zero-out if luminance below threshold.

### LED output

22. LED rotation via `RotateLedFrame()` based on `InputPosition` config.
23. Raw RGB sent via `UdpClient.SendAsync()` to WLED device IP:port.
24. On playback stop: sends 3 zero frames (blank LEDs) with 20ms delay.

### Multi-device

25. Multiple `AmbilightInProcessPlayer` instances per session (one per WLED device).
26. Device matched by DeviceId (stripped of timestamp) or DeviceName against configured mappings.

### Effects

27. Loading effect: rotating ochre segment (204, 119, 34) at ~33fps during extraction/loading.
28. Failure flash: 3 red flashes (255, 0, 0) with 150ms on/off.

## Implementation files

- `Services/AmbilightInProcessPlayer.cs` — 901 lines, main playback logic
- `Services/AmbilightPlaybackService.cs` — 414 lines, session/device integration
