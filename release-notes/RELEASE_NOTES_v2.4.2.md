# Release Notes - v2.4.2

## Fix LEDs Flickering Once Per Second

Since version 2.3.0, LEDs flickered visibly once per second during steady playback. The root cause was a seek-detection bug dating back to 1.0.0: each Jellyfin playback progress report was compared against the *previous* report, and the ~1s interval between reports always exceeded the 0.5s seek threshold. Every report was therefore treated as a seek. This was harmless until 2.3.0 added an EMA (smoothing accumulator) reset on seek, which made each false seek produce a visible color jump.

Seek detection now compares the client's reported position against the player's own tracked position, which is independent of the reporting interval. The threshold has been raised to 1.5s to tolerate decode drift and clients that round position to whole seconds.

## Sync Lead Preserved Across Seeks

`AmbilightSyncLeadSeconds` was only applied when playback started. Any seek would drop the lead offset, leaving the ambilight running behind the picture. It is now reapplied on every seek.

## Scene Change Snapping LED Count Fix

The scene-change detection compared the number of changed LEDs against the device-mapping LED count, but the count itself was measured over the source frame. When a `.bin` file's LED counts differed from the mapping's, the snap rate was skewed. The percentage is now correctly taken against the source LED count.

## Cleanup

- Removed the write-only `_lastPositionSeconds` dictionary from the playback service, which leaked one entry per session.
