# Release Notes - v1.5.8

## 🔁 Live Device Mapping Reload

- Device mappings created or edited in the Ambilight settings UI now take effect **immediately**, without requiring a Jellyfin restart.
- The playback service reads the latest plugin configuration on each playback event, so new mappings are picked up as soon as you save the configuration.

## 📦 Installation & Upgrade

- For installation and upgrade instructions, see the `INSTALLATION.md` file in the repository.
- After upgrading:
  1. Restart Jellyfin once to load the new plugin version.
  2. Configure or adjust your device mappings; subsequent changes should no longer require additional restarts to be honored during playback.

