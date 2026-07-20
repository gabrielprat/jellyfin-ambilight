# Jellyfin Ambilight Plugin

**Version:** 2.2.0

Transform your Jellyfin viewing experience with synchronized ambient lighting! This plugin automatically creates immersive ambilight effects for your movies and TV shows by controlling WLED-compatible LED strips.

## What is Ambilight?

Ambilight creates ambient lighting that matches the colors on your screen edges, extending the picture beyond your TV or monitor. This plugin analyzes your video content and sends real-time color data to your WLED LED strips, creating a stunning visual experience.

## Features

- **Automatic extraction** - The plugin scans your Jellyfin library and prepares ambilight data for your videos
- **Seamless playback** - Lights automatically sync when you start watching
- **Multi-device support** - Control different LED setups for different playback devices
- **Customizable** - Adjust colors, brightness, and LED layout to match your setup
- **Background processing** - Extraction happens automatically without interrupting your viewing
- **AMb3 compressed format** - New extraction format with Deflate compression, delta encoding, and RLE dedup for significantly smaller files
- **Backward compatible** - Plays both legacy AMb2 and new AMb3 files transparently

## Requirements

- Jellyfin 10.10.x or compatible version
- WLED-compatible LED controller
- LED strips installed around your TV/monitor
- Docker volume (if running Jellyfin in Docker)

## WLED Network Requirements

The plugin streams raw RGB frames over UDP to WLED's **Hyperion raw-RGB handler on port 19446**. This port is hardcoded in WLED and cannot be changed — the plugin always targets it automatically.

### UDP Packet Size Limit

WLED's UDP handler has a **1472-byte hard limit** per packet (standard UDP MTU). Each LED requires 3 bytes (RGB), so a single packet can carry at most **490 LEDs** (490 × 3 = 1470 bytes).

**For setups with more than 490 total LEDs**, split your strip across **multiple WLED instances**, each handling ≤490 LEDs. For example, an 832-LED strip could be driven by two WLED controllers (e.g., 416 LEDs each), with both mapped to the same Jellyfin device.

### Why Port 19446?

WLED exposes two UDP listeners:

| Port | Handler | Protocol | Notes |
|------|---------|----------|-------|
| **19446** | Hyperion raw RGB | Raw bytes, no header | **Optimized for streaming**, zero protocol overhead. Used by this plugin. |
| 21324 | Notifier / UDP Realtime | Protocol-wrapped (DRGB/DNRGB) | Shares socket with WLED sync, calls `strip.show()` per packet, adds ~100ms latency for large strips. Not suitable for ambilight. |

Port 19446 is the only correct target for real-time ambilight streaming.

## Installation

### Docker Storage Volume (Do This First For Docker Installs)

If Jellyfin runs in Docker, set up a persistent volume for ambilight binary data before installing the plugin.

Add this line to your `docker-compose.yml` under `volumes`:

```yaml
volumes:
  - /path/on/your/host/ambilight-data:/config/data/ambilight
```

Or with `docker run`:

```bash
-v /path/on/your/host/ambilight-data:/config/data/ambilight
```

**Example:**
```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin
    volumes:
      - /mnt/media:/media
      - /mnt/jellyfin/config:/config
      - /mnt/jellyfin/ambilight:/config/data/ambilight  # Add this line
```

This folder stores extracted ambilight binary files (`.bin`) and should persist across container restarts.

### Plugin Repository (Recommended)

1. Go to **Jellyfin Dashboard** -> **Administration** -> **Plugins** -> **Repositories**
2. Click **Add Repository**
3. Enter:
   - **Name:** `Ambilight`
   - **URL:** `https://raw.githubusercontent.com/gabrielprat/jellyfin-ambilight/refs/heads/master/manifest.json`
4. Save, then open **Catalog**
5. Search for **Ambilight** and click **Install**
6. Restart Jellyfin

### Manual Install (Fallback)

