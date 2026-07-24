# Mission

## What we build

**Jellyfin Ambilight** — a server-side plugin for Jellyfin that transforms any viewing session into an ambient lighting experience by driving WLED-compatible LED strips with edge-detected video colors.

## For whom

Jellyfin users who own WLED-compatible LED controllers (ESP32, ESP8266) and LED strips, and want synchronized ambient lighting without client-side software.

## Core value proposition

- **Zero client footprint:** everything runs server-side. No browser extensions, no apps, no companion software.
- **Automatic:** extract once, play forever. Extraction runs in the background on newly added media.
- **Precise sync:** per-frame timestamps derived from the video's actual framerate ensure lights match the picture at any moment — playback, seeking, or pausing.
- **Multi-device:** multiple WLED devices per viewing session, each with independent LED layouts and positions.
- **Backward compatible:** existing AMb2 binary files continue to work unchanged. AMb3 is opt-in and transparent.

## Design principles

1. **Sync is non-negotiable.** Every architectural decision must preserve frame-accurate light-video synchronization. Timestamps are derived from the probed video FPS, never hardcoded.
2. **Ship nothing unnecessary.** No external dependencies beyond Jellyfin SDK and .NET 8 BCL. Compression uses `System.IO.Compression.DeflateStream`, not third-party libraries.
3. **Fail gracefully.** If extraction fails, the user sees a failure flash on the LEDs. If a binary file is corrupt, the player logs a warning and stops cleanly. Stuck extractions are cleaned up on startup.
4. **Config hot-reload.** Services read `Plugin.Instance?.Configuration` directly at runtime. No restart required for config changes.
5. **File-based storage.** Simple JSON metadata + binary data files. No database migrations, no SQLite, no EF Core.
