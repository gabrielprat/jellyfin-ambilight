# Release Notes - v1.5.7

## 🎯 Device Mapping Matching Fix

- Device mappings created from the settings UI now store the **human-readable device name** instead of Jellyfin's internal device ID.
- Playback matching uses the current session's `DeviceName`, so mappings remain stable even if Jellyfin changes internal device IDs.
- Existing mappings that were created with internal IDs will still load in the UI, but you may want to re-select the device in the dropdown and save to migrate them to the new, name-based identifiers.

## 📦 Installation & Upgrade

- For installation and upgrade instructions, see the `INSTALLATION.md` file in the repository.
- After upgrading:
  1. Restart Jellyfin.
  2. Open the Ambilight plugin settings, review your **Device Mappings**, and re-save them if needed so they use device names.

