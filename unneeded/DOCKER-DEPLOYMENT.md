# Jellyfin Ambilight - Volume-Based Docker Deployment 🐳

**Development-friendly deployment with volume mounts - no rebuilds needed for code changes!**

## 🎯 Key Features

- **📂 Volume Mounts**: Source code mounted as volumes - no container rebuilds needed
- **⚡ Fast Development**: Edit code, restart service, changes apply immediately
- **🌍 Multi-Environment**: Different configs for development, production, home server, NAS
- **🔄 HTTP Polling**: Reliable 1-second monitoring (no WebSocket issues)
- **🚀 Easy Deployment**: Works on any machine with Docker

## 🚀 Quick Start

### 1. Choose Your Environment

Copy the appropriate environment file:

```bash
# For development/testing
cp env.development .env

# For production home server
cp env.homeserver .env

# For NAS deployment (Synology/QNAP)
cp env.nas .env

# Or use the general production config
cp env.production .env
```

### 2. Configure for Your System

Edit your `.env` file with your paths:

```bash
# Required: Update these for your target machine
JELLYFIN_API_KEY=your_jellyfin_api_key_here
JELLYFIN_BASE_URL=https://your-jellyfin-server.com

# Update these paths for your target deployment machine
MOVIES_PATH=/your/movies/path
TV_PATH=/your/tv/path
DATA_PATH=/your/data/path

# WLED device
WLED_HOST=your-wled-device.local
```

### 3. Deploy

```bash
# Make script executable
chmod +x docker-manager.sh

# Build image (only needed once!)
./docker-manager.sh build

# Start service
./docker-manager.sh start

# Monitor
./docker-manager.sh logs
```

## 📋 Environment Examples

### Home Server Example
```bash
# env.homeserver
MOVIES_PATH=/mnt/storage/Movies
TV_PATH=/mnt/storage/Series
DATA_PATH=/home/user/jellyfin-ambilight/data
WLED_HOST=wled-livingroom.local
```

### NAS Example (Synology)
```bash
# env.nas
MOVIES_PATH=/volume1/Movies
TV_PATH=/volume1/TV Shows
DATA_PATH=/volume1/docker/jellyfin-ambilight/data
WLED_HOST=wled-device.local
```

### Development Example
```bash
# env.development
MOVIES_PATH=./test-media/movies
TV_PATH=./test-media/tv
DATA_PATH=./data
WLED_HOST=wled-ambilight-lgc1.lan
LOG_LEVEL=DEBUG
```

## 🛠️ Management Commands

### Basic Operations
```bash
./docker-manager.sh start [environment]    # Start service
./docker-manager.sh stop                   # Stop service
./docker-manager.sh restart                # Restart service
./docker-manager.sh logs                   # View logs
./docker-manager.sh status                 # Show status
```

### Testing & Development
```bash
./docker-manager.sh test [environment]     # Test configuration
./docker-manager.sh testrun [environment]  # Quick connectivity test
./docker-manager.sh shell                  # Open container shell
./docker-manager.sh monitor               # Start with monitoring
```

### System Management
```bash
./docker-manager.sh build                 # Build image (one-time)
./docker-manager.sh update                # Update code (no rebuild!)
./docker-manager.sh cleanup               # Clean old images
```

## 🔧 Development Workflow

**🎉 No more container rebuilds for code changes!**

```bash
# 1. Build image once
./docker-manager.sh build

# 2. Start development environment
./docker-manager.sh start development

# 3. Edit code in your favorite editor
nano ambilight-daemon-files.py

# 4. Restart to apply changes (no rebuild!)
./docker-manager.sh restart

# 5. View logs
./docker-manager.sh logs
```

### How Volume Mounts Work
```yaml
volumes:
  - ./:/app/src:ro  # Your source code mounted read-only
  - ./data:/app/data  # Persistent data
```

- Code changes are **immediately available** in the container
- Just restart the service to pick up changes
- No rebuild, no waiting, no hassle!

## 🌍 Multi-Environment Deployment

### Use Different Configs
```bash
# Development
./docker-manager.sh start development

# Production
./docker-manager.sh start production

# Home server
./docker-manager.sh start homeserver

# NAS deployment
./docker-manager.sh start nas

# Test specific environment
./docker-manager.sh test nas
```

### Environment-Specific Settings

Each environment has optimized settings:

| Environment | LED Count | FPS | CPU Limit | Use Case |
|-------------|-----------|-----|-----------|----------|
| development | 30x30x20x20 | 5 | 0.5 | Local testing |
| production | 89x89x49x49 | 10 | 1.0 | Full deployment |
| homeserver | 89x89x49x49 | 10 | 1.0 | Home server |
| nas | 89x89x49x49 | 8 | 0.5 | NAS deployment |