1. Download the latest `jellyfin-plugin-ambilight_x.x.x.zip` from [Releases](https://github.com/gabrielprat/jellyfin-ambilight/releases)
2. Extract the zip
3. Copy the `Jellyfin.Plugin.Ambilight` folder to your Jellyfin plugins directory:
   - Linux: `/var/lib/jellyfin/plugins/`
   - Docker: `/config/plugins/`
   - Windows: `C:\ProgramData\Jellyfin\Server\plugins\`
4. Restart Jellyfin

## Configuration

### Accessing Plugin Settings

1. Go to **Jellyfin Dashboard** → **Plugins**
2. Find **Ambilight** in the list
3. Click **Settings** to configure the plugin
4. Click **Manager** to view extraction status and manually extract videos

![Plugin Settings](docs/plugin-settings.png)

> **Note:** The screenshot above shows the Settings page. The Manager page provides a list of all videos with their extraction status and manual extraction controls.

### Configuration Options

The plugin settings page is organized into the following sections:

#### Extraction

Controls how and when the plugin processes videos:

- **Extract newly added items** - Automatically extract ambilight data when new videos are added to your libraries
- **Extraction priority** - Order in which videos are processed (newest first, oldest first, alphabetical, or movies newest first)
- **Excluded libraries** - Select which Jellyfin libraries to skip during extraction
- **Hardware acceleration** - Choose hardware-accelerated video decoding for faster extraction. 'Auto' (recommended) uses CPU decoding - most compatible. Select specific hardware (VAAPI, Intel Quick Sync, NVIDIA CUDA, VideoToolbox) only if your system supports it

**Extraction LED Configuration:**

- **Top/Bottom/Left/Right LED counts** - Default LED strip layout used when creating binary files (default: 89/89/49/49)
- **Ambilight data folder** - Where to store extracted `.bin` files (default: `/data/ambilight`)

The extracted data can be automatically scaled to match different LED layouts during playback (configured per device mapping below).

#### WLED Device Mappings

Configure which Jellyfin devices should trigger ambilight effects and where to send them. **Only devices with at least one mapping will have ambilight enabled.**

**How to configure:**
1. Click **"Add Device Mapping"** to create a new mapping
2. **Select device** - Choose from your registered Jellyfin devices (e.g., "Living Room TV")
3. **Enter WLED host** - IP address of your WLED controller (e.g., `192.168.1.100`)
4. **Configure LED layout** for this specific WLED instance:
   - **Top/Bottom/Left/Right LED counts** - Number of LEDs on each edge of your screen
   - **Input Position** - Starting index of your LED strip in clockwise order from the viewer perspective:
     - `0` = top-left LED
     - `1` = next LED to the right
     - continue clockwise around the screen
   - **Gap Length** - Number of inactive LEDs at the gap position (include in the corresponding edge's LED count). Set to0 for no gap.
   - **Gap Position** - LED index where the gap starts, counting from 0 at top-left, clockwise (same coordinate system as Input Position). For example, if Top=50 and Right=25, the start of the bottom edge is index75.
5. **Save** - Click the Save button at the bottom
6. **Repeat** - Add more mappings as needed

**Important:** The plugin automatically handles device ID variations (e.g., session timestamps) so your mappings will work across multiple playback sessions from the same device.

**Key features:**
- **Per-device control** - Each playback device routes to its specific WLED instance(s)
- **Per-mapping LED configuration** - Each WLED instance can have its own LED layout for different screen sizes
- **Multi-zone support** - Map the same device to multiple WLED instances for synchronized effects
- **Auto-validation** - Duplicate mappings are automatically detected and prevented
- **Note:** Color order (RGB/GRB/etc.) is configured in WLED's web interface, not in this plugin

#### Lightning Tuning

Fine-tune the appearance and behavior of your ambilight effects:

- **Smoothing window** - Time window for temporal smoothing between frames in seconds (default: 0.06). Set to 0 to disable. Higher values = smoother but more delayed; lower values = more responsive but can flicker on rapid cuts
- **Base gamma** - Overall gamma curve (default: 2.2). Higher values make mid-tones and highlights darker
- **Saturation** - Color saturation multiplier (default: 1.0). Higher = more vivid colors
- **Red/Green/Blue gamma** - Per-channel gamma correction to balance colors

#### Debug

- **Enable debug logging** - Logs play/pause/seek, binary found/loaded, WLED connection and broadcast. Enable when troubleshooting why lights don't react

## Using the Plugin

### Extraction Manager

The plugin includes a built-in extraction manager that handles video processing:

#### Automatic Mode (Recommended)

1. Once configured, the plugin automatically scans your library
2. New videos are queued for extraction
3. Processing happens in the background
4. You'll see ambilight data files (`.bin`) created in your data directory

#### What Gets Extracted?

The plugin looks for:
- Movies
- TV show episodes
- Items without existing ambilight data

#### Monitoring Extraction

- Check the Jellyfin logs to see extraction progress
- Each video gets a `.bin` file with the same name in your ambilight data folder
- Extraction time depends on video length and your CPU priority setting

### Watching with Ambilight

1. Start playing any video that's been extracted
2. The plugin automatically detects playback and activates your LEDs
3. Colors sync in real-time with the video
4. Lights turn off when you stop or pause

### Manual Extraction

#### Extraction Manager Page
1. Go to **Jellyfin Dashboard** → **Plugins** → **Ambilight**
2. Click on the **Manager** tab
3. View all videos and their extraction status with real-time progress bars
4. Click "Extract" on specific items or "Extract All Pending"

**Note:** The "Extract All Pending" feature processes videos sequentially (one at a time) to avoid overloading your system and ensure efficient resource usage.

## Troubleshooting

### LEDs Don't Turn On

1. Check your WLED device is online and accessible
2. Verify the IP address and port in plugin settings
3. Make sure the video has been extracted (check for `.bin` file)
4. Enable Debug mode and check Jellyfin logs

### Extraction Not Working

1. Verify ffmpeg is installed (required for video processing)
2. Check CPU priority isn't set too low
3. Ensure the data directory has write permissions
4. Look for error messages in Jellyfin logs

### Wrong Colors or Layout

1. Verify your LED counts match your physical setup
2. Check the LED input position setting
3. Configure color order in WLED's web interface if colors are swapped
4. Try adjusting gamma and saturation

### Docker Volume Issues

1. Make sure the volume path exists on your host
2. Check folder permissions (Jellyfin user needs write access)
3. Verify the path matches your plugin settings

## Advanced Configuration

### Multiple WLED Devices & Multi-Zone Setups

The plugin supports unlimited device-to-WLED mappings:

**Setting up multiple rooms:**
1. Add a mapping for each device/room combination
2. Each device routes to its own WLED instance

**Setting up multi-zone ambilight:**
1. Add multiple mappings with the **same device** but **different WLED hosts**
2. The plugin will broadcast to all matching WLED instances simultaneously
3. Perfect for wraparound lighting, ceiling effects, or multi-strip setups

**Example: Theater room with 3 WLED controllers:**
- Map "Theater Room" → `192.168.1.102` (screen LEDs)
- Map "Theater Room" → `192.168.1.103` (wall LEDs)
- Map "Theater Room" → `192.168.1.104` (ceiling LEDs)

When playing on "Theater Room", all 3 WLED instances receive synchronized color data!

### Storage Management

Ambilight `.bin` files are compressed but can add up:

- Average file size: 10-50 MB per hour of video
- A 2-hour movie ≈ 20-100 MB

### Binary Format (AMb3)

Starting with v2.0.0, new extractions use the **AMb3** binary format. The plugin automatically detects and plays both AMb2 (legacy) and AMb3 files — no migration required.

**AMb3 advantages over AMb2:**
- **Deflate compression** — 30-50% smaller files on top of encoding gains
- **Delta encoding** — only changed LEDs are stored between keyframes (every ~2 seconds)
- **RLE deduplication** — static scenes (credits, pauses) stored once with a repeat count
- **Chunk-based structure** — frames grouped into independently compressed chapters
- **Seeking index** — instant seeking in long files via timestamp→offset index at EOF

**Typical file sizes:**
| Content type | AMb2 | AMb3 |
|---|---|---|
| Typical movie (2h) | ~850 MB | 200-350 MB |
| Dialogue/slow | ~850 MB | 150-250 MB |
| Anime (limited animation) | ~850 MB | 100-200 MB |

**AMb3 header (96 bytes):** magic `AMb3`, version, flags (compression, delta, VFR, HDR), duration, total frames, base FPS, LED counts, compression algorithm, quality level, index offset, chunk count.

**Chunk header (32 bytes):** timestamp, chunk type (keyframe/delta/RLE), compressed/uncompressed sizes, frame count, average brightness, flags.

## Support & Development

### Getting Help

For issues, questions, or feature requests:

- **Check Jellyfin logs** for error messages (Dashboard → Logs)
- **Review this README** and the configuration screenshot
- **Check existing issues** on the GitHub repository

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

### What does this mean?

The GPLv3 license grants you the freedom to:
- Use this software for any purpose
- Study and modify the source code
- Share copies of the software
- Share your modifications

Under the condition that any distributed modifications or derivative works are also licensed under the GPLv3.

For more information about the GPL license, visit: https://www.gnu.org/licenses/gpl-3.0.html

---

**Enjoy your immersive viewing experience! 🎬✨**
