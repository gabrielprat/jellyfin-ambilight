# Jellyfin Ambilight

Ambilight-style lighting for your Jellyfin media center.

## Primary deliverable: Jellyfin plugin

The **publishable deliverable** is the **Jellyfin Ambilight plugin** in `jellyfin-plugin-ambilight/`. It is intended to be:

- **Publishable** — A single, installable plugin per platform (catalog/release-ready).
- **Simple to use** — Configure and use entirely from the Jellyfin UI; no extra services or API keys.
- **Self-contained** — Extractor and player binaries are embedded; ambilight data lives next to your video files.
- **Cross-platform** — Linux (x64, ARM64), Windows (x64), macOS (x64, ARM64).

See **[jellyfin-plugin-ambilight/GOALS.md](jellyfin-plugin-ambilight/GOALS.md)** for the full goals and **[jellyfin-plugin-ambilight/BUILDING.md](jellyfin-plugin-ambilight/BUILDING.md)** for building and releasing the plugin.

---

## Other components (reference / homelab)

**Proof-of-concept / homelab:** The repo also contains a standalone setup (Python daemons + Rust binaries in Docker) for reference or for users who prefer that architecture. It is intentionally lightweight and pragmatic.

Ambilight-style lighting is powered by:

- Two **Python daemons**:
  - A library **extractor daemon** that talks to Jellyfin and manages extraction jobs.
  - A **player daemon** that follows Jellyfin playback sessions and decides what ambilight stream should run where.
- Two **Rust binaries**:
  - A **Rust extractor** that does the heavy lifting of reading video files and computing per-frame edge colors.
  - A **Rust player** that reads precomputed ambilight binaries, applies all gamma/brightness/saturation/rotation tweaks, and pushes frames to WLED over UDP.

Everything runs as two lightweight Docker services (extractor + player), with both Python daemons orchestrating the Rust binaries and using simple file-based storage (no database).

If you’re looking for enterprise-grade abstractions and 100% test coverage, this might not be your favorite repo. If you enjoy hacking on real-world PoCs, please jump in, send PRs, and help turn this chaos into a slightly more civilized chaos.

---

## What This Project Does

- **Scans your Jellyfin libraries** and discovers `Movie`, `Episode` and `Video` items.
- **Extracts ambilight frames** from each video using the `ambilight-extractor` Rust binary and stores them as compact `.bin` files under `AMBILIGHT_DATA_DIR/binaries`.
- **Monitors active Jellyfin sessions** and tracks play, pause, seek and stop.
- **Streams precomputed ambilight data** over UDP to your WLED devices in sync with playback.
- Supports **per-device mapping** using `WLED_DEVICE_*` environment variables so different Jellyfin clients can target different WLED strips.

High level data flow:

1. **Extractor container** (`ambilight-extractor` service)
   - Python daemon (`ambilight-daemon-extractor.py`) periodically polls Jellyfin for library items.
   - Writes metadata JSON for each item to `AMBILIGHT_DATA_DIR/items`.
   - Invokes the Rust `ambilight-extractor` binary to generate `item_id.bin` ambilight binaries that contain raw per-frame edge colors.
2. **Player container** (`ambilight-player` service)
   - Python daemon (`ambilight-daemon-player.py`) polls Jellyfin `/Sessions` for active video playback.
   - Picks a WLED target based on Jellyfin’s device info and `WLED_DEVICE_*` mappings.
   - Starts/stops the Rust `ambilight-player` binary, which performs all color processing (gamma, saturation, brightness, rotation, resampling) and streams the resulting LED frames to the mapped WLED device over UDP.

---

## System Requirements

- **Docker + Docker Compose**
- **Jellyfin server** reachable from the containers, with an API key.
- **At least one WLED device** on the same network.
- Sufficient storage for ambilight binaries (a few hundred MB for a large library).

For Raspberry Pi / ARM:

- The extractor image is based on a minimal Alpine + FFmpeg stack.
- Optional hardware acceleration devices can be passed through (see `docker-compose.yml` comments).

---

## Quick Start

1. **Copy the example environment file**

   ```bash
   cp env.example .env
   ```

2. **Edit `.env` with your values**

   At minimum you must set:

   ```bash
   JELLYFIN_API_KEY=your_jellyfin_api_key
   JELLYFIN_BASE_URL=http://jellyfin:8096   # or your actual URL

   MOVIES_PATH=/path/to/your/movies
   TV_PATH=/path/to/your/tv-shows

   # Simple single-device setup
   WLED_HOST=your-wled-device.local
   WLED_UDP_RAW_PORT=19446
   ```

   For a multi-device / multi-client setup, you will also want `WLED_DEVICE_*` mappings (see **Configuration** below).

