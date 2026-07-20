# Release Notes - v2.1.0

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
