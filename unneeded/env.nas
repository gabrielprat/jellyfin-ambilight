# NAS Environment Configuration
# Example configuration for Synology/QNAP NAS deployment

# Jellyfin Configuration
JELLYFIN_API_KEY=your_jellyfin_api_key_here
JELLYFIN_BASE_URL=https://jellyfin.your-nas.local:8920

# Synology NAS paths (typical volume structure)
DATA_PATH=/volume1/docker/jellyfin-ambilight/data
MOVIES_PATH=/volume1/Movies
TV_PATH=/volume1/TV Shows

# QNAP NAS alternative paths:
# DATA_PATH=/share/Container/jellyfin-ambilight/data
# MOVIES_PATH=/share/Multimedia/Movies
# TV_PATH=/share/Multimedia/TV

# WLED Configuration
WLED_HOST=wled-device.local
WLED_UDP_PORT=21324

# LED Configuration
AMBILIGHT_TOP_LED_COUNT=89
AMBILIGHT_BOTTOM_LED_COUNT=89
AMBILIGHT_LEFT_LED_COUNT=49
AMBILIGHT_RIGHT_LED_COUNT=49
AMBILIGHT_INPUT_POSITION=46

# Conservative settings for NAS (lower CPU usage)
FRAMES_PER_SECOND=8
EXTRACTION_PRIORITY=newest_first
EXTRACTION_BATCH_SIZE=3

# Longer intervals to reduce NAS load
LIBRARY_SCAN_INTERVAL=7200
PLAYBACK_MONITOR_INTERVAL=1.0

# Storage
AMBILIGHT_DATA_DIR=/app/data/ambilight

# Network
DNS_SERVER=8.8.8.8

# Info logging for NAS
LOG_LEVEL=INFO

# Conservative resource limits for NAS
MEMORY_LIMIT=1G
CPU_LIMIT=0.5
