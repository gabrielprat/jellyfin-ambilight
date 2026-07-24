# Plan: Playback Pipeline

## Architecture

### Process model

Playback runs as an async task per WLED device, managed by `AmbilightPlaybackService`. Each player is a `Task` with its own `CancellationTokenSource`. Multiple players run concurrently (one per device) for a single playback session.

### AMb3 reconstruction strategy

```
1. Read 4-byte magic → dispatch
2. Read 96-byte header → fps, LED counts, flags
3. Seek to index_offset → read IDX3 seeking index into memory
4. Seek back to header offset (byte 100)
5. For each chunk:
   a. Read 32-byte chunk header
   b. Read compressed_size bytes
   c. DeflateStream.Decompress → uncompressed payload
   d. Parse payload based on chunk_type:
      - Keyframe: expand RLE entries → frames list
      - Delta: decode against lastKeyframe → frames list
   e. Record (timestampUs, fileOffset, chunkIndex) in index
6. All frames now in memory with timestamps
```

### Visual processing pipeline (per frame)

```
frame RGB data
    ↓
ComputeAverageLuminance()
    ↓
AdaptiveGamma(luminance)
    ↓
PerChannelGamma(R, G, B) — clamped 0.1-5.0
    ↓
SaturationAdjust()
    ↓
InverseGamma()
    ↓
BrightnessTargetFactor()
    ↓
EMA Smoothing (accumulative, per-LED)
    ↓
Round + MinBrightness + PerChannelBoost
    ↓
ZeroOut(below threshold)
    ↓
RotateLedFrame(InputPosition)
    ↓
UdpClient.SendAsync(raw RGB)
```

### EMA smoothing formula

```csharp
double frameDt = (timestampsUs[next] - timestampsUs[current]) / 1_000_000.0;
double smoothTau = config.AmbilightSmoothSeconds; // default 0.12s
double k = 1.0 - Math.Exp(-frameDt / smoothTau);
// For each LED:
 smoothed = smoothed + k * (target - smoothed);
```

This provides frame-rate-independent smoothing. At 24fps (41.7ms frame time): k ≈ 0.29. At 60fps (16.7ms): k ≈ 0.13.

### Seeking implementation

1. `OnPlaybackProgress` detects position jump >0.5s
2. Calls `player.Seek(seconds)` which sets `_pendingSeekSeconds` under lock
3. Main loop checks `_pendingSeekSeconds`, converts to target microsecond
4. Binary search through `timestampsUs` for nearest frame ≥ target
5. Sets `frameIndex` to found position
6. Resumes normal playback loop

### Device matching

```csharp
// Strip timestamp from Jellyfin device ID
// Jellyfin web client: base64(UserAgent|timestamp)
// Plugin strips timestamp for stable matching
stripped = base64(userAgent) // without timestamp part
// Match against configured DeviceIdentifier
```

## Thread safety

- `_stateLock` protects `_isPaused`, `_pendingSeekSeconds`
- `_cts` for cooperative cancellation
- `UdpClient` is thread-safe for `SendAsync` calls
- Multiple players for same session run independently

## Error handling

- ffmpeg path resolution failure: log warning, use fallback string
- UDP send failure: log, continue (don't crash the player loop)
- Decompression failure: log warning, skip chunk
- EOF during chunk read: stop playback cleanly
