// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

namespace Jellyfin.Plugin.Ambilight.Services.Extraction;

/// <summary>
/// Resolves the configured <see cref="PluginConfiguration.AmbilightExtractionMethod"/> value to a
/// concrete <see cref="IExtractionLogic"/>. Unknown or missing values fall back to the default
/// edge-weighted logic.
/// </summary>
public static class ExtractionLogicFactory
{
    /// <summary>Config value for the historical Sobel edge-weighted extraction (default).</summary>
    public const string EdgeWeighted = "edge_weighted";

    /// <summary>Config value for the linear-light averaging extraction.</summary>
    public const string LinearLightAverage = "linear_light_average";

    public static IExtractionLogic Create(string? method) => method switch
    {
        LinearLightAverage => new LinearLightAverageExtractionLogic(),
        _ => new EdgeWeightedExtractionLogic(),
    };
}
