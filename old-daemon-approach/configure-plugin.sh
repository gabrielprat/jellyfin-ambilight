#!/bin/bash
# Configure Ambilight plugin via Jellyfin API

JELLYFIN_URL="http://localhost:8096"
API_KEY="YOUR_JELLYFIN_API_KEY"  # Get from Dashboard → Advanced → API Keys
PLUGIN_ID="b3f6b4c7-0a3d-4bd4-a7e3-c8d5a0a1e3f0"

# Get current configuration
echo "Current configuration:"
curl -s "${JELLYFIN_URL}/Plugins/${PLUGIN_ID}/Configuration" \
  -H "X-Emby-Token: ${API_KEY}" | jq .

# Update configuration
echo ""
echo "Updating configuration..."
curl -X POST "${JELLYFIN_URL}/Plugins/${PLUGIN_ID}/Configuration" \
  -H "Content-Type: application/json" \
  -H "X-Emby-Token: ${API_KEY}" \
  -d '{
    "AmbilightDataDirectory": "ambilight",
    "LibraryScanIntervalSeconds": 1800,
    "ExtractionBatchSize": 5,
    "ExtractionPriority": "newest_first",
    "ExtractViewed": false,
    "ExtractionMaxAgeDays": 0,
    "ExtractionStartTime": "",
    "ExtractionEndTime": "",
    "DefaultWledHost": "192.168.1.100",
    "DefaultWledUdpPort": 19446,
    "DeviceMatchField": "DeviceName",
    "AmbilightTopLedCount": 30,
    "AmbilightBottomLedCount": 30,
    "AmbilightLeftLedCount": 15,
    "AmbilightRightLedCount": 15,
    "AmbilightInputPosition": 0,
    "AmbilightRgbw": false,
    "AmbilightGamma": 2.2,
    "AmbilightSaturation": 1.0,
    "AmbilightBrightnessTarget": 60.0,
    "DeviceMappings": [],
    "RustExtractorPath": null,
    "RustPlayerPath": null
  }'

echo ""
echo "Done! Configuration updated."
