# Tasks: Multi-Device Support

## Done

- [x] Define `DeviceMapping` class (8 properties)
- [x] Store device mappings in `PluginConfiguration.DeviceMappings`
- [x] Implement device matching in `ResolveWledTargets()` (DeviceId + DeviceName)
- [x] Implement `StripDeviceIdTimestamp()` — decode base64, strip timestamp, re-encode
- [x] Implement deduplication by (host, port)
- [x] Implement multi-player lifecycle (start/stop/pause/seek per device)
- [x] Implement `_sessionPlayers` concurrent dictionary
- [x] Implement LED rotation (`RotateLedFrame`) based on `InputPosition`
- [x] Implement loading effect on all matched devices
- [x] Implement failure flash on all matched devices
- [x] Implement blank-on-stop for all players
- [x] Implement device mapping UI (card-based, dynamic)
- [x] Implement duplicate detection in device mapping UI
- [x] Implement device select dropdown from Jellyfin Devices API
- [x] Per-device LED count override (different LED counts per device)

## TODO

(none)
