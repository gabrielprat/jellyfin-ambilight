#!/usr/bin/env python3
"""
Jellyfin Ambilight Daemon
=========================

Production-ready service that:
1. Monitors Jellyfin library for new videos and extracts LED colors
2. Monitors Jellyfin playback sessions for play/pause/seek events
3. Controls WLED ambilight in real-time based on video position
4. Runs as a persistent daemon service

This integrates all components into a cohesive ambilight system.
"""

import os
import sys
import time
import threading
import socket
import json
import signal
import logging
from datetime import datetime
from typing import Dict, Optional

# Import local modules
sys.path.append('/app')
from database import (
    init_database, get_all_libraries, get_items_by_library,
    get_item_by_filepath, save_session_event, get_frames_for_item,
    frame_exists, get_videos_needing_extraction, get_extraction_statistics
)
# Import by loading the module directly to handle hyphenated filename
import importlib.util
spec = importlib.util.spec_from_file_location("frame_extractor", "/app/frame-extractor.py")
frame_extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frame_extractor)
extract_frames_from_video_memory = frame_extractor.extract_frames_from_video_memory
import requests

# Configuration
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))

# Service intervals
LIBRARY_SCAN_INTERVAL = int(os.getenv('LIBRARY_SCAN_INTERVAL', '3600'))  # 1 hour
PLAYBACK_MONITOR_INTERVAL = float(os.getenv('PLAYBACK_MONITOR_INTERVAL', '1.0'))  # 1 second
FRAME_EXTRACTION_INTERVAL = int(os.getenv('FRAME_EXTRACTION_INTERVAL', '300'))  # 5 minutes

# Frame extraction priority settings
EXTRACTION_PRIORITY = os.getenv('EXTRACTION_PRIORITY', 'newest_first')  # newest_first, oldest_first, alphabetical, random
EXTRACTION_BATCH_SIZE = int(os.getenv('EXTRACTION_BATCH_SIZE', '5'))  # Process N videos at a time

# Global state
shutdown_event = threading.Event()
logger = logging.getLogger(__name__)