3. **Start the stack**

   ```bash
   docker-compose up -d
   ```

4. **Watch logs**

   ```bash
   # Follow both services
   docker-compose logs -f

   # Or per service
   docker-compose logs -f ambilight-extractor
   docker-compose logs -f ambilight-player
   ```

5. **Verify it works**

   - Add or rescan some media in Jellyfin.
   - Check `ambilight-extractor` logs for library scan and extraction progress.
   - Start playback in Jellyfin from a client that matches a configured `WLED_DEVICE_*` mapping.
   - Check `ambilight-player` logs for session detection and UDP streaming.

---

## How It Works (In More Detail)

### Extractor Daemon (`ambilight-daemon-extractor.py`)

- Periodically polls Jellyfin for:
  - Libraries (`/Users/{userId}/Views`)
  - Items in each library (`/Users/{userId}/Items`)
- Stores metadata for each item as JSON under `AMBILIGHT_DATA_DIR/items/{item_id}.json` using `storage/storage.py`.
- Filters out:
  - Non-video item types.
  - Missing video files.
  - Items already marked as failed.
  - Optionally, items that are already viewed (`EXTRACT_VIEWED=false`).
  - Optionally, items older than `EXTRACTION_MAX_AGE_DAYS`.
- Selects a batch of items that still need extraction and calls the Rust `ambilight-extractor` binary:
  - Input: original video file path.
  - Output: `AMBILIGHT_DATA_DIR/binaries/{item_id}.bin`.
  - The `.bin` contains timestamped LED colors around the frame edges.
- Runs continuously, respecting an optional **extraction time window** so heavy extraction can be restricted to off-hours.

### Player Daemon (`ambilight-daemon-player.py` + Rust `ambilight-player`)

- Periodically polls Jellyfin’s `/Sessions` endpoint.
- For each active playback session with a video:
  - Determines a **target WLED device** using:
    - `DEVICE_MATCH_FIELD` (e.g. `DeviceName`) pulled from the Jellyfin session.
    - Normalized substring matching against `WLED_DEVICE_*` environment variables.
  - Locates the matching `AMBILIGHT_DATA_DIR/binaries/{item_id}.bin`.
  - Spawns the Rust `ambilight-player` binary (wrapped by `simplified/ambilight_play.AmbilightBinaryPlayer`) pointed at that `.bin`, host and port.
- The Rust `ambilight-player`:
  - Reads the `.bin` ambilight file and derives timing from embedded timestamps.
  - Resamples from the extractor’s LED counts to your actual `AMBILIGHT_*_LED_COUNT` layout.
  - Applies gamma, saturation, brightness, per-channel boosts, minimum brightness, and LED order (`AMBILIGHT_ORDER`).
  - Rotates the logical LED ring based on `AMBILIGHT_INPUT_POSITION` so colors line up with your physical strip.
  - Handles pause/resume/seek/stop commands coming from the Python daemon over stdin.

All state is stored on disk under `AMBILIGHT_DATA_DIR`, so containers can be restarted without losing extraction progress.

### Storage & I/O

The design keeps disk I/O to a minimum and does most of the work in memory:

- **Layout**
  - **`AMBILIGHT_DATA_DIR/items/`** — One small JSON file per Jellyfin item (metadata only: id, filepath, extraction status, etc.).
  - **`AMBILIGHT_DATA_DIR/binaries/`** — One `.bin` file per video. Each file holds the full ambilight stream for that video (header + per-frame timestamps and LED colors). No thousands of tiny files; one contiguous binary per movie/episode.

- **Extractor (Rust)**
  - All frame decoding and color extraction runs in memory. The Rust extractor appends to a single in-memory buffer (`Vec<u8>`) for the whole run.
  - **Only disk write**: when done, it writes that buffer once to a temp file, then renames it to `{item_id}.bin`. So one atomic write per video, no incremental flushing.

- **Player (Rust)**
  - On start, it opens the `.bin` file, reads the header, then **loads all frames and timestamps into RAM** (`Vec<Vec<u8>>` + `Vec<u64>`).
  - After that, playback is entirely from memory: timing, gamma/saturation/brightness, resampling, rotation, and UDP sends use only in-memory data. No disk reads during playback.

- **Python daemons**
  - They read/write only small JSON files (item metadata) and decide which binaries to run; they do not stream binary content. So disk usage on the daemon side is minimal and metadata-only.

Net effect: heavy work (video decode, color math, LED output) stays in memory; disk is used for durable storage of metadata and one-off write/read of each ambilight binary per video.

---

## Docker Services

Defined in `docker-compose.yml`:

