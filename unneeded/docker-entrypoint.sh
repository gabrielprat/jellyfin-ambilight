#!/bin/bash
set -e

echo "🐳 Jellyfin Ambilight Container Starting..."
echo "================================================"

# Print configuration
echo "📊 Configuration:"
echo "   Jellyfin URL: ${JELLYFIN_BASE_URL}"
echo "   WLED Host: ${WLED_HOST}:${WLED_UDP_PORT}"
echo "   Data Directory: ${AMBILIGHT_DATA_DIR}"
echo "   Monitor Interval: ${PLAYBACK_MONITOR_INTERVAL}s"
echo "   Log Level: ${LOG_LEVEL}"

# Validate required environment variables
if [ -z "$JELLYFIN_API_KEY" ]; then
    echo "❌ ERROR: JELLYFIN_API_KEY is required"
    exit 1
fi

if [ -z "$JELLYFIN_BASE_URL" ]; then
    echo "❌ ERROR: JELLYFIN_BASE_URL is required"
    exit 1
fi

# Create necessary directories
echo "📁 Creating data directories..."

# Create directories with proper error handling
create_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        echo "   Creating: $dir"
        if ! mkdir -p "$dir" 2>/dev/null; then
            echo "   ⚠️  Cannot create $dir - trying as root..."
            if command -v sudo >/dev/null; then
                sudo mkdir -p "$dir" && sudo chown $(id -u):$(id -g) "$dir"
            else
                echo "   ❌ Failed to create $dir (no sudo available)"
                echo "   💡 Using /tmp as fallback for this directory"
                case "$dir" in
                    */logs) export LOG_DIR="/tmp/ambilight-logs" && mkdir -p "$LOG_DIR" ;;
                    */frames) export FRAMES_DIR="/tmp/ambilight-frames" && mkdir -p "$FRAMES_DIR" ;;
                    *) echo "   ⚠️  Directory creation failed: $dir" ;;
                esac
            fi
        fi
    else
        echo "   ✅ Directory exists: $dir"
    fi
}

# Create ambilight data directory
create_dir "${AMBILIGHT_DATA_DIR}"

# Create standard directories with fallbacks
create_dir "/app/data/logs"
create_dir "/app/data/frames"

# Try to set permissions if we can
if [ -w "/app/data" ]; then
    echo "   🔧 Setting permissions on /app/data/"
    chmod -R 755 /app/data/ 2>/dev/null || echo "   ⚠️  Could not set permissions"
else
    echo "   ⚠️  /app/data/ not writable - this may cause issues"
fi

# Test Jellyfin connectivity
echo "🧪 Testing Jellyfin connectivity..."
python3 -c "
import requests
import sys
import os

try:
    headers = {
        'Authorization': f'MediaBrowser Client=\"ambilight-docker\", Device=\"Docker\", DeviceId=\"ambilight-docker-001\", Version=\"1.0\", Token=\"{os.environ[\"JELLYFIN_API_KEY\"]}\"'
    }
    response = requests.get(f'{os.environ[\"JELLYFIN_BASE_URL\"]}/System/Info', headers=headers, timeout=10)
    if response.status_code == 200:
        info = response.json()
        print(f'✅ Connected to Jellyfin: {info.get(\"ServerName\", \"Unknown\")} v{info.get(\"Version\", \"Unknown\")}')
    else:
        print(f'❌ Jellyfin connection failed: HTTP {response.status_code}')
        sys.exit(1)
except Exception as e:
    print(f'❌ Cannot connect to Jellyfin: {e}')
    sys.exit(1)
"

# Test WLED connectivity (optional - don't fail if WLED is not available)
echo "🧪 Testing WLED connectivity..."
python3 -c "
import socket
import sys
import os

try:
    wled_host = os.environ.get('WLED_HOST', 'wled-ambilight-lgc1.lan')
    wled_port = int(os.environ.get('WLED_UDP_PORT', '21324'))

    # Test UDP socket creation
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)

    # Try to send a test packet (all black LEDs)
    test_packet = b'DRGB' + bytes([1]) + bytes([0, 0, 0] * 10)  # 10 black LEDs
    sock.sendto(test_packet, (wled_host, wled_port))
    sock.close()

    print(f'✅ WLED UDP test successful: {wled_host}:{wled_port}')
except Exception as e:
    print(f'⚠️  WLED test failed (will continue anyway): {e}')
"

# Show storage status
echo "📊 Storage status:"
echo "   Data directory: $(du -sh ${AMBILIGHT_DATA_DIR} 2>/dev/null || echo 'Empty')"
echo "   Available space: $(df -h ${AMBILIGHT_DATA_DIR} | tail -1 | awk '{print $4}')"

# Initialize file storage if needed
echo "🔧 Initializing file storage..."
python3 -c "
import sys
sys.path.append('/app')
from storage.storage import FileBasedStorage
import os

storage = FileBasedStorage(os.environ['AMBILIGHT_DATA_DIR'])
info = storage.get_storage_info()
print(f'📁 Storage initialized: {info[\"data_directory\"]}')
print(f'   UDP files: {info[\"udp_file_count\"]}')
print(f'   Index files: {info[\"index_file_count\"]}')
print(f'   Total size: {info[\"total_size_mb\"]:.1f} MB')
"

echo "================================================"
echo "🚀 Starting Jellyfin Ambilight Service..."
echo "   Command: $@"
echo "   User: $(whoami)"
echo "================================================"

# Switch to ambilight user and execute the command
if [ "$(id -u)" = "0" ]; then
    echo "🔄 Switching to ambilight user..."
    # Ensure proper ownership of created directories
    chown -R ambilight:ambilight /app/data/ 2>/dev/null || echo "⚠️  Could not change ownership"
    # Execute command as ambilight user
    exec gosu ambilight "$@"
else
    # Already running as non-root user
    exec "$@"
fi