class AmbilightDaemon:
    """Main daemon service orchestrating all ambilight components"""

    def __init__(self):
        self.udp_socket = None
        self.active_sessions: Dict[str, Dict] = {}
        self.prev_states: Dict[str, bool] = {}
        self.prev_positions: Dict[str, float] = {}

        # Initialize UDP socket
        self.init_udp_socket()

        logger.info("🌈 Jellyfin Ambilight Daemon initialized")
        logger.info(f"   JELLYFIN: {JELLYFIN_BASE_URL}")
        logger.info(f"   WLED: {WLED_HOST}:{WLED_UDP_PORT}")

    def init_udp_socket(self):
        """Initialize UDP socket for WLED communication"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            logger.info(f"✅ UDP socket initialized for WLED")
        except Exception as e:
            logger.error(f"❌ UDP socket failed: {e}")

    def send_colors_to_wled(self, led_colors):
        """Send LED colors to WLED via UDP"""
        if not self.udp_socket or not led_colors:
            return False

        try:
            # DRGB protocol
            packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])

            for color in led_colors:
                if color and len(color) >= 3:
                    packet.extend([int(color[0]), int(color[1]), int(color[2])])
                else:
                    packet.extend([0, 0, 0])

            self.udp_socket.sendto(packet, (WLED_HOST, WLED_UDP_PORT))
            return True

        except Exception as e:
            logger.error(f"UDP transmission error: {e}")
            return False

    def turn_off_wled(self):
        """Turn off WLED (black colors)"""
        black_colors = [[0, 0, 0] for _ in range(276)]  # 276 LEDs all black
        return self.send_colors_to_wled(black_colors)

    def get_jellyfin_user_id(self):
        """Get the first available Jellyfin user ID"""
        try:
            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Users",
                headers={"X-Emby-Token": JELLYFIN_API_KEY},
                timeout=5
            )
            response.raise_for_status()
            users = response.json()
            if users:
                return users[0]["Id"]
        except Exception as e:
            logger.error(f"Failed to get user ID: {e}")
        return None

    def perform_incremental_library_update(self, user_id):
        """Perform incremental library update (simplified version)"""
        try:
            # Get all libraries
            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Users/{user_id}/Views",
                headers={"X-Emby-Token": JELLYFIN_API_KEY},
                timeout=10
            )
            response.raise_for_status()
            libraries = response.json()

            # Process each library
            for lib in libraries.get("Items", []):
                lib_id = lib['Id']
                lib_name = lib['Name']

                logger.info(f"📚 Checking library: {lib_name}")

                # Get items from this library
                items_response = requests.get(
                    f"{JELLYFIN_BASE_URL}/Users/{user_id}/Items",
                    headers={"X-Emby-Token": JELLYFIN_API_KEY},
                    params={
                        "ParentId": lib_id,
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie,Episode,Video",
                        "Fields": "Path,MediaSources"
                    },
                    timeout=15
                )
                items_response.raise_for_status()
                items = items_response.json().get("Items", [])

                logger.info(f"   Found {len(items)} video items")

                # Save items to database
                from database import save_library, save_item
                save_library(lib_id, lib_name)

                for item in items:
                    item_id = item["Id"]
                    title = item.get("Name", "Unknown")
                    item_type = item.get("Type", "Unknown")

                    # Get filepath
                    filepath = "Unknown"
                    if "Path" in item:
                        filepath = item["Path"]
                    elif "MediaSources" in item and item["MediaSources"]:
                        filepath = item["MediaSources"][0].get("Path", "Unknown")

                    # Save to database
                    save_item(item_id, lib_id, title, item_type, filepath)

        except Exception as e:
            logger.error(f"Error in incremental library update: {e}")

    def get_jellyfin_sessions(self):
        """Get current Jellyfin playback sessions via HTTP API (NOT WebSocket!)"""
        try:
            # Use proper MediaBrowser authorization header format
            headers = {
                "Authorization": f'MediaBrowser Client="ambilight-daemon", Device="Python", DeviceId="ambilight-daemon-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
            }

            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Sessions",
                headers=headers,
                timeout=5
            )
            response.raise_for_status()
            sessions = response.json()

            # Filter for active video playback sessions
            video_sessions = []
            for session in sessions:
                now_playing = session.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    video_sessions.append(session)

            return video_sessions

        except Exception as e:
            logger.error(f"Failed to get Jellyfin sessions: {e}")
            return []

    def ticks_to_seconds(self, ticks):
        """Convert Jellyfin ticks to seconds"""
        return ticks / 10_000_000

    def get_led_colors_for_timestamp(self, item_id: str, timestamp: float) -> Optional[list]:
        """Get precomputed LED colors for a specific timestamp"""
        try:
            frames = get_frames_for_item(item_id)
            if not frames:
                return None

            # Find closest frame to the timestamp
            closest_frame = min(frames,
                              key=lambda f: abs(f['timestamp_seconds'] - timestamp))

            # Only use if within 0.15 seconds (our frame interval is 0.067s = 15 FPS)
            if abs(closest_frame['timestamp_seconds'] - timestamp) <= 0.15:
                return closest_frame['led_colors']

        except Exception as e:
            logger.error(f"Error getting LED colors for {item_id} at {timestamp}s: {e}")

        return None

    def monitor_playback_sessions(self):
        """Monitor Jellyfin playback sessions and control ambilight"""
        logger.info("🎬 Starting playback monitoring...")

        while not shutdown_event.is_set():
            try:
                sessions = self.get_jellyfin_sessions()
                current_session_ids = set()

                for session in sessions:
                    session_id = session["Id"]
                    current_session_ids.add(session_id)

                    now_playing = session.get("NowPlayingItem")
                    play_state = session.get("PlayState")
                    client = session.get("Client", "Unknown")

                    if not now_playing or not play_state:
                        continue

                    is_paused = play_state["IsPaused"]
                    position_ticks = play_state.get("PositionTicks", 0)
                    position_seconds = self.ticks_to_seconds(position_ticks)

                    # Get video filepath
                    filepath = "Unknown"
                    if "Path" in now_playing:
                        filepath = now_playing["Path"]
                    elif "MediaSources" in now_playing and now_playing["MediaSources"]:
                        filepath = now_playing["MediaSources"][0].get("Path", "Unknown")

                    # Find item in database
                    db_item = get_item_by_filepath(filepath)

                    # Handle play/pause state changes
                    if session_id not in self.prev_states or self.prev_states[session_id] != is_paused:
                        self.prev_states[session_id] = is_paused
                        state = "PAUSED" if is_paused else "PLAYING"

                        logger.info(f"{state}: {now_playing['Name']} at {position_seconds:.1f}s")

                        if db_item:
                            save_session_event(session_id, db_item['id'], client, state, position_seconds)

                            if state == "PLAYING":
                                # Get and send LED colors for current position
                                led_colors = self.get_led_colors_for_timestamp(db_item['id'], position_seconds)
                                if led_colors:
                                    self.send_colors_to_wled(led_colors)
                                    logger.debug(f"🌈 Sent colors for {position_seconds:.1f}s")
                                else:
                                    logger.warning(f"⚠️  No LED colors available for {db_item['name']} at {position_seconds:.1f}s")
                            else:  # PAUSED
                                # Keep current colors but maybe dim them or turn off
                                self.turn_off_wled()
                                logger.debug("⏸️  Turned off ambilight (paused)")
                        else:
                            logger.warning(f"📂 Video not in database: {filepath}")
                            save_session_event(session_id, None, client, state, position_seconds)

                    # Handle seek events and continuous playback
                    if session_id in self.prev_positions:
                        prev_pos = self.prev_positions[session_id]
                        time_diff = abs(position_seconds - prev_pos)

                        # Detect seek (jump > 2 seconds)
                        if time_diff > 2:
                            logger.info(f"⏩ SEEK: {now_playing['Name']} from {prev_pos:.1f}s to {position_seconds:.1f}s")

                            if db_item:
                                save_session_event(session_id, db_item['id'], client, "SEEK", position_seconds)

                                # Update ambilight for new position
                                if not is_paused:
                                    led_colors = self.get_led_colors_for_timestamp(db_item['id'], position_seconds)
                                    if led_colors:
                                        self.send_colors_to_wled(led_colors)
                                        logger.debug(f"🌈 Updated colors after seek to {position_seconds:.1f}s")

                        # Continuous playback updates (every ~0.5 seconds when playing for smooth ambilight)
                        elif not is_paused and time_diff >= 0.5:
                            if db_item:
                                led_colors = self.get_led_colors_for_timestamp(db_item['id'], position_seconds)
                                if led_colors:
                                    self.send_colors_to_wled(led_colors)
                                    logger.debug(f"🌈 Updated colors for playback at {position_seconds:.1f}s")

                    self.prev_positions[session_id] = position_seconds

                # Detect stopped sessions
                stopped_sessions = set(self.prev_states.keys()) - current_session_ids
                for session_id in stopped_sessions:
                    logger.info(f"⏹️  STOPPED session: {session_id}")
                    save_session_event(session_id, None, "Unknown", "STOPPED", 0)

                    # Clean up session state
                    self.prev_states.pop(session_id, None)
                    self.prev_positions.pop(session_id, None)

                    # Turn off ambilight if no active sessions
                    if not current_session_ids:
                        self.turn_off_wled()
                        logger.debug("💡 All sessions stopped - ambilight turned off")

            except Exception as e:
                logger.error(f"Error in playback monitoring: {e}")

            # Wait before next check
            time.sleep(PLAYBACK_MONITOR_INTERVAL)

    def scan_library_for_new_videos(self):
        """Scan library for new videos and extract frames"""
        logger.info("📚 Starting library scanning for new videos...")

        while not shutdown_event.is_set():
            try:
                # Get user ID for Jellyfin API
                user_id = self.get_jellyfin_user_id()
                if not user_id:
                    logger.error("Failed to get Jellyfin user ID")
                    time.sleep(LIBRARY_SCAN_INTERVAL)
                    continue

                # Perform incremental library update
                logger.info("🔄 Performing incremental library scan...")
                self.perform_incremental_library_update(user_id)

                # Get extraction statistics
                stats = get_extraction_statistics()
                logger.info(f"📊 Extraction status: {stats['extracted_videos']}/{stats['total_videos']} " +
                           f"({stats['completion_percentage']:.1f}% complete)")

                if stats['pending_videos'] > 0:
                    # Get videos that need extraction, prioritized
                    videos_to_process = get_videos_needing_extraction(
                        priority_order=EXTRACTION_PRIORITY,
                        limit=EXTRACTION_BATCH_SIZE
                    )

                    if videos_to_process:
                        logger.info(f"🎬 Processing {len(videos_to_process)} videos (priority: {EXTRACTION_PRIORITY})")

                        for i, item in enumerate(videos_to_process):
                            if shutdown_event.is_set():
                                break

                            logger.info(f"📸 [{i+1}/{len(videos_to_process)}] Extracting: {item['name']}")
                            logger.info(f"    Added: {item.get('created_at', 'Unknown')}")
                            logger.info(f"    Updated: {item.get('updated_at', 'Unknown')}")

                            try:
                                extract_frames_from_video_memory(
                                    item['id'],
                                    item['filepath'],
                                    item['name']
                                )
                                logger.info(f"✅ Completed frame extraction for: {item['name']}")
                            except Exception as e:
                                logger.error(f"❌ Failed to extract frames for {item['name']}: {e}")
                    else:
                        logger.info("✅ All videos have frames extracted")
                else:
                    logger.info("✅ All videos have frames extracted")

            except Exception as e:
                logger.error(f"Error in library scanning: {e}")

            # Wait before next scan
            for _ in range(LIBRARY_SCAN_INTERVAL):
                if shutdown_event.is_set():
                    break
                time.sleep(1)

    def periodic_frame_extraction(self):
        """Periodically check for videos that need frame extraction"""
        logger.info("🔄 Starting periodic frame extraction checks...")

        while not shutdown_event.is_set():
            try:
                # Get extraction statistics
                stats = get_extraction_statistics()

                if stats['pending_videos'] > 0:
                    logger.info(f"⏳ {stats['pending_videos']} videos still need frame extraction")
                    logger.info(f"📊 Progress: {stats['completion_percentage']:.1f}% complete")

                    # Process a small batch of videos
                    videos_to_process = get_videos_needing_extraction(
                        priority_order=EXTRACTION_PRIORITY,
                        limit=min(EXTRACTION_BATCH_SIZE, 3)  # Smaller batch for periodic checks
                    )

                    if videos_to_process:
                        logger.info(f"🎬 Processing {len(videos_to_process)} high-priority videos...")

                        for item in videos_to_process:
                            if shutdown_event.is_set():
                                break

                            logger.info(f"📸 Quick extraction: {item['name']}")
                            try:
                                extract_frames_from_video_memory(
                                    item['id'],
                                    item['filepath'],
                                    item['name']
                                )
                                logger.info(f"✅ Completed: {item['name']}")
                            except Exception as e:
                                logger.error(f"❌ Failed: {item['name']}: {e}")
                else:
                    logger.debug("✅ All videos have frames extracted")

            except Exception as e:
                logger.error(f"Error in periodic frame check: {e}")

            # Wait before next check
            for _ in range(FRAME_EXTRACTION_INTERVAL):
                if shutdown_event.is_set():
                    break
                time.sleep(1)

    def run(self):
        """Run the complete ambilight daemon"""
        logger.info("🚀 Starting Jellyfin Ambilight Daemon")

        # Initialize database
        init_database()

        # Start background threads
        threads = []

        # Library scanning thread
        library_thread = threading.Thread(
            target=self.scan_library_for_new_videos,
            name="LibraryScanner",
            daemon=True
        )
        library_thread.start()
        threads.append(library_thread)

        # Periodic frame extraction thread
        frame_thread = threading.Thread(
            target=self.periodic_frame_extraction,
            name="FrameExtractor",
            daemon=True
        )
        frame_thread.start()
        threads.append(frame_thread)

        # Playback monitoring thread (main ambilight control)
        playback_thread = threading.Thread(
            target=self.monitor_playback_sessions,
            name="PlaybackMonitor",
            daemon=True
        )
        playback_thread.start()
        threads.append(playback_thread)

        logger.info("✅ All daemon threads started")
        logger.info("   📚 Library scanning every %d seconds", LIBRARY_SCAN_INTERVAL)
        logger.info("   🎬 Playback monitoring every %.1f seconds", PLAYBACK_MONITOR_INTERVAL)
        logger.info("   🔄 Frame checking every %d seconds", FRAME_EXTRACTION_INTERVAL)

        try:
            # Keep main thread alive
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Shutdown requested")
            shutdown_event.set()

        # Wait for threads to finish
        logger.info("⏳ Waiting for background threads to finish...")
        for thread in threads:
            thread.join(timeout=5)

        # Cleanup
        if self.udp_socket:
            self.turn_off_wled()  # Turn off ambilight
            self.udp_socket.close()

        logger.info("👋 Jellyfin Ambilight Daemon stopped")

def setup_logging():
    """Setup logging configuration"""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/app/data/ambilight.log')
        ]
    )

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_event.set()

def main():
    """Main entry point"""
    setup_logging()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Validate configuration
    if not JELLYFIN_API_KEY or not JELLYFIN_BASE_URL:
        logger.error("❌ JELLYFIN_API_KEY and JELLYFIN_BASE_URL must be set")
        sys.exit(1)

    # Create and run daemon
    daemon = AmbilightDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
