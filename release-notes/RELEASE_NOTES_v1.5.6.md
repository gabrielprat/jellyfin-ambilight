# Release Notes - v1.5.6

## ⏸ Fixed Pause/Resume Ambilight Sync

- Ambilight now correctly pauses its effect when the Jellyfin session is paused and resumes in sync when playback continues.
- Playback pause state is now wired through the playback progress events into the in-process player, so LEDs hold the last video frame instead of continuing to advance.

## 🧵 Scheduled Task Retries Failed Extractions

- The **Extract Pending Ambilight Data** scheduled task now also includes items whose extraction previously failed, as long as no valid binary exists.
- This allows you to re-run the task to automatically retry failed extractions without manual cleanup.

## 🪵 Improved Debug Logging for Device Mappings

- When **Debug** is enabled and a play session starts, logs now include:
  - The current device ID in both raw and **normalized (timestamp-stripped)** form.
  - A summary of all configured device mappings, including their normalized identifiers and WLED targets.
- This makes it easier to diagnose cases where a device-to-WLED mapping is not being matched as expected.

