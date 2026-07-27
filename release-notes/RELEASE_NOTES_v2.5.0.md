# Release Notes - v2.5.0

## Selectable Extraction Logic

The plugin now supports two per-zone color algorithms, selectable from the **Extraction logic** dropdown in settings:

- **Sobel edge-weighted** (default) — The existing algorithm: Sobel edge detection + Gaussian center weighting with relative-luminance rescaling. Biases each zone toward high-contrast pixels and lifts dark zones, keeping the strip lively but making dark scenes read brighter than the picture.

- **Linear-light averaging** — A plain unweighted mean of every pixel in the zone, taken in linear light via sRGB→linear lookup tables. A dark zone averages dark, and a black frame produces black LEDs. This more closely matches the behavior of HyperHDR and other ambilight software.

### Tone curve automatically follows extraction method

The player now reads the extraction method from the AMb3 file header and applies the correct tone curve:
- Linear-light files apply the user's gamma directly (`pow(x, gamma)`) and skip the mean-luminance pass.
- Edge-weighted, AMb2, and older files keep the existing scene-adaptive lift.

**No config change needed** — already-extracted files benefit without re-extraction.

### Migration notes

- Switching extraction method **requires re-extracting** existing items; previously extracted files are not converted.
- The `AmbilightGamma` default of **2.2 will appear dark** for linear-light files (since gamma is applied directly instead of as a lift). Lower it to ~1.3-1.5 for a more picture-faithful result.

## Per-Device Signal Delay

A new signed **Signal Delay (ms)** setting on each WLED device mapping lets you fine-tune sync on a per-controller basis:
- **Positive** values delay the ambilight data (LEDs react later).
- **Negative** values advance it (LEDs react earlier).
- The offset is applied on top of the global sync lead, so it works consistently across initial frame selection, seeks, and reported position.

## Extraction Manager

The extraction table now includes a **Logic** column showing which extraction method produced each binary. The status API also exposes `ExtractionLogic` in its responses.
