// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System.Collections.Generic;
using MediaBrowser.Model.Plugins;

namespace Jellyfin.Plugin.Ambilight
{
    public class PluginConfiguration : BasePluginConfiguration
    {
        public string JellyfinBaseUrl { get; set; } = string.Empty;
        public string JellyfinApiKey { get; set; } = string.Empty;
        
        // Extraction
        public string ExtractionPriority { get; set; } = "newest_first";
        public bool ExtractNewlyAddedItems { get; set; } = true;
        public int MaxConcurrentExtractions { get; set; } = 1;
        public string HardwareAcceleration { get; set; } = "auto"; // "auto", "none", "vaapi", "qsv", "cuda", "videotoolbox"
        
        // WLED Device Mappings
        public string DeviceMatchField { get; set; } = "DeviceName";
        public List<DeviceMapping> DeviceMappings { get; set; } = new();
        
        // Ambilight Extraction Settings (for creating binary files)
        public int AmbilightTopLedCount { get; set; } = 89;
        public int AmbilightBottomLedCount { get; set; } = 89;
        public int AmbilightLeftLedCount { get; set; } = 49;
        public int AmbilightRightLedCount { get; set; } = 49;
        // Ambilight Visual Settings (global preferences)
        public double AmbilightSyncLeadSeconds { get; set; } = 0.2;
        /// <summary>
        /// Smoothing window in seconds for temporal blending between frames.
        /// Set to 0 to disable smoothing entirely.
        /// Higher values = smoother but more lag; lower values = more responsive but can flicker.
        /// </summary>
        public double AmbilightSmoothSeconds { get; set; } = 0.06;
        public double AmbilightGamma { get; set; } = 2.2;
        public double AmbilightSaturation { get; set; } = 1.0;
        
        public double AmbilightGammaRed { get; set; } = 1.0;
        public double AmbilightGammaGreen { get; set; } = 1.0;
        public double AmbilightGammaBlue { get; set; } = 1.0;

        /// <summary>
        /// Libraries (by Id) that should be excluded from extraction.
        /// </summary>
        public List<string> ExcludedLibraryIds { get; set; } = new();

        /// <summary>
        /// Folder where ambilight binary files are stored. Filenames are {ItemId}.bin.
        /// </summary>
        public string AmbilightDataFolder { get; set; } = "/data/ambilight";

        // AMb3 extraction settings
        /// <summary>
        /// Number of frames per AMb3 chapter (~2s at 24fps with default 48).
        /// </summary>
        public int Amb3ChapterSizeFrames { get; set; } = 48;

        /// <summary>
        /// Per-LED RGB difference threshold to consider an LED "changed" for delta encoding.
        /// </summary>
        public int Amb3DeltaThreshold { get; set; } = 10;

        /// <summary>
        /// When true, delta chunks fall back to keyframe if average LED change exceeds 50%.
        /// </summary>
        public bool Amb3DeltaFallbackToKeyframe { get; set; } = true;

        /// <summary>
        /// Percentage of LEDs that must change between consecutive frames to trigger a scene change (forces keyframe).
        /// Default 40 means 40% of LEDs must change significantly. Set to 0 to disable scene change detection.
        /// </summary>
        public int Amb3SceneChangeThreshold { get; set; } = 40;

        /// <summary>
        /// When true, enables verbose logging for play/pause/seek, binary load, WLED connection and broadcast.
        /// </summary>
        public bool Debug { get; set; } = false;

        public string? RustExtractorPath { get; set; }
    }
    
    public class DeviceMapping
    {
        public string DeviceIdentifier { get; set; } = string.Empty;
        public string Host { get; set; } = string.Empty;
        public int Port { get; set; } = 19446;
        
        // LED Layout Configuration (per WLED instance)
        public int TopLedCount { get; set; } = 89;
        public int BottomLedCount { get; set; } = 89;
        public int LeftLedCount { get; set; } = 49;
        public int RightLedCount { get; set; } = 49;
        public int InputPosition { get; set; } = 0;
    }
}
