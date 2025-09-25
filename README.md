# Jellyfin Ambilight - Simplified Docker Setup

🎉 **10x smaller Docker image** - 181MB Alpine vs 1.89GB Debian!

## Quick Start

1. **Copy environment configuration:**
   ```bash
   cp env.example .env
   ```

2. **Edit `.env` with your settings:**
   ```bash
   # Update these required values:
   JELLYFIN_API_KEY=your_api_key_here
   JELLYFIN_BASE_URL=https://your-jellyfin-server.com
   MOVIES_PATH=/path/to/your/movies
   TV_PATH=/path/to/your/tv-shows
   WLED_HOST=your-wled-device.local
   ```

3. **Start the service:**
   ```bash
   docker-compose up -d
   ```

4. **Check logs:**
   ```bash
   docker-compose logs -f
   ```

That's it! 🚀

## What This Does

- **Monitors Jellyfin** for video playback
- **Extracts frame colors** using ultra-fast pure Python processing
- **Sends ambilight data** to your WLED device via UDP
- **Syncs perfectly** with play, pause, seek, and stop events

## System Requirements

- **Docker & Docker Compose**
- **181MB disk space** (vs 1.89GB for the old setup!)
- **~200MB RAM** (vs 2GB+ for the old setup!)
- **Jellyfin server** with API access
- **WLED device** on your network

## Architecture Highlights

### ✅ What We Kept
- All the core functionality
- File-based storage (no database)
- HTTP polling for reliable playback monitoring
- UDP packet optimization for WLED

### 🗑️ What We Removed
- ❌ **1.89GB Debian base** → 181MB Alpine
- ❌ **300+ system packages** → Just ffmpeg
- ❌ **Complex OpenCV** → Pure Python processing
- ❌ **NumPy compilation** → Standard library only
- ❌ **Complex user management** → Simple Alpine setup
- ❌ **Management scripts** → Standard docker-compose

## Development

The source code is mounted as a volume, so you can edit files and restart:

```bash
docker-compose restart
```

No rebuild needed! 🎯

## Troubleshooting

### Container won't start
```bash
docker-compose logs
```

### Check environment variables
```bash
docker-compose config
```

### Test Jellyfin connection
```bash
curl -H "Authorization: MediaBrowser Token=\"YOUR_API_KEY\"" \
     YOUR_JELLYFIN_URL/System/Info
```

### Resource usage
```bash
docker stats jellyfin-ambilight
```

## Alternative Configurations

For different deployment scenarios, you can use:

- `env.homeserver` - Local testing configuration
- `env.production` - Production server setup
- `env.remote-deployment` - Remote deployment template

Copy any of these to `.env` and adjust as needed.

---

**Previous Debian setup**: 1.89GB, complex scripts, 300+ packages
**New Alpine setup**: 181MB, standard workflow, minimal dependencies
**Same functionality, 10x efficiency!** 💪
