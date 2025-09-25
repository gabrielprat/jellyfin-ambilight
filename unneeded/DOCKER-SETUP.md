# Jellyfin Ambilight Docker Setup 🐳

Complete containerized solution for Jellyfin ambilight synchronization using **HTTP polling** (not WebSocket).

## 🎯 Features

- **🔄 HTTP Polling**: Reliable 1-second monitoring (no WebSocket issues)
- **📁 File-Based Storage**: Ultra-fast binary ambilight data (12x faster than database)
- **🔍 Auto-Discovery**: Automatically detects new videos and generates ambilight data
- **⚡ Real-Time Sync**: Perfect synchronization with play/pause/seek/stop events
- **🌈 WLED Integration**: Direct UDP packet transmission for minimal latency
- **🐳 Containerized**: Easy deployment and management
- **📊 Health Monitoring**: Built-in health checks and status monitoring
- **🔧 Auto-Recovery**: Handles connection failures gracefully

## 🚀 Quick Start

### 1. Configuration

Copy and edit the environment file:
```bash
cp env.example env.production
nano env.production
```

**Required settings:**
```bash
# Update these for your setup
JELLYFIN_API_KEY=your_jellyfin_api_key_here
JELLYFIN_BASE_URL=https://your-jellyfin-server.com
DATA_PATH=/your/data/path
MOVIES_PATH=/your/movies/path
TV_PATH=/your/tv/path
WLED_HOST=your-wled-device.lan
```

### 2. Start the Service

```bash
# Make management script executable
chmod +x docker-manager.sh

# Test configuration
./docker-manager.sh test

# Start the service
./docker-manager.sh start

# Monitor logs
./docker-manager.sh logs
```

### 3. Verify Operation

```bash
# Check status
./docker-manager.sh status

# View real-time logs
./docker-manager.sh logs
```

## 📋 Management Commands

The `docker-manager.sh` script provides comprehensive management:

```bash
./docker-manager.sh start      # Start the ambilight service
./docker-manager.sh stop       # Stop the service
./docker-manager.sh restart    # Restart the service
./docker-manager.sh logs       # Show real-time logs
./docker-manager.sh status     # Show container status and health
./docker-manager.sh test       # Test system configuration
./docker-manager.sh build      # Rebuild Docker image
./docker-manager.sh update     # Update and rebuild
./docker-manager.sh shell      # Open shell in container
./docker-manager.sh cleanup    # Remove old containers/images
./docker-manager.sh monitor    # Start with monitoring service
```

## 🔧 Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JELLYFIN_API_KEY` | *required* | Your Jellyfin API token |
| `JELLYFIN_BASE_URL` | *required* | Jellyfin server URL |
| `WLED_HOST` | `wled-ambilight-lgc1.lan` | WLED device hostname/IP |
| `WLED_UDP_PORT` | `21324` | WLED UDP port |
| `PLAYBACK_MONITOR_INTERVAL` | `1.0` | HTTP polling interval (seconds) |
| `LIBRARY_SCAN_INTERVAL` | `3600` | New video scan interval (seconds) |
| `FRAME_EXTRACTION_INTERVAL` | `300` | Background extraction interval (seconds) |
| `FRAMES_PER_SECOND` | `10` | Ambilight frame rate |
| `EXTRACTION_PRIORITY` | `newest_first` | Video processing priority |

### LED Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AMBILIGHT_TOP_LED_COUNT` | `89` | Top edge LED count |
| `AMBILIGHT_BOTTOM_LED_COUNT` | `89` | Bottom edge LED count |
| `AMBILIGHT_LEFT_LED_COUNT` | `49` | Left edge LED count |
| `AMBILIGHT_RIGHT_LED_COUNT` | `49` | Right edge LED count |
| `AMBILIGHT_INPUT_POSITION` | `46` | LED strip start position |

### Storage Paths

| Variable | Example | Description |
|----------|---------|-------------|
| `DATA_PATH` | `/mnt/storage/ambilight/data` | Persistent data directory |
| `MOVIES_PATH` | `/mnt/storage/Movies` | Movies directory (read-only) |
| `TV_PATH` | `/mnt/storage/Series` | TV shows directory (read-only) |

## 🏗️ Architecture

```
┌─────────────────┐    HTTP Polling     ┌─────────────────┐
│   Jellyfin      │ ◄─────────────────► │   Ambilight     │
│   Server        │    (1-second)       │   Container     │
└─────────────────┘                     └─────────────────┘
                                                │
                                                │ UDP Packets
                                                ▼
┌─────────────────┐                     ┌─────────────────┐
│   Video Files   │ ◄───── Extracts ────│   File Storage  │
│   (Read-Only)   │        Frames        │   (.udpdata)    │
└─────────────────┘                     └─────────────────┘
                                                │
                                                │ Direct UDP
                                                ▼
                                        ┌─────────────────┐
                                        │   WLED Device   │
                                        │   (Ambilight)   │
                                        └─────────────────┘
```

