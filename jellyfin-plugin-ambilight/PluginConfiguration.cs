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
        public bool ExtractViewed { get; set; } = false;
        public bool ExtractNewlyAddedItems { get; set; } = true;
        public double ExtractionMaxAgeDays { get; set; } = 0;
        public string ExtractionStartTime { get; set; } = "00:00";
        public string ExtractionEndTime { get; set; } = "23:59";
        
        // WLED
        public string DefaultWledHost { get; set; } = "wled-ambilight.local";
        public int DefaultWledUdpPort { get; set; } = 19446;
        public string DeviceMatchField { get; set; } = "DeviceName";
        public List<DeviceMapping> DeviceMappings { get; set; } = new();
        
        // Ambilight LED settings
        public bool AmbilightRgbw { get; set; } = false;
        public double AmbilightSyncLeadSeconds { get; set; } = 0.2;
        /// <summary>
        /// Smoothing window in seconds for temporal blending between frames.
        /// Set to 0 to disable smoothing entirely.
        /// Higher values = smoother but more lag; lower values = more responsive but can flicker.
        /// </summary>
        public double AmbilightSmoothSeconds { get; set; } = 0.12;
        public double AmbilightGamma { get; set; } = 2.2;
        public double AmbilightSaturation { get; set; } = 1.0;
        public double AmbilightBrightnessTarget { get; set; } = 60.0;
        public string AmbilightOrder { get; set; } = "RGB";
        
        public double AmbilightGammaRed { get; set; } = 1.0;
        public double AmbilightGammaGreen { get; set; } = 1.0;
        public double AmbilightGammaBlue { get; set; } = 1.0;
        
        public double AmbilightRedBoost { get; set; } = 0.0;
        public double AmbilightBlueBoost { get; set; } = 0.0;
        public double AmbilightGreenBoost { get; set; } = 0.0;
        
        public double AmbilightMinLedBrightness { get; set; } = 0.0;
        
        public int AmbilightTopLedCount { get; set; } = 89;
        public int AmbilightBottomLedCount { get; set; } = 89;
        public int AmbilightLeftLedCount { get; set; } = 49;
        public int AmbilightRightLedCount { get; set; } = 49;
        public int AmbilightInputPosition { get; set; } = 0;

        /// <summary>
        /// Libraries (by Id) that should be excluded from extraction.
        /// </summary>
        public List<string> ExcludedLibraryIds { get; set; } = new();

        /// <summary>
        /// Devices (by DeviceId) that are allowed to drive Ambilight playback.
        /// If empty, all devices are allowed.
        /// </summary>
        public List<string> AllowedDeviceIds { get; set; } = new();

        /// <summary>
        /// Folder where ambilight binary files are stored. Filenames are {ItemId}.bin.
        /// </summary>
        public string AmbilightDataFolder { get; set; } = "/data/ambilight";

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
    }
}
