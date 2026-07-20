# Release Notes - v2.2.0

## LED Strip Gap Configuration

Per-device **Gap Length** and **Gap Position** settings for LED strips with a physical gap at any position (matching HyperHDR's gap feature):

- **Gap Length** — Number of inactive LEDs in the gap
- **Gap Position** — LED index where the gap starts (clockwise from top-left, same coordinate system as Input Position)
- Include the gap count in the corresponding edge's **LED count** (e.g. if the gap is on the bottom edge, add it to Bottom LEDs)
- Gap positions receive black frames after Input Position rotation, keeping them off
- Works correctly with any Input Position, including when the gap wraps around the end of the strip

### Example

TV with 50 top LEDs, 25 right LEDs, 25 left LEDs, and a bottom edge with 40 active LEDs plus a 10-LED gap behind the stand:

| Setting | Value |
|---|---|
| Top LEDs | 50 |
| Right LEDs | 25 |
| Left LEDs | 25 |
| Bottom LEDs | 50 (40 active + 10 gap) |
| Gap Length | 10 |
| Gap Position | 95 (50 top + 25 right + 20 into bottom) |
| Input Position | 95 (data cable enters at the gap) |

## Removed Per-Device Port Configuration

The **Port** field in device mappings has been removed. The plugin now always targets WLED's Hyperion raw-RGB handler on UDP port 19446, which is hardcoded in WLED and cannot be changed.

This eliminates misconfiguration where users set the wrong port (e.g. 21324) resulting in no ambilight effects. Existing saved configurations with a `Port` field continue to work — the field is silently ignored.

## WLED Network Requirements Documentation

The README now documents:

- **UDP port 19446** — WLED's Hyperion raw-RGB handler, used by the plugin
- **490-LED per-packet limit** — WLED's 1472-byte UDP MTU caps each packet at 490 LEDs (490 × 3 bytes RGB). For larger strips, use multiple WLED instances.
- **Why port 19446 over 21324** — Port 21324 (notifier/UDP realtime) shares socket with WLED sync, calls `strip.show()` per packet, and adds ~100ms latency. Not suitable for ambilight.