- **`ambilight-extractor`**
  - Builds from `Dockerfile.extractor`.
  - Mounts:
    - `${DATA_PATH:-./data}:/app/data`
    - `${MOVIES_PATH:-./test-media/movies}:/media/movies:ro`
    - `${TV_PATH:-./test-media/tv}:/media/tv:ro`
  - Uses `.env` for configuration.
  - Optionally passes through video acceleration devices for FFmpeg.

- **`ambilight-player`**
  - Builds from `Dockerfile.player`.
  - Mounts the same volumes so it can see the same data and media paths.
  - Uses `.env` for WLED and playback configuration.

---

## Configuration (Environment Variables)

Most variables are demonstrated in `env.example` and `env.homelab`. Below is a consolidated reference.

### Core Jellyfin / Network

- **`JELLYFIN_API_KEY`** (required)
  Jellyfin API key/token used for both extractor and player.

- **`JELLYFIN_BASE_URL`** (required)
  Base URL Jellyfin is reachable at from inside the containers, e.g. `http://jellyfin:8096` or `https://jellyfin.example.com`.

- **`DNS_TTL_SECONDS`** (default: `3600`)
  Time (seconds) to cache DNS lookups for Jellyfin and WLED.
  Set to `0` to disable caching and always resolve hostnames.

- **`TZ`** (optional, example: `Europe/Berlin`)
  Timezone for the containers (set in `.env` and used by Docker).

### Paths & Volumes

- **`DATA_PATH`** (example: `/mnt/5TB20241012/jellyfin-ambilight/`)
  Host directory mounted to `/app/data` inside the containers.
  All ambilight data lives under this path on the host.

- **`MOVIES_PATH`** (example: `/mnt/all_disks/Movies`)
  Host path for your movies library. Mounted read-only.

- **`TV_PATH`** (example: `/mnt/all_disks/Series`)
  Host path for TV/series libraries. Mounted read-only.

- **`AMBILIGHT_DATA_DIR`** (default inside container: `/app/data/ambilight`)
  Base directory for ambilight storage (items + binaries).
  Normally you leave this at the default and control the host side with `DATA_PATH`.

### Extractor: Library Scan & Extraction

Used mainly by `ambilight-daemon-extractor.py` and `storage/storage.py`:

- **`LIBRARY_SCAN_INTERVAL`** (default: `1800` seconds)
  How often to refresh Jellyfin library metadata and look for new videos.

- **`EXTRACTION_PRIORITY`** (default: `newest_first`)
  Order in which to extract videos. Supported values:
  - `newest_first`
  - `oldest_first`
  - `alphabetical`
  - `movies_newest_first`

- **`EXTRACTION_BATCH_SIZE`** (default: `5`)
  Maximum number of videos to extract per batch.

- **`EXTRACT_VIEWED`** (default: `false`)
  - `false`: skip items Jellyfin marks as already played.
  - `true`: also extract ambilight data for viewed items.

- **`EXTRACTION_MAX_AGE_DAYS`** (default: `0` = no age limit)
  Skip videos older than the given number of days based on Jellyfin’s `DateCreated`.
  Examples: `1` (only last 24h), `30` (last month), `365` (last year).

- **`EXTRACTION_START_TIME`**, **`EXTRACTION_END_TIME`** (default: unset → no restriction, example: `22:00` / `06:00`)
  Extraction time window in `HH:MM` 24h format.
  - Can cross midnight (e.g. `22:00`–`06:00`) to run heavy work overnight.
  - Library scanning still happens periodically; only extraction is gated.

### Player: Jellyfin Session Monitoring

Used by `ambilight-daemon-player.py`:

- **`PLAYBACK_MONITOR_INTERVAL`** (default: `0.1`–`1.0` seconds)
  Poll interval for Jellyfin `/Sessions`.
  Lower values → snappier reaction to state changes but more API calls.

- **`DEVICE_MATCH_FIELD`** (default: `DeviceName`)
  Which field from the Jellyfin session is used to match `WLED_DEVICE_*` mappings.
  Common values:
  - `DeviceName`
  - `Client`

### WLED & Device Mapping

- **`WLED_HOST`** (default: `wled-ambilight-lgc1.lan`)
  Default WLED hostname used mainly for logging and as a fallback.

- **`WLED_UDP_RAW_PORT`** (default: `19446`)
  UDP port for the WLED `UDP_RAW` protocol.

