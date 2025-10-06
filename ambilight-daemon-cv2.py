#!/usr/bin/env python3
"""
CV2-Based Ambilight Daemon
==========================

A variant of the file-based daemon that:
- Uses simplified/extractor_cv2.py for frame extraction
- Uses simplified/ambilight_play.py for playback over UDP

This keeps a per-session player thread using AmbilightBinaryPlayer.
"""

import os
import sys
import time
import threading
import socket
import signal
import logging
import requests
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict
from pathlib import Path

from storage.storage import FileBasedStorage

# Local module paths (container mount)
sys.path.append('/app')
sys.path.append('/app/storage')
sys.path.append('/app/frames')

from simplified.extractor_cv2 import extract_frames  # noqa: E402
from simplified.ambilight_play import AmbilightBinaryPlayer  # noqa: E402


# Configuration
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))
WLED_LED_COUNT = int(os.getenv('WLED_LED_COUNT', '300'))
WLED_UDP_RAW_PORT = int(os.getenv('WLED_UDP_RAW_PORT', '19446'))

AMBILIGHT_DNS_TTL_SECONDS = int(os.getenv('AMBILIGHT_DNS_TTL_SECONDS', '3600'))
AMBILIGHT_DISABLE_DNS_RESOLVE = os.getenv('AMBILIGHT_DISABLE_DNS_RESOLVE', 'false').lower() == 'true'

# Polling intervals
LIBRARY_SCAN_INTERVAL = int(os.getenv('LIBRARY_SCAN_INTERVAL', '3600'))
PLAYBACK_MONITOR_INTERVAL = float(os.getenv('PLAYBACK_MONITOR_INTERVAL', '0.2'))

# Extraction queue configuration
EXTRACTION_PRIORITY = os.getenv('EXTRACTION_PRIORITY', 'newest_first')
EXTRACTION_BATCH_SIZE = int(os.getenv('EXTRACTION_BATCH_SIZE', '5'))

# Device-WLED Pairing
DEVICE_MATCH_FIELD = os.getenv('DEVICE_MATCH_FIELD', 'DeviceName')
ENABLE_EXTRACTION = os.getenv('ENABLE_EXTRACTION', 'true').lower() == 'true'

# File storage
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")


shutdown_event = threading.Event()
logger = logging.getLogger(__name__)


