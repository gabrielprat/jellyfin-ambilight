#!/usr/bin/env python3
"""
Ambilight Player Daemon (UDP)
=============================

Monitors Jellyfin sessions and plays AMBI binaries via UDP using
simplified/ambilight_play.py, synchronizing playback with the current
video position and detecting seek, pause, resume, and desync events.
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
from pathlib import Path
from typing import Dict

# Local paths
sys.path.append('/app')
sys.path.append('/app/storage')

from storage.storage import FileBasedStorage  # noqa: E402
from simplified.ambilight_play import AmbilightBinaryPlayer  # noqa: E402


JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_RAW_PORT = int(os.getenv('WLED_UDP_RAW_PORT', '19446'))
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")
PLAYBACK_MONITOR_INTERVAL = float(os.getenv('PLAYBACK_MONITOR_INTERVAL', '0.2'))
AMBILIGHT_DNS_TTL_SECONDS = int(os.getenv('AMBILIGHT_DNS_TTL_SECONDS', '3600'))
AMBILIGHT_DISABLE_DNS_RESOLVE = os.getenv('AMBILIGHT_DISABLE_DNS_RESOLVE', 'false').lower() == 'true'
JELLYFIN_DEVICE_FILTER = os.getenv("JELLYFIN_DEVICE_FILTER", "").strip().lower()
# Device → WLED mapping
DEVICE_MATCH_FIELD = os.getenv("DEVICE_MATCH_FIELD", "DeviceName").strip()

shutdown_event = threading.Event()
logger = logging.getLogger(__name__)


def fmt_ts(seconds: float) -> str:
    """Format seconds as hh:mm:ss.mmm"""
    msec = int((seconds % 1) * 1000)
    return time.strftime("%H:%M:%S", time.gmtime(seconds)) + f".{msec:03d}"


class PlayerDaemon:
    def __init__(self):
        self.storage = FileBasedStorage(AMBILIGHT_DATA_DIR)
        self._jellyfin_parsed = urlparse(JELLYFIN_BASE_URL) if JELLYFIN_BASE_URL else None
        self._jellyfin_resolved_ip = None
        self._jellyfin_last_resolve_ts = 0.0
        self._wled_resolved_ip = None
        self._wled_last_resolve_ts = 0.0
        self._players: Dict[str, AmbilightBinaryPlayer] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._session_state: Dict[str, Dict] = {}
        # Parse WLED_DEVICE_* mappings once at startup
        self._device_map: Dict[str, tuple[str, int]] = self._parse_device_mappings()
        # Track items we already warned about missing binary
        self._no_binary_notified: set[str] = set()

    # DNS helpers
    def _resolve_host_cached(self, host: str, udp: bool = False) -> str | None:
        if AMBILIGHT_DISABLE_DNS_RESOLVE:
            return None
        family = socket.AF_INET
        typ = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
        ttl = AMBILIGHT_DNS_TTL_SECONDS
        now = time.time()
        cache_ip = self._wled_resolved_ip if udp else self._jellyfin_resolved_ip
        cache_ts = self._wled_last_resolve_ts if udp else self._jellyfin_last_resolve_ts
        if ttl != 0 and cache_ip and (now - cache_ts) < ttl:
            return cache_ip
        try:
            infos = socket.getaddrinfo(host, None, family=family, type=typ)
            if infos:
                ip = infos[0][4][0]
                if udp:
                    self._wled_resolved_ip = ip
                    self._wled_last_resolve_ts = now
                else:
                    self._jellyfin_resolved_ip = ip
                    self._jellyfin_last_resolve_ts = now
                return ip
        except Exception as e:
            logger.warning(f"DNS resolve failed for {host}: {e}")
        return None

    def _jellyfin_base(self) -> tuple[str, dict]:
        if not self._jellyfin_parsed:
            return JELLYFIN_BASE_URL, {}
        ip = self._resolve_host_cached(self._jellyfin_parsed.hostname, udp=False)
        host = ip or self._jellyfin_parsed.hostname
        port = f":{self._jellyfin_parsed.port}" if self._jellyfin_parsed.port else ''
        base = f"{self._jellyfin_parsed.scheme}://{host}{port}"
        return base, {"Host": self._jellyfin_parsed.netloc}

    def _parse_device_mappings(self) -> Dict[str, tuple[str, int]]:
        """Parse env vars WLED_DEVICE_* into mapping of identifier -> (host, port)."""
        mappings: Dict[str, tuple[str, int]] = {}
        for key, value in os.environ.items():
            if not key.startswith("WLED_DEVICE_"):
                continue
            ident = key[len("WLED_DEVICE_"):].strip().lower()
            if not ident:
                continue
            host = value.strip()
            port = WLED_UDP_RAW_PORT
            if ":" in host:
                h, p = host.rsplit(":", 1)
                host = h.strip()
                try:
                    port = int(p)
                except ValueError:
                    port = WLED_UDP_RAW_PORT
            mappings[ident] = (host, port)
        return mappings

    def _device_match_value(self, session: Dict) -> str:
        """Extract the field used to match device mappings from a Jellyfin session."""
        try:
            value = session.get(DEVICE_MATCH_FIELD, "")
            if isinstance(value, str):
                return value
        except Exception:
            pass
        # Fallback to DeviceName
        return session.get("DeviceName", "")

    def _target_for_session(self, session: Dict) -> tuple[str, int] | None:
        """
        Determine WLED target for this session using WLED_DEVICE_* mappings.
        Returns (resolved_ip_or_hostname, port) or None if no mapping applies.
        """
        device_value = self._device_match_value(session).strip().lower()
        if not device_value:
            return None
        # Exact match on identifier within the device value (substring match)
        for ident, (host, port) in self._device_map.items():
            if ident in device_value:
                # Resolve to IP (use UDP family) and return IP if available
                ip = self._resolve_host_cached(host, udp=True)
                return (ip or host, port)
        return None

    def get_sessions(self):
        try:
            base, host_header = self._jellyfin_base()
            headers = {
                "Authorization": f'MediaBrowser Client="ambilight-player", Device="Python", DeviceId="ambilight-player-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
            }
            headers.update(host_header)
            r = requests.get(f"{base}/Sessions", headers=headers, timeout=5)
            r.raise_for_status()
            sessions = r.json()
            videos = []
            for s in sessions:
                device_name = s.get("DeviceName", "").lower()
                if JELLYFIN_DEVICE_FILTER and JELLYFIN_DEVICE_FILTER not in device_name:
                    logger.debug(f"🚫 Skipping session from device '{device_name}'")
                    continue
                now_playing = s.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    videos.append(s)
            return videos
        except Exception as e:
            logger.error(f"get_sessions failed: {e}")
            return []

    def _start_player(self, session_id: str, binary_file: Path, host: str, port: int, start_seconds: float):
        p = AmbilightBinaryPlayer(str(binary_file), host=host, port=port)
        self._players[session_id] = p
        t = threading.Thread(target=p.play, kwargs={"start_time": start_seconds}, daemon=True)
        self._threads[session_id] = t
        t.start()
        logger.info(f"▶️  Player started for session {session_id} at {fmt_ts(start_seconds)} (from binary {binary_file.name})")

    def _stop_player(self, session_id: str):
        p = self._players.pop(session_id, None)
        t = self._threads.pop(session_id, None)
        if p:
            try:
                logger.info(f"🛑 Stopping player for session {session_id}")
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
            logger.info(f"⏸️  Pausing player for session {session_id}")
            try:
                p.pause()
            except Exception:
                pass

    def _resume_player(self, session_id: str):
        p = self._players.get(session_id)
        if p:
            logger.info(f"▶️  Resuming player for session {session_id}")
            try:
                p.resume()
            except Exception:
                pass

    def _resync_player(self, session_id: str, position_seconds: float):
        p = self._players.get(session_id)
        if p:
            try:
                logger.info(f"🔄 Resyncing player for session {session_id} → {fmt_ts(position_seconds)}")
                p.resync(position_seconds)
            except Exception as e:
                logger.warning(f"Player resync failed: {e}")

    def monitor(self):
        logger.info("🎬 Starting player monitoring...")
        while not shutdown_event.is_set():
            try:
                sessions = self.get_sessions()
                if sessions:
                    for s in sessions:
                        sid = s["Id"]
                        item = s["NowPlayingItem"]
                        item_id = item["Id"]
                        item_name = item.get("Name", "Unknown")
                        is_playing = not s.get("PlayState", {}).get("IsPaused", True)
                        ticks = s.get("PlayState", {}).get("PositionTicks", 0)
                        pos_s = (ticks / 10_000_000) if ticks else 0.0
                        prev_state = self._session_state.get(sid, {})
                        prev_is_playing = prev_state.get('is_playing', False)
                        prev_pos = prev_state.get('last_pos', 0.0)

                        # Determine target strictly from WLED_DEVICE_* mappings
                        target = self._target_for_session(s)
                        if not target:
                            logger.debug("🚫 No WLED device mapping for this session; skipping ambilight.")
                            # If a player exists from earlier, stop it
                            if sid in self._players:
                                self._stop_player(sid)
                            continue
                        host, port = target

                        # Only check binary availability if a target exists
                        data_dir = Path(AMBILIGHT_DATA_DIR)
                        binary_file = data_dir / "binaries" / f"{item_id}.bin"
                        if not binary_file.exists():
                            # Log only once per item id
                            if item_id not in self._no_binary_notified:
                                logger.info(f"no binary data for: {item_name} ({item_id})")
                                self._no_binary_notified.add(item_id)
                            continue
                        else:
                            # If binary now exists, clear any previous notification so future items can log again
                            if item_id in self._no_binary_notified:
                                self._no_binary_notified.discard(item_id)

                        # Detect large seek jumps
                        if abs(pos_s - prev_pos) > 2.0:
                            logger.info(f"⏩  Session {sid} seek detected: {fmt_ts(prev_pos)} → {fmt_ts(pos_s)} (Δ{pos_s - prev_pos:+.1f}s)")

                        if is_playing:
                            if sid not in self._players:
                                try:
                                    self._start_player(sid, binary_file, host, port, pos_s)
                                except Exception as e:
                                    logger.error(f"Failed to start player: {e}")
                            else:
                                # Handle pause/resume transitions
                                if not prev_is_playing:
                                    self._resume_player(sid)
                                # Handle desync correction
                                drift = pos_s - prev_pos
                                if abs(drift) > 0.10:
                                    logger.info(f"🎯 Drift check: video={fmt_ts(pos_s)} prev={fmt_ts(prev_pos)} drift={drift:+.3f}s")
                                    if abs(drift) > 0.2:
                                        self._resync_player(sid, pos_s)
                        else:
                            if sid in self._players:
                                self._pause_player(sid)

                        # Save current state
                        self._session_state[sid] = {
                            'is_playing': is_playing,
                            'last_pos': pos_s,
                            'item_id': item_id,
                        }
                else:
                    if self._players:
                        logger.info("⏹️  No active sessions — stopping players")
                        for sid in list(self._players.keys()):
                            self._stop_player(sid)
            except Exception as e:
                logger.error(f"Player loop error: {e}")
            time.sleep(PLAYBACK_MONITOR_INTERVAL)

    def start(self):
        logger.info("✅ Player daemon started")
        t = threading.Thread(target=self.monitor, daemon=True)
        t.start()
        try:
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️  Shutdown requested...")
        finally:
            shutdown_event.set()
            for sid in list(self._players.keys()):
                self._stop_player(sid)
            logger.info("🔚 Player daemon stopped")


def signal_handler(signum, frame):
    logger.info(f"📡 Received signal {signum}")
    shutdown_event.set()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print("📡 AMBILIGHT PLAYER DAEMON")
    print("=" * 60)
    d = PlayerDaemon()
    d.start()


if __name__ == "__main__":
    main()