- **`WLED_DEVICE_*`** (optional, strongly recommended)
  Per-device mapping from Jellyfin clients to WLED targets. Examples:

  ```bash
  # In .env:
  WLED_DEVICE_LGSMARTTV=wled-ambilight-lgc1.lan:19446
  WLED_DEVICE_ANDROIDTV=wled-tv.lan:19446
  ```

  - The part after `WLED_DEVICE_` (e.g. `LGSMARTTV`) is normalized and matched
    as a substring against the normalized `DEVICE_MATCH_FIELD` value from the session.
  - The value can be either `hostname` or `hostname:port`.
  - If no mapping matches a session, ambilight is disabled for that session.

### Ambilight / LED Tuning

Most of these are read by the Rust extractor and the Python binary player (`simplified/ambilight_play.py`):

- **`AMBILIGHT_TOP_LED_COUNT`**, **`AMBILIGHT_BOTTOM_LED_COUNT`**,
  **`AMBILIGHT_LEFT_LED_COUNT`**, **`AMBILIGHT_RIGHT_LED_COUNT`**
  Number of LEDs on each side of the TV. Used to resample the binary data to your actual strip layout.

- **`AMBILIGHT_INPUT_POSITION`**
  Index (from the top-left corner, looking at the screen) of the first LED in your physical strip wiring.

- **`AMBILIGHT_RGBW`** (default: `false`)
  Set to `true` for RGBW strips. The extractor then outputs 4 bytes per LED (RGBW) instead of RGB.

- **`AMBILIGHT_SYNC_LEAD_SECONDS`**
  Small negative/positive offset to lead/lag the ambilight stream relative to Jellyfin playback.

- **`AMBILIGHT_SMOOTH_SECONDS`**
  Temporal smoothing window for color transitions.

- **`AMBILIGHT_GAMMA`**, **`AMBILIGHT_GAMMA_RED`**, **`AMBILIGHT_GAMMA_GREEN`**, **`AMBILIGHT_GAMMA_BLUE`**
  Gamma correction for overall and per-channel brightness.

- **`AMBILIGHT_RED_BOOST`**, **`AMBILIGHT_GREEN_BOOST`**, **`AMBILIGHT_BLUE_BOOST`**
  Per-channel gain to compensate for LED color balance.

- **`AMBILIGHT_BRIGHTNESS_TARGET`**
  Target brightness level for the output (relative scale).

- **`AMBILIGHT_MIN_LED_BRIGHTNESS`**
  Any LED below this brightness is treated as off/black.

- **`AMBILIGHT_SATURATION`**
  Global color saturation factor.

- **`AMBILIGHT_ORDER`** (default: `RGB`)
  Byte order expected by your LED controller (`RGB`, `GRB`, etc.).

- **`AMBILIGHT_DEBUG`**
  Debug level for ambilight playback logic (if supported by the player).

---

## Running & Managing the Stack

### Start

```bash
docker-compose up -d
```

### Stop

```bash
docker-compose down
```

### Restart after config changes

```bash
docker-compose down
docker-compose up -d
```

### View logs

```bash
docker-compose logs -f            # all services
docker-compose logs -f ambilight-extractor
docker-compose logs -f ambilight-player
```

---

## Caveats & known issues

- **Sync drift** — Ambilight can lose sync with the video at times (e.g. after long playback or network hiccups). It will resync automatically after a seek or pause/resume event.
- **Dark scenes** — In very dark scenes or dark regions, LEDs may appear slightly blueish. This is a known limitation of the current color extraction/tuning.

---

## Troubleshooting & Tips

- **No ambilight during playback**
  - Check that a `.bin` file exists under `DATA_PATH/ambilight/binaries` for the playing item.
  - Ensure the Jellyfin client’s device name matches at least one `WLED_DEVICE_*` identifier.
  - Confirm `JELLYFIN_API_KEY` and `JELLYFIN_BASE_URL` are correct.

- **Extractor never finishes**
  - Look at `ambilight-extractor` logs for errors.
  - Check disk space where `DATA_PATH` lives.
  - Consider tightening `EXTRACTION_MAX_AGE_DAYS` and lowering `EXTRACTION_BATCH_SIZE`.

- **High CPU usage**
  - Increase `LIBRARY_SCAN_INTERVAL`.
  - Increase `PLAYBACK_MONITOR_INTERVAL`.
  - Restrict extraction to off-hours using `EXTRACTION_START_TIME` / `EXTRACTION_END_TIME`.

---

## Development Notes

- Source is mounted as a volume, so you can edit files on the host and simply restart:

  ```bash
  docker-compose restart ambilight-extractor
  docker-compose restart ambilight-player
  ```

- For image build details and pre-built images (if provided), see `DOCKER_IMAGES.md` and `docker-compose.images.yml`.

This README is the canonical reference for environment variables and runtime behavior; if you add new tuning knobs, please document them here as well.

---

## License

This project is licensed under the [MIT License](LICENSE).