class CV2AmbilightDaemon:
    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        self.storage = FileBasedStorage(AMBILIGHT_DATA_DIR)
        self._players: Dict[str, AmbilightBinaryPlayer] = {}
        self._player_threads: Dict[str, threading.Thread] = {}
        self._jellyfin_parsed = urlparse(JELLYFIN_BASE_URL) if JELLYFIN_BASE_URL else None
        self._jellyfin_resolved_ip = None
        self._jellyfin_last_resolve_ts = 0.0
        self._wled_resolved_ip = None
        self._wled_last_resolve_ts = 0.0

        logger.info("📁 CV2-Based Jellyfin Ambilight Daemon")
        logger.info(f"   JELLYFIN: {JELLYFIN_BASE_URL}")
        logger.info(f"   WLED: {WLED_HOST}:{WLED_UDP_RAW_PORT}")
        logger.info(f"   STORAGE: {AMBILIGHT_DATA_DIR}")

    # --- Jellyfin DNS helpers (copy from files daemon) ---
    def _resolve_jellyfin_if_needed(self, force: bool = False):
        if not self._jellyfin_parsed:
            return
        if AMBILIGHT_DISABLE_DNS_RESOLVE:
            self._jellyfin_resolved_ip = None
            return
        now = time.time()
        if AMBILIGHT_DNS_TTL_SECONDS == 0:
            force = True
        if not force and self._jellyfin_resolved_ip and (now - self._jellyfin_last_resolve_ts) < AMBILIGHT_DNS_TTL_SECONDS:
            return
        try:
            import threading as _t
            import queue as _q
            result_queue = _q.Queue()
            exception_queue = _q.Queue()

            def dns_worker():
                try:
                    infos = socket.getaddrinfo(self._jellyfin_parsed.hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
                    if infos:
                        ip = infos[0][4][0]
                        result_queue.put(ip)
                except Exception as e:
                    exception_queue.put(e)

            t = _t.Thread(target=dns_worker, daemon=True)
            t.start()
            t.join(timeout=5.0)
            if t.is_alive():
                logger.warning(f"DNS resolution timeout for Jellyfin host {self._jellyfin_parsed.hostname}")
                return
            if not exception_queue.empty():
                raise exception_queue.get()
            if not result_queue.empty():
                ip = result_queue.get()
                self._jellyfin_resolved_ip = ip
                self._jellyfin_last_resolve_ts = now
                logger.info(f"DNS resolved Jellyfin {self._jellyfin_parsed.hostname} → {ip}")
        except Exception as e:
            logger.warning(f"DNS resolve failed for Jellyfin host {self._jellyfin_parsed.hostname}: {e}")

    def _jellyfin_base_resolved(self) -> tuple[str, dict]:
        if not self._jellyfin_parsed:
            return JELLYFIN_BASE_URL, {}
        self._resolve_jellyfin_if_needed()
        host = self._jellyfin_resolved_ip or self._jellyfin_parsed.hostname
        port = f":{self._jellyfin_parsed.port}" if self._jellyfin_parsed.port else ''
        base = f"{self._jellyfin_parsed.scheme}://{host}{port}"
        return base, {"Host": self._jellyfin_parsed.netloc}

    # --- WLED DNS helper ---
    def _resolve_wled_if_needed(self, force: bool = False):
        if AMBILIGHT_DISABLE_DNS_RESOLVE:
            self._wled_resolved_ip = None
            return
        now = time.time()
        if AMBILIGHT_DNS_TTL_SECONDS == 0:
            force = True
        if not force and self._wled_resolved_ip and (now - self._wled_last_resolve_ts) < AMBILIGHT_DNS_TTL_SECONDS:
            return
        try:
            import threading as _t
            import queue as _q
            result_queue = _q.Queue()
            exception_queue = _q.Queue()

            def dns_worker():
                try:
                    infos = socket.getaddrinfo(WLED_HOST, None, family=socket.AF_INET, type=socket.SOCK_DGRAM)
                    if infos:
                        ip = infos[0][4][0]
                        result_queue.put(ip)
                except Exception as e:
                    exception_queue.put(e)

            t = _t.Thread(target=dns_worker, daemon=True)
            t.start()
            t.join(timeout=3.0)
            if t.is_alive():
                logger.warning(f"DNS resolution timeout for WLED host {WLED_HOST}")
                return
            if not exception_queue.empty():
                raise exception_queue.get()
            if not result_queue.empty():
                ip = result_queue.get()
                self._wled_resolved_ip = ip
                self._wled_last_resolve_ts = now
                logger.info(f"DNS resolved WLED {WLED_HOST} → {ip}")
        except Exception as e:
            logger.warning(f"DNS resolve failed for WLED host {WLED_HOST}: {e}")

    # --- Jellyfin API helpers ---
    def get_jellyfin_user_id(self):
        try:
            base, host_header = self._jellyfin_base_resolved()
            hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
            hdrs.update(host_header)
            r = requests.get(f"{base}/Users", headers=hdrs, timeout=10)
            r.raise_for_status()
            users = r.json()
            if users:
                uid = users[0]["Id"]
                logger.info(f"🔐 Using Jellyfin user: {users[0].get('Name', 'Unknown')}")
                return uid
        except Exception as e:
            logger.warning(f"Failed to get Jellyfin user: {e}")
        return None

    def get_jellyfin_sessions(self):
        try:
            headers = {
                "Authorization": f'MediaBrowser Client="ambilight-cv2", Device="Python", DeviceId="ambilight-cv2-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
            }
            base, host_header = self._jellyfin_base_resolved()
            headers.update(host_header)
            req_start_ts = time.time()
            r = requests.get(f"{base}/Sessions", headers=headers, timeout=5)
            r.raise_for_status()
            sessions = r.json()
            videos = []
            for s in sessions:
                now_playing = s.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    videos.append(s)
            return videos, req_start_ts
        except Exception as e:
            logger.error(f"Failed to get sessions: {e}")
            return [], time.time()

    # --- Player management ---
    def _start_player(self, session_id: str, binary_file: Path, wled_host: str, wled_port: int, start_seconds: float):
        # Create player and launch thread
        player = AmbilightBinaryPlayer(str(binary_file), host=wled_host, port=wled_port)
        self._players[session_id] = player
        t = threading.Thread(target=player.play, kwargs={"start_time": start_seconds}, daemon=True)
        self._player_threads[session_id] = t
        t.start()

    def _stop_player(self, session_id: str):
        p = self._players.pop(session_id, None)
        t = self._player_threads.pop(session_id, None)
        if p:
            try:
                p.stop()
            except Exception:
                pass
        if t:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass

    def _pause_player(self, session_id: str):
        p = self._players.get(session_id)
        if p:
            try:
                p.pause()
            except Exception:
                pass

    def _resume_player(self, session_id: str):
        p = self._players.get(session_id)
        if p:
            try:
                p.resume()
            except Exception:
                pass

    def _resync_player(self, session_id: str, position_seconds: float):
        p = self._players.get(session_id)
        if p:
            try:
                p.resync(position_seconds)
            except Exception:
                pass

    # --- Device selection ---
    def get_wled_target_for_session(self, session: Dict) -> tuple[str, int] | tuple[None, None]:
        # Resolve WLED host to IP (cached) to avoid runtime getaddrinfo errors
        self._resolve_wled_if_needed()
        host = self._wled_resolved_ip or WLED_HOST
        port = WLED_UDP_RAW_PORT
        return host, port

    # --- Library scan (same logic but using cv2 extractor) ---
    def perform_incremental_library_update(self, user_id):
        try:
            logger.info("🔄 Checking for library updates...")
            base, host_header = self._jellyfin_base_resolved()
            hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
            hdrs.update(host_header)
            r = requests.get(f"{base}/Users/{user_id}/Views", headers=hdrs, timeout=15)
            r.raise_for_status()
            libraries = r.json()

            for lib in libraries.get("Items", []):
                lib_id = lib['Id']
                lib_name = lib['Name']
                logger.info(f"📚 Checking library: {lib_name}")

                hdrs2 = {"X-Emby-Token": JELLYFIN_API_KEY}
                hdrs2.update(host_header)
                items_r = requests.get(
                    f"{base}/Users/{user_id}/Items",
                    headers=hdrs2,
                    params={
                        "ParentId": lib_id,
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie,Episode,Video",
                        "Fields": "Path,MediaSources,DateCreated"
                    },
                    timeout=15
                )
                items_r.raise_for_status()
                items = items_r.json().get("Items", [])
                logger.info(f"   Found {len(items)} video items")

                for item in items:
                    item_id = item["Id"]
                    title = item.get("Name", "Unknown")
                    item_type = item.get("Type", "Unknown")
                    jellyfin_date_created = item.get("DateCreated")

                    filepath = "Unknown"
                    if "Path" in item:
                        filepath = item["Path"]
                    elif item.get("MediaSources"):
                        filepath = item["MediaSources"][0].get("Path", "Unknown")

                    self.storage.save_item(item_id, lib_id, title, item_type, filepath, jellyfin_date_created)
        except Exception as e:
            logger.error(f"Error in incremental library update: {e}")
            raise

    def scan_library_for_new_videos(self):
        logger.info("🔄 Starting library scan with CV2 extractor...")
        user_id = None
        try:
            user_id = self.get_jellyfin_user_id()
            if user_id:
                logger.info("✅ Jellyfin server accessible - will update library")
            else:
                logger.warning("⚠️  Jellyfin server not accessible - continuing with offline extraction")
        except Exception as e:
            logger.warning(f"⚠️  Jellyfin server not accessible: {e} - continuing with offline extraction")

        while not shutdown_event.is_set():
            try:
                if user_id:
                    try:
                        self.perform_incremental_library_update(user_id)
                        logger.info("✅ Library updated from Jellyfin")
                    except Exception as e:
                        logger.warning(f"⚠️  Failed to update library from Jellyfin: {e} - continuing with offline extraction")
                        user_id = None
                else:
                    logger.info("🔄 Skipping library update (Jellyfin unavailable) - processing existing videos")

                while not shutdown_event.is_set():
                    stats = self.storage.get_extraction_statistics()
                    logger.info(f"📊 Extraction status: {stats['extracted_videos']}/{stats['total_videos']} ({stats['completion_percentage']:.1f}% complete, {stats['failed_videos']} failed)")
                    if stats['pending_videos'] <= 0:
                        logger.info("✅ No pending videos to extract")
                        break

                    videos_to_process = self.storage.get_videos_needing_extraction(
                        priority_order=EXTRACTION_PRIORITY,
                        limit=EXTRACTION_BATCH_SIZE
                    )
                    if not videos_to_process:
                        logger.info("✅ Extraction queue empty")
                        break

                    logger.info(f"🎬 Processing batch of {len(videos_to_process)} videos...")
                    for item in videos_to_process:
                        if shutdown_event.is_set():
                            break
                        logger.info(f"📁 Extracting: {item['name']}")
                        try:
                            data_dir = Path(AMBILIGHT_DATA_DIR)
                            binary_file = data_dir / "binaries" / f"{item['id']}.bin"
                            src_mtime = Path(item['filepath']).stat().st_mtime if os.path.exists(item['filepath']) else 0
                            dst_mtime = binary_file.stat().st_mtime if binary_file.exists() else 0
                            if binary_file.exists() and dst_mtime >= src_mtime:
                                logger.info(f"⏭️  Skipping (up-to-date): {item['name']}")
                                self.storage.mark_extraction_completed(item['id'])
                            else:
                                ok = extract_frames(item['filepath'], item['id'])
                                if ok:
                                    if binary_file.exists():
                                        logger.info(f"✅ Completed: {item['name']}")
                                    else:
                                        logger.warning(f"⚠️  No binary file created for: {item['name']}")
                                else:
                                    logger.error(f"❌ Extraction failed for: {item['name']} (marked as failed, will not retry)")
                        except Exception as e:
                            logger.error(f"❌ Unexpected error during extraction for {item['name']}: {e}")
                            self.storage.mark_extraction_failed(item['id'], f"Unexpected error: {str(e)}")
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in library scanning: {e}")

            for _ in range(LIBRARY_SCAN_INTERVAL):
                if shutdown_event.is_set():
                    break
                time.sleep(1)

    def monitor_playback(self):
        logger.info("🎬 Starting playback monitoring (CV2 player)...")
        while not shutdown_event.is_set():
            try:
                sessions, sampled_ts = self.get_jellyfin_sessions()
                if sessions:
                    for session in sessions:
                        session_id = session["Id"]
                        item = session["NowPlayingItem"]
                        item_id = item["Id"]
                        play_state = session.get("PlayState", {})
                        is_playing = not play_state.get("IsPaused", True)
                        position_ticks = play_state.get("PositionTicks", 0)
                        position_seconds = position_ticks / 10_000_000 if position_ticks else 0.0

                        prev_is_playing = self.active_sessions.get(session_id, {}).get('is_playing', False)

                        # Ensure binary file exists
                        data_dir = Path(AMBILIGHT_DATA_DIR)
                        binary_file = data_dir / "binaries" / f"{item_id}.bin"
                        if not binary_file.exists():
                            logger.info(f"⏳ Waiting for frame extraction: {item.get('Name', 'Unknown')} ({item_id})")
                            self.active_sessions[session_id] = {
                                'item_id': item_id,
                                'item_name': item.get('Name', 'Unknown'),
                                'is_playing': is_playing,
                                'position_seconds': position_seconds,
                                'last_seen': datetime.now(),
                            }
                            continue

                        host, port = self.get_wled_target_for_session(session)
                        if is_playing:
                            if session_id not in self._players:
                                try:
                                    self._start_player(session_id, binary_file, host, port, position_seconds)
                                    logger.info(f"▶️ Player started for session {session_id} at {position_seconds:.2f}s")
                                except Exception as e:
                                    logger.error(f"Failed to start player: {e}")
                            else:
                                # Sync to new position when it changes significantly
                                prev_pos = self.active_sessions.get(session_id, {}).get('position_seconds', 0.0)
                                if abs(position_seconds - prev_pos) > 0.5:
                                    try:
                                        self._resync_player(session_id, position_seconds)
                                        logger.info(f"🔄 Player resynced to {position_seconds:.2f}s")
                                    except Exception as e:
                                        logger.warning(f"Player resync failed: {e}")
                                # If previously paused, resume
                                if not prev_is_playing:
                                    self._resume_player(session_id)
                        else:
                            # Paused
                            if prev_is_playing:
                                self._pause_player(session_id)

                        self.active_sessions[session_id] = {
                            'item_id': item_id,
                            'item_name': item.get('Name', 'Unknown'),
                            'is_playing': is_playing,
                            'position_seconds': position_seconds,
                            'last_seen': datetime.now(),
                        }
                else:
                    # No sessions — stop players
                    if self.active_sessions:
                        logger.info("⏸️  No active video playback - stopping players")
                        for sid in list(self._players.keys()):
                            self._stop_player(sid)
                        self.active_sessions.clear()

            except Exception as e:
                logger.error(f"Playback monitoring error: {e}")

            time.sleep(PLAYBACK_MONITOR_INTERVAL)

    def start(self):
        logger.info("📁 Starting CV2-Based Ambilight Daemon...")
        # Show storage info
        info = self.storage.get_storage_info()
        stats = self.storage.get_extraction_statistics()
        logger.info("📁 FILE STORAGE STATUS:")
        logger.info(f"   Directory: {info['data_directory']}")
        logger.info(f"   Total storage: {info['total_size_mb']:.1f} MB")
        logger.info(f"   Binary files: {info['binary_file_count']}")
        logger.info(f"   Index files: {info['index_file_count']}")
        logger.info(f"   Videos: {stats['extracted_videos']}/{stats['total_videos']} extracted")
        if stats['failed_videos'] > 0:
            logger.info(f"   Failed: {stats['failed_videos']} videos (marked as failed, will not retry)")
        logger.info(f"   Pending: {stats['pending_videos']} videos need extraction")

        # Threads
        library_thread = None
        if ENABLE_EXTRACTION:
            library_thread = threading.Thread(target=self.scan_library_for_new_videos, daemon=True)
            library_thread.start()
        playback_thread = threading.Thread(target=self.monitor_playback, daemon=True)
        playback_thread.start()

        logger.info("✅ CV2-based daemon started successfully!")
        if not ENABLE_EXTRACTION:
            logger.info("🛑 Extraction disabled via ENABLE_EXTRACTION=false - running playback only")

        try:
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️  Shutdown requested...")
        finally:
            shutdown_event.set()
            for sid in list(self._players.keys()):
                self._stop_player(sid)
            logger.info("🔚 CV2-based daemon stopped")


def signal_handler(signum, frame):
    logger.info(f"📡 Received signal {signum}")
    shutdown_event.set()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("📁 CV2-BASED AMBILIGHT DAEMON")
    print("=" * 50)
    print("   🎥 OpenCV extractor | 🛰️ UDP player (ambilight_play)")
    print("=" * 50)

    daemon = CV2AmbilightDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