## 🔍 How It Works

1. **HTTP Polling**: Monitors Jellyfin sessions API every second (reliable, no WebSocket issues)
2. **Auto-Discovery**: Scans for new videos and extracts ambilight data in background
3. **File Storage**: Stores pre-computed UDP packets for ultra-fast access
4. **Real-Time Sync**: Detects play/pause/seek events and syncs ambilight instantly
5. **Direct UDP**: Sends ambilight data directly to WLED via UDP for minimal latency

## 📊 Monitoring

### Container Health

The container includes built-in health checks:

```bash
# Check health status
docker inspect jellyfin-ambilight --format='{{.State.Health.Status}}'

# View health check logs
docker inspect jellyfin-ambilight --format='{{range .State.Health.Log}}{{.Output}}{{end}}'
```

### Performance Monitoring

```bash
# Real-time resource usage
docker stats jellyfin-ambilight

# Storage usage
docker exec jellyfin-ambilight du -sh /app/data/ambilight
```

### Debug Logs

```bash
# Follow logs with timestamps
docker-compose logs -f --timestamps jellyfin-ambilight

# Filter for specific events
docker-compose logs jellyfin-ambilight | grep "🎬\|⏸️\|⏩\|⏹️"
```

## 🛠️ Troubleshooting

### Common Issues

#### 1. Container Won't Start
```bash
# Check configuration
./docker-manager.sh test

# View startup logs
./docker-manager.sh logs
```

#### 2. No Ambilight Data
```bash
# Check if videos are being processed
docker exec jellyfin-ambilight ls -la /app/data/ambilight/

# Monitor extraction process
./docker-manager.sh logs | grep "extraction\|📸"
```

#### 3. WLED Connection Issues
```bash
# Test WLED connectivity
docker exec jellyfin-ambilight ping $WLED_HOST

# Check UDP port
docker exec jellyfin-ambilight nc -u $WLED_HOST $WLED_UDP_PORT
```

#### 4. Jellyfin Connection Issues
```bash
# Test API connectivity
./docker-manager.sh test

# Check authorization headers
./docker-manager.sh logs | grep "authorization\|401\|403"
```

### Performance Tuning

#### For High-Performance Systems:
```bash
# Increase processing speed
PLAYBACK_MONITOR_INTERVAL=0.5    # 2x per second
FRAMES_PER_SECOND=15            # Higher FPS
EXTRACTION_BATCH_SIZE=10        # Process more videos at once
```

#### For Low-Resource Systems:
```bash
# Reduce resource usage
PLAYBACK_MONITOR_INTERVAL=2.0    # Every 2 seconds
FRAMES_PER_SECOND=5             # Lower FPS
EXTRACTION_BATCH_SIZE=2         # Process fewer videos
```

## 🔒 Security

### Network Isolation
The container only needs:
- **Outbound HTTP**: To Jellyfin server
- **Outbound UDP**: To WLED device
- **File Access**: To media directories (read-only)

### Minimal Privileges
- Runs as non-root user
- Read-only access to media files
- No exposed ports

## 🔄 Updates

### Automatic Updates
```bash
# Update to latest version
./docker-manager.sh update
```

### Manual Updates
```bash
# Pull latest code
git pull

# Rebuild and restart
./docker-manager.sh build
./docker-manager.sh restart
```

## 📈 Advanced Usage

### Multiple Ambilight Zones
To run multiple ambilight instances for different WLED devices:

```yaml
# In docker-compose.yaml
  jellyfin-ambilight-zone1:
    # ... standard config ...
    environment:
      - WLED_HOST=wled-zone1.lan
      - AMBILIGHT_DATA_DIR=/app/data/zone1

  jellyfin-ambilight-zone2:
    # ... standard config ...
    environment:
      - WLED_HOST=wled-zone2.lan
      - AMBILIGHT_DATA_DIR=/app/data/zone2
```

### Custom LED Configurations
For different LED strip layouts:

```bash
# Living room (large TV)
AMBILIGHT_TOP_LED_COUNT=120
AMBILIGHT_BOTTOM_LED_COUNT=120
AMBILIGHT_LEFT_LED_COUNT=68
AMBILIGHT_RIGHT_LED_COUNT=68

# Bedroom (small TV)
AMBILIGHT_TOP_LED_COUNT=60
AMBILIGHT_BOTTOM_LED_COUNT=60
AMBILIGHT_LEFT_LED_COUNT=34
AMBILIGHT_RIGHT_LED_COUNT=34
```

## 🎉 Success!

Once running, you should see:

```
✅ Connected to Jellyfin: YourServer v10.10.7
✅ WLED UDP test successful: wled-device.lan:21324
📁 Storage initialized: /app/data/ambilight
🎬 Starting file-based playback monitoring...
🌈 File-based ambilight: Movie Name @ 123.4s
```

Your ambilight will now automatically sync with any video playing in Jellyfin! 🌈
