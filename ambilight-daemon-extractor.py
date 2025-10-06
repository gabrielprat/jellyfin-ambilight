#!/usr/bin/env python3
"""
Ambilight Extractor Daemon (CV2)
================================

Runs the library scan and frame extraction using simplified/extractor_cv2.py
and stores AMBI binaries under $AMBILIGHT_DATA_DIR/binaries.
"""

import os
import sys
import time
import threading
import signal
import logging
import requests
from urllib.parse import urlparse
from pathlib import Path

from storage.storage import FileBasedStorage

# Local paths
sys.path.append('/app')
sys.path.append('/app/storage')

from simplified.extractor_cv2 import extract_frames  # noqa: E402


# Config
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")

LIBRARY_SCAN_INTERVAL = int(os.getenv('LIBRARY_SCAN_INTERVAL', '3600'))
EXTRACTION_PRIORITY = os.getenv('EXTRACTION_PRIORITY', 'newest_first')
EXTRACTION_BATCH_SIZE = int(os.getenv('EXTRACTION_BATCH_SIZE', '5'))
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")

shutdown_event = threading.Event()
logger = logging.getLogger(__name__)


class ExtractorDaemon:
    def __init__(self):
        self.storage = FileBasedStorage(AMBILIGHT_DATA_DIR)
        self._jellyfin_parsed = urlparse(JELLYFIN_BASE_URL) if JELLYFIN_BASE_URL else None
        self._jellyfin_resolved_ip = None
        self._jellyfin_last_resolve_ts = 0.0

    def _resolve_jellyfin_if_needed(self, force: bool = False):
        if not self._jellyfin_parsed:
            return
        ttl = int(os.getenv('AMBILIGHT_DNS_TTL_SECONDS', '3600'))
        disable = os.getenv('AMBILIGHT_DISABLE_DNS_RESOLVE', 'false').lower() == 'true'
        if disable:
            self._jellyfin_resolved_ip = None
            return
        now = time.time()
        if ttl == 0:
            force = True
        if not force and self._jellyfin_resolved_ip and (now - self._jellyfin_last_resolve_ts) < ttl:
            return
        try:
            import threading as _t, queue as _q, socket
            rq, eq = _q.Queue(), _q.Queue()
            def worker():
                try:
                    infos = socket.getaddrinfo(self._jellyfin_parsed.hostname, None)
                    if infos:
                        rq.put(infos[0][4][0])
                except Exception as e:
                    eq.put(e)
            t = _t.Thread(target=worker, daemon=True)
            t.start(); t.join(timeout=5.0)
            if t.is_alive():
                logger.warning(f"DNS resolution timeout for {self._jellyfin_parsed.hostname}")
                return
            if not eq.empty():
                raise eq.get()
            if not rq.empty():
                self._jellyfin_resolved_ip = rq.get()
                self._jellyfin_last_resolve_ts = now
        except Exception as e:
            logger.warning(f"DNS resolve failed for {self._jellyfin_parsed.hostname}: {e}")

    def _jellyfin_base_resolved(self) -> tuple[str, dict]:
        if not self._jellyfin_parsed:
            return JELLYFIN_BASE_URL, {}
        self._resolve_jellyfin_if_needed()
        host = self._jellyfin_resolved_ip or self._jellyfin_parsed.hostname
        port = f":{self._jellyfin_parsed.port}" if self._jellyfin_parsed.port else ''
        base = f"{self._jellyfin_parsed.scheme}://{host}{port}"
        return base, {"Host": self._jellyfin_parsed.netloc}

    def get_jellyfin_user_id(self):
        try:
            base, host_header = self._jellyfin_base_resolved()
            hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
            hdrs.update(host_header)
            r = requests.get(f"{base}/Users", headers=hdrs, timeout=10)
            r.raise_for_status()
            users = r.json()
            return users[0]["Id"] if users else None
        except Exception as e:
            logger.warning(f"get_jellyfin_user_id failed: {e}")
            return None

    def perform_incremental_library_update(self, user_id):
        base, host_header = self._jellyfin_base_resolved()
        hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
        hdrs.update(host_header)
        r = requests.get(f"{base}/Users/{user_id}/Views", headers=hdrs, timeout=15)
        r.raise_for_status()
        libraries = r.json()
        for lib in libraries.get("Items", []):
            lib_id = lib['Id']
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
            for item in items:
                item_id = item["Id"]
                title = item.get("Name", "Unknown")
                item_type = item.get("Type", "Unknown")
                created = item.get("DateCreated")
                filepath = item.get("Path") or (item.get("MediaSources") or [{}])[0].get("Path", "Unknown")
                self.storage.save_item(item_id, lib_id, title, item_type, filepath, created)

    def scan_library_for_new_videos(self):
        logger.info("🔄 Starting library scan (extractor)...")
        user_id = None
        try:
            user_id = self.get_jellyfin_user_id()
        except Exception:
            user_id = None
        while not shutdown_event.is_set():
            try:
                if user_id:
                    try:
                        self.perform_incremental_library_update(user_id)
                    except Exception as e:
                        logger.warning(f"Library update failed: {e}")
                        user_id = None
                stats = self.storage.get_extraction_statistics()
                logger.info(f"📊 Extraction status: {stats['extracted_videos']}/{stats['total_videos']} ({stats['completion_percentage']:.1f}% complete, {stats['failed_videos']} failed)")
                if stats['pending_videos'] <= 0:
                    logger.info("✅ No pending videos to extract")
                else:
                    videos = self.storage.get_videos_needing_extraction(priority_order=EXTRACTION_PRIORITY, limit=EXTRACTION_BATCH_SIZE)
                    logger.info(f"🎬 Processing batch of {len(videos)} videos...")
                    for item in videos:
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
                                    logger.info(f"✅ Completed: {item['name']}")
                                else:
                                    logger.error(f"❌ Extraction failed for: {item['name']}")
                        except Exception as e:
                            logger.error(f"❌ Unexpected error during extraction for {item['name']}: {e}")
                            self.storage.mark_extraction_failed(item['id'], f"Unexpected error: {str(e)}")
            except Exception as e:
                logger.error(f"Extractor loop error: {e}")
            for _ in range(LIBRARY_SCAN_INTERVAL):
                if shutdown_event.is_set():
                    break
                time.sleep(1)

    def start(self):
        info = self.storage.get_storage_info()
        stats = self.storage.get_extraction_statistics()
        logger.info("📁 FILE STORAGE STATUS:")
        logger.info(f"   Directory: {info['data_directory']}")
        logger.info(f"   Binaries: {info['binary_file_count']}")
        logger.info(f"   Pending: {stats['pending_videos']}")
        t = threading.Thread(target=self.scan_library_for_new_videos, daemon=True)
        t.start()
        logger.info("✅ Extractor daemon started")
        try:
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️  Shutdown requested...")
        finally:
            shutdown_event.set()
            logger.info("🔚 Extractor daemon stopped")


def signal_handler(signum, frame):
    logger.info(f"📡 Received signal {signum}")
    shutdown_event.set()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print("📁 AMBILIGHT EXTRACTOR (CV2)")
    print("=" * 50)
    d = ExtractorDaemon()
    d.start()


if __name__ == "__main__":
    main()