## 📁 Directory Structure

```
jellyfin-ambilight/
├── docker-manager.sh          # Management script
├── Dockerfile                 # Container definition
├── docker-compose.yaml        # Service definition
├── env.development            # Development config
├── env.production             # Production config
├── env.homeserver            # Home server config
├── env.nas                   # NAS config
├── data/                     # Persistent data (auto-created)
│   ├── ambilight/           # Binary ambilight files
│   ├── logs/                # Service logs
│   └── frames/              # Extracted frames
└── [source files mounted as volumes]
```

## 🔍 Testing & Troubleshooting

### Quick Connectivity Test
```bash
# Test without starting full service
./docker-manager.sh testrun

# Test specific environment
./docker-manager.sh testrun homeserver
```

### Configuration Testing
```bash
# Validate environment configuration
./docker-manager.sh test development

# Check paths and connectivity
./docker-manager.sh test production
```

### Debug Mode
```bash
# Set debug logging in your .env file
LOG_LEVEL=DEBUG

# Restart and view detailed logs
./docker-manager.sh restart
./docker-manager.sh logs
```

### Container Shell Access
```bash
# Access running container
./docker-manager.sh shell

# Inside container, check paths
ls -la /app/src/
ls -la /media/
ls -la /app/data/
```

## 🚀 Deployment Scenarios

### Scenario 1: Local Development
```bash
cp env.development .env
# Edit paths if needed
./docker-manager.sh build
./docker-manager.sh start development
./docker-manager.sh logs
```

### Scenario 2: Home Server
```bash
cp env.homeserver .env
# Edit JELLYFIN_API_KEY, paths, WLED_HOST
./docker-manager.sh build
./docker-manager.sh start homeserver
./docker-manager.sh status
```

### Scenario 3: Remote Server Deployment
```bash
# Copy project to remote server
scp -r . user@server:/opt/jellyfin-ambilight/

# SSH to server
ssh user@server
cd /opt/jellyfin-ambilight

# Configure for server environment
cp env.production .env
# Edit all paths and settings

# Deploy
./docker-manager.sh build
./docker-manager.sh start production
./docker-manager.sh monitor
```

### Scenario 4: NAS Deployment
```bash
# Copy to NAS (via web interface or SSH)
cp env.nas .env

# Edit for NAS paths
MOVIES_PATH=/volume1/Movies
TV_PATH=/volume1/TV Shows
DATA_PATH=/volume1/docker/jellyfin-ambilight/data

# Deploy with conservative resource limits
./docker-manager.sh build
./docker-manager.sh start nas
```

## 📊 Monitoring & Logs

### Real-time Monitoring
```bash
# Follow all logs
./docker-manager.sh logs

# Monitor specific events
docker-compose logs -f | grep "🎬\|⏸️\|⏩\|⏹️"

# Container resource usage
docker stats jellyfin-ambilight
```

### Health Checks
```bash
# Container health
./docker-manager.sh status

# Service health
docker inspect jellyfin-ambilight --format='{{.State.Health.Status}}'
```

## 🔧 Customization

### Custom LED Configurations
Create a custom environment file:
```bash
cp env.production env.custom

# Edit LED counts for your setup
AMBILIGHT_TOP_LED_COUNT=120
AMBILIGHT_BOTTOM_LED_COUNT=120
AMBILIGHT_LEFT_LED_COUNT=68
AMBILIGHT_RIGHT_LED_COUNT=68

# Use custom config
./docker-manager.sh start custom
```

### Multiple WLED Devices
```bash
# Create zone-specific configs
cp env.production env.zone1
cp env.production env.zone2

# Configure different WLED devices
# env.zone1: WLED_HOST=wled-livingroom.local
# env.zone2: WLED_HOST=wled-bedroom.local

# Deploy multiple instances
docker-compose --env-file env.zone1 up -d
docker-compose --env-file env.zone2 up -d
```

## ✅ Advantages of Volume-Based Deployment

1. **🚀 Fast Development**: No rebuilds for code changes
2. **🌍 Portable**: Same container works on any machine
3. **🔧 Flexible**: Easy environment switching
4. **💾 Persistent**: Data survives container restarts
5. **🛡️ Secure**: Non-root container user
6. **📊 Scalable**: Resource limits per environment
7. **🔍 Debuggable**: Easy access to logs and shell

## 🎉 Ready to Deploy!

Your Jellyfin ambilight system is now ready for deployment on any machine with Docker. The volume-based approach means you can develop locally and deploy anywhere without modification.

**Start with**: `./docker-manager.sh start development` and enjoy your synchronized ambilight! 🌈
