# Environment Variables - Actually Used vs Removed 🧹

## ✅ Variables Actually Used

### **Required Configuration**
```bash
# Jellyfin Connection (REQUIRED)
JELLYFIN_API_KEY=your_api_key_here       # Used by: ambilight-daemon-files.py
JELLYFIN_BASE_URL=https://jellyfin.local  # Used by: ambilight-daemon-files.py

# WLED Connection (REQUIRED)
WLED_HOST=wled-device.local               # Used by: ambilight-daemon-files.py
WLED_UDP_PORT=21324                       # Used by: ambilight-daemon-files.py

# Storage (REQUIRED)
AMBILIGHT_DATA_DIR=/app/data/ambilight    # Used by: ambilight-daemon-files.py
```

### **LED Configuration**
```bash
# LED Strip Layout (used by fast_extractor.py)
AMBILIGHT_TOP_LED_COUNT=89                # Used by: fast_extractor.py
AMBILIGHT_BOTTOM_LED_COUNT=89             # Used by: fast_extractor.py
AMBILIGHT_LEFT_LED_COUNT=49               # Used by: fast_extractor.py
AMBILIGHT_RIGHT_LED_COUNT=49              # Used by: fast_extractor.py
AMBILIGHT_INPUT_POSITION=46               # Used by: fast_extractor.py
```

### **Frame Extraction Settings**
```bash
# Frame Processing (used by fast_extractor.py)
FRAMES_PER_SECOND=10                      # Used by: fast_extractor.py
EXTRACTION_PRIORITY=newest_first          # Used by: ambilight-daemon-files.py
EXTRACTION_BATCH_SIZE=5                   # Used by: ambilight-daemon-files.py
```

### **Service Timing**
```bash
# Daemon Intervals (used by ambilight-daemon-files.py)
LIBRARY_SCAN_INTERVAL=3600                # Used by: scan_library_for_new_videos()
PLAYBACK_MONITOR_INTERVAL=1.0             # Used by: monitor_playback_with_files()
```

### **Optional Configuration**
```bash
# Logging & Docker
LOG_LEVEL=INFO                            # Used by: Docker container
DNS_SERVER=8.8.8.8                       # Used by: Docker container
MEMORY_LIMIT=2G                           # Used by: Docker compose
CPU_LIMIT=1.0                             # Used by: Docker compose

# Host Path Mapping (Docker only)
DATA_PATH=./data                          # Used by: Docker volume mount
MOVIES_PATH=/path/to/movies               # Used by: Docker volume mount
TV_PATH=/path/to/tv                       # Used by: Docker volume mount
```

## ❌ Variables REMOVED (Not Actually Used)

### **Removed from File-Based System**
```bash
# These were included but NOT used by ambilight-daemon-files.py:
FRAME_EXTRACTION_INTERVAL=300             # ❌ REMOVED - not used!
SKIP_EXISTING=true                        # ❌ REMOVED - not used!
WLED_PORT=80                             # ❌ REMOVED - only UDP used!
WLED_USE_UDP=true                        # ❌ REMOVED - always UDP!
WLED_TIMEOUT=5                           # ❌ REMOVED - not used!
```

### **Why These Were Removed**

#### `FRAME_EXTRACTION_INTERVAL` ❌
- **Issue**: Only used in `ambilight-daemon.py` (database version)
- **Fact**: File-based daemon (`ambilight-daemon-files.py`) has no `periodic_frame_extraction()` function
- **Reality**: Frame extraction happens during `scan_library_for_new_videos()` using `LIBRARY_SCAN_INTERVAL`

#### `SKIP_EXISTING` ❌
- **Issue**: Not referenced anywhere in the file-based system
- **Fact**: File storage automatically skips existing files

#### `WLED_PORT`, `WLED_USE_UDP`, `WLED_TIMEOUT` ❌
- **Issue**: File-based daemon only uses UDP, never HTTP API
- **Fact**: Only `WLED_HOST` and `WLED_UDP_PORT` are actually used

## 🎯 How Each Variable is Used

### **ambilight-daemon-files.py** (Main Daemon)
```python
# Service intervals
LIBRARY_SCAN_INTERVAL = int(os.getenv('LIBRARY_SCAN_INTERVAL', '3600'))      # ✅ USED
PLAYBACK_MONITOR_INTERVAL = float(os.getenv('PLAYBACK_MONITOR_INTERVAL', '1.0'))  # ✅ USED

# Jellyfin connection
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")                             # ✅ USED
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")                           # ✅ USED

# WLED connection
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')                # ✅ USED
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))                     # ✅ USED

# LED configuration (passed to fast_extractor)
AMBILIGHT_TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))    # ✅ USED
# ... other LED counts

# Frame extraction settings
EXTRACTION_PRIORITY = os.getenv('EXTRACTION_PRIORITY', 'newest_first')       # ✅ USED
EXTRACTION_BATCH_SIZE = int(os.getenv('EXTRACTION_BATCH_SIZE', '5'))         # ✅ USED

# Storage
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")   # ✅ USED
```

### **fast_extractor.py** (Frame Processing)
```python
# LED configuration
TOP = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", 89))                          # ✅ USED
BOTTOM = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", 89))                    # ✅ USED
LEFT = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", 49))                        # ✅ USED
RIGHT = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", 49))                      # ✅ USED
INPUT_POSITION = int(os.getenv("AMBILIGHT_INPUT_POSITION", 46))              # ✅ USED

# Frame extraction
FPS = float(os.getenv("FRAMES_PER_SECOND", 10))                              # ✅ USED
```

## 🧹 Clean Environment Files

The cleaned environment files now contain **only variables that are actually used**:

- **env.production** - Production deployment
- **env.development** - Local development (smaller LED counts, debug logging)
- **env.homeserver** - Home server setup
- **env.nas** - NAS deployment (conservative resource usage)

## 📊 Before vs After

### Before (Bloated) ❌
```bash
# 15+ variables, many unused
FRAME_EXTRACTION_INTERVAL=300    # ❌ Not used!
SKIP_EXISTING=true              # ❌ Not used!
WLED_PORT=80                    # ❌ Not used!
WLED_USE_UDP=true               # ❌ Not used!
WLED_TIMEOUT=5                  # ❌ Not used!
```

### After (Clean) ✅
```bash
# Only 12 core variables, all used
JELLYFIN_API_KEY=...            # ✅ Required
JELLYFIN_BASE_URL=...           # ✅ Required
WLED_HOST=...                   # ✅ Required
WLED_UDP_PORT=...               # ✅ Required
# ... only variables actually used
```

## 🎯 Result

- **Cleaner configuration** - no confusion about unused variables
- **Faster startup** - fewer environment variables to process
- **Better documentation** - each variable has a clear purpose
- **Easier deployment** - only configure what actually matters

**The system now has exactly the variables it needs, nothing more!** 🎉
