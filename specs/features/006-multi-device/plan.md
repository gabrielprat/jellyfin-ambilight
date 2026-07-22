# Plan: Multi-Device Support

## Architecture

### Session-to-device mapping

```
Jellyfin Session
├── DeviceId: "base64(UserAgent|timestamp)"
├── DeviceName: "Chrome on MacBook"
│
▼
AmbilightPlaybackService.ResolveWledTargets()
├── StripDeviceIdTimestamp(deviceId)
│   ├── decode base64
│   ├── split on '|'
│   ├── take first part (UserAgent only)
│   └── re-encode base64
├── Match against DeviceMappings:
│   ├── DeviceIdentifier == stripped_deviceId
│   ├── DeviceIdentifier == deviceName
│   └── (or other matching rules)
├── Deduplicate by (host, port)
└── Return List<DeviceMapping>
```

### Multi-player lifecycle

```
OnPlaybackStart(session)
├── ResolveWledTargets(session) → List<DeviceMapping>
├── For each mapping:
│   ├── SendLoadingEffect(host, port)
│   └── Start new AmbilightInProcessPlayer(binPath, mapping, startSeconds)
└── Store in _sessionPlayers[sessionId]

OnPlaybackProgress(session)
├── Get _sessionPlayers[sessionId]
├── Detect pause → SetPaused() on all players
└── Detect seek → Seek() on all players

OnPlaybackStopped(session)
├── Stop all players for session
└── Remove from _sessionPlayers
```

### Device ID stripping

```csharp
// Jellyfin web client device ID format:
// base64("Mozilla/5.0...|1705312345678")
//
// Plugin strips timestamp for stable matching:
string StripDeviceIdTimestamp(string deviceId)
{
    string decoded = DecodeBase64(deviceId);
    string[] parts = decoded.Split('|');
    string userAgent = parts[0]; // without timestamp
    return EncodeBase64(userAgent);
}
```

### UDP streaming per device

Each player creates its own `UdpClient` and connects to its device's IP:port. No shared UDP socket — each device gets independent streaming.

## Concurrency model

- `_sessionPlayers` is a `ConcurrentDictionary<string, List<AmbilightInProcessPlayer>>`
- Player tasks run independently — no shared state between players
- Pause/seek broadcast is best-effort (fire-and-forget to all players)
- Stop waits up to 2s for each player task to complete

## Edge cases

- **No matching devices:** playback proceeds without ambilight (no crash, no error to user)
- **Device offline:** UDP send fails silently, player continues
- **Multiple sessions same device:** each session gets its own player, last-write-wins on UDP
- **Device removed mid-session:** player continues, UDP fails silently
