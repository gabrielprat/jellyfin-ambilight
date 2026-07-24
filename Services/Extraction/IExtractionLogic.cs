// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

namespace Jellyfin.Plugin.Ambilight.Services.Extraction;

/// <summary>
/// Turns a single decoded RGB24 frame into one color per LED zone.
/// Implementations own the full per-frame color algorithm so the extractor plumbing
/// (ffmpeg decoding, chaptering, AMb3 serialization) stays agnostic about how zone
/// colors are derived. Which implementation is used is chosen by
/// <see cref="PluginConfiguration.AmbilightExtractionMethod"/>.
/// </summary>
public interface IExtractionLogic
{
    /// <summary>
    /// Compute one RGB color per zone and write them into <paramref name="output"/> as
    /// consecutive RGB byte triplets (3 bytes per zone, in zone order).
    /// </summary>
    /// <param name="frame">Packed RGB24 pixels for the whole frame (width * height * 3 bytes).</param>
    /// <param name="width">Frame width in pixels.</param>
    /// <param name="height">Frame height in pixels.</param>
    /// <param name="zones">Per-LED pixel rectangles as (x1, y1, x2, y2), half-open on x2/y2.</param>
    /// <param name="output">Destination buffer, at least zones.Length * 3 bytes long.</param>
    void ComputeFrameColors(
        byte[] frame,
        int width,
        int height,
        (int x1, int y1, int x2, int y2)[] zones,
        byte[] output);
}
