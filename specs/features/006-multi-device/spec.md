# Feature 007: Multi-Device Support

## Summary

Support multiple WLED devices per playback session, each with independent LED layouts, positions, and UDP streaming. Device matching via Jellyfin device ID or name.

## Problem

Users may have multiple LED setups (e.g., TV backlight + desk strip + ceiling lights), each driven by a separate WLED controller. Each device may have different LED counts per side and different rotational offsets. The plugin must match the correct devices to each session and stream independently.

## Acceptance criteria

### Device configuration

1. `DeviceMapping` class with: `DeviceIdentifier`, `Host`, `Port`, `TopLedCount`, `BottomLedCount`, `LeftLedCount`, `RightLedCount`, `InputPosition`.
2. Multiple device mappings stored in `PluginConfiguration.DeviceMappings` (List<DeviceMapping>).
3. Config UI shows card-based layout with device select dropdown, host/port inputs, LED grid, and InputPosition.
4. Duplicate detection: same device + host + port combination is rejected.

### Device matching at playback start

5. Session's `DeviceId` is decoded from base64, stripped of timestamp (Jellyfin web client uses `base64(UserAgent|timestamp)`).
6. Session's `DeviceName` is also checked against `DeviceIdentifier`.
7. All matching mappings are collected — multiple matches allowed (different host/port).
8. Deduplication by (host, port) — no duplicate UDP streams to same destination.

### Parallel playback

9. One `AmbilightInProcessPlayer` instance per matched device.
10. All players share the same binary file (read-only).
11. Each player runs as an independent `Task` with its own CTS.
12. Pause/seek events forwarded to all players simultaneously.
13. Stop stops all players.

### LED rotation (InputPosition)

14. `RotateLedFrame()` shifts LED indices circularly based on `InputPosition` config.
15. Allows physical LED strip alignment offset (e.g., strip starts at corner instead of edge start).

### Effects on all devices

16. Loading effect (rotating ochre) sent to all matched devices.
17. Failure flash (3 red flashes) sent to all matched devices if binary missing.
18. Blank-on-stop (3 zero frames) sent to all players on exit.

## Implementation files

- `Services/AmbilightPlaybackService.cs` — 414 lines (device resolution, multi-player management)
- `Services/AmbilightInProcessPlayer.cs` — 901 lines (LED rotation, UDP streaming)
- `PluginConfiguration.cs` — DeviceMapping class
- `Configuration/configPage.html` — Device mapping UI
