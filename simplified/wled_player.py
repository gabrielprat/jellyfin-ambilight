import os
import logging
import socket
import struct
import time
import requests
import numpy as np  # noqa: F401  (kept for backward compat; may be used by callers)
import sys  # noqa: F401
import json  # noqa: F401
import threading

# WLED target
WLED_HOST = os.getenv("WLED_HOST", "wled-ambilight-lgc1.lan")
# Always use UDP RAW port for broadcasting
WLED_PORT = int(os.getenv("WLED_UDP_RAW_PORT", os.getenv("WLED_PORT", "19446")))
AMBILIGHT_BROADCAST_DEBUG = os.getenv("AMBILIGHT_BROADCAST_DEBUG", "false").lower() == "true"
AMBILIGHT_DNS_TTL_SECONDS = int(os.getenv("AMBILIGHT_DNS_TTL_SECONDS", "3600"))
AMBILIGHT_DISABLE_DNS_RESOLVE = os.getenv("AMBILIGHT_DISABLE_DNS_RESOLVE", "false").lower() == "true"
AMBILIGHT_SYNC_LEAD_SECONDS = float(os.getenv("AMBILIGHT_SYNC_LEAD_SECONDS", "-0.05"))  # negative to lead lights ahead of video by default
AMBILIGHT_PROFILE = os.getenv("AMBILIGHT_PROFILE", "false").lower() == "true"
AMBILIGHT_MAX_CATCHUP_LAG_SECONDS = float(os.getenv("AMBILIGHT_MAX_CATCHUP_LAG_SECONDS", "0.100"))
AMBILIGHT_CATCHUP_MODE = os.getenv("AMBILIGHT_CATCHUP_MODE", "last_only").lower()  # last_only | burst
AMBILIGHT_MAX_BURST_FRAMES = int(os.getenv("AMBILIGHT_MAX_BURST_FRAMES", "10"))


logger = logging.getLogger(__name__)

def get_wled_state():
    try:
        resp = requests.get(f"http://{WLED_HOST}/json/state", timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print("⚠️ Could not fetch WLED state:", e)
    return None

def restore_wled_state(state):
    if state:
        try:
            requests.post(f"http://{WLED_HOST}/json/state", json=state, timeout=3)
            print("✅ Restored previous WLED state.")
        except Exception as e:
            print("⚠️ Could not restore WLED state:", e)


class AmbilightBroadcaster:
    """Stateful UDP broadcaster with pause/resume and time sync."""
    def __init__(self, filename: str, wled_host: str | None = None, wled_port: int | None = None):
        self.filename = filename
        self._f = None
        self._index = []  # list of (timestamp: float, offset: int, payload_len: int)
        self._fps = 0
        self._led_count = 0
        self._rgbw = False
        self._offset = 0
        self._sock = None
        self._thread = None
        self._running = False
        self._paused = False
        self._lock = threading.RLock()
        self._wall_start = 0.0         # wall-clock time when playback (unpaused) started
        self._video_base = 0.0         # video time at _wall_start
        self._current_index = 0
        self._prev_wled_state = None
        # Per-session WLED target (fallback to globals)
        self._host = wled_host or WLED_HOST
        self._port = int(wled_port or WLED_PORT)
        self._last_send_ts = 0.0
        # DNS cache per broadcaster
        self._resolved_ip = None
        self._last_resolve_ts = 0.0
        # Profiling metrics
        self._frames_sent = 0
        self._cumulative_read_s = 0.0
        self._cumulative_send_s = 0.0
        self._max_lag_s = 0.0
        self._last_lag_s = 0.0
        self._last_profile_log = 0.0

    def _read_header(self):
        magic = self._f.read(4)
        if magic != b"AMBI":
            raise ValueError("Invalid file format")
        self._fps = struct.unpack("<H", self._f.read(2))[0]
        self._led_count = struct.unpack("<H", self._f.read(2))[0]
        fmt = struct.unpack("<B", self._f.read(1))[0]
        self._offset = struct.unpack("<H", self._f.read(2))[0]
        self._rgbw = (fmt == 1)

    def _build_index(self):
        self._index.clear()

        # After header, frames repeat: [timestamp:double][len:uint16][payload:bytes]
        while True:
            header = self._f.read(10)
            if not header or len(header) < 10:
                break
            ts, payload_len = struct.unpack("<dH", header)
            payload_offset = self._f.tell()

            self._f.seek(payload_len, 1)

            self._index.append((ts, payload_offset, payload_len))

    def load(self):
        with self._lock:
            if self._f is not None:
                return
            self._f = open(self.filename, "rb")
            self._read_header()
            self._build_index()

    def _ensure_socket(self):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self, start_seconds: float = 0.0, source_wall_ts: float | None = None):
        """Start broadcasting from given video time (seconds)."""
        self.load()
        with self._lock:
            self._ensure_socket()
            # Resolve target host to IP (cached)
            self._resolve_host_if_needed(force=True)
            # Best-effort: ensure device is on
            try:
                target = self._resolved_ip or self._host
                requests.post(f"http://{target}/json/state", json={"on": True}, timeout=3)
            except Exception:
                pass
            # Position to requested time
            # Apply sync compensation: include sampling age and lead offset
            now_ts = time.time()
            sample_age = 0.0
            if source_wall_ts is not None and source_wall_ts <= now_ts:
                sample_age = max(0.0, now_ts - source_wall_ts)
            compensation = AMBILIGHT_SYNC_LEAD_SECONDS
            effective_start = max(0.0, start_seconds + sample_age + compensation)
            self._seek_locked(effective_start)
            self._running = True
            self._paused = False
            self._wall_start = time.time()
            self._video_base = effective_start
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.info(f"WLED broadcaster start @{effective_start:.2f}s (src {start_seconds:.2f}s, age {sample_age:.3f}s, lead {compensation:+.2f}s) → {self._host}:{self._port}")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()

    def pause(self):
        with self._lock:
            if not self._running or self._paused:
                return
            # Calculate accumulated video time at pause
            elapsed = time.time() - self._wall_start
            self._video_base = self._video_base + max(0.0, elapsed)
            self._paused = True
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.info("WLED broadcaster paused")

    def resume(self):
        with self._lock:
            if not self._running or not self._paused:
                return
            self._paused = False
            self._wall_start = time.time()
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.info("WLED broadcaster resumed")

    def stop(self):
        with self._lock:
            self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._sock is not None:
            try:
                # Optionally restore state (disabled or no-op)
                if self._prev_wled_state:
                    try:
                        requests.post(f"http://{self._host}/json/state", json=self._prev_wled_state, timeout=3)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None
        if self._f is not None:
            try:
                self._f.close()
            finally:
                self._f = None
        if AMBILIGHT_BROADCAST_DEBUG:
            logger.info("WLED broadcaster stopped")

    def sync_to(self, video_seconds: float, source_wall_ts: float | None = None):
        """Hard-sync playback to a given video timestamp (seconds)."""
        with self._lock:
            now_ts = time.time()
            sample_age = 0.0
            if source_wall_ts is not None and source_wall_ts <= now_ts:
                sample_age = max(0.0, now_ts - source_wall_ts)
            effective = max(0.0, video_seconds + sample_age + AMBILIGHT_SYNC_LEAD_SECONDS)
            self._seek_locked(effective)
            # Reset wall clock so next frame scheduling aligns
            self._video_base = effective
            self._wall_start = time.time()
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.info(f"WLED broadcaster sync_to @{effective:.2f}s (src {video_seconds:.2f}s, age {sample_age:.3f}s, lead {AMBILIGHT_SYNC_LEAD_SECONDS:+.2f}s)")

    # Backward-compat alias
    def seek_to(self, video_seconds: float):
        self.sync_to(video_seconds)

    def _seek_locked(self, video_seconds: float):
        # Find nearest frame index
        if not self._index:
            self._current_index = 0
            return
        lo, hi = 0, len(self._index) - 1
        best = 0
        target = video_seconds
        while lo <= hi:
            mid = (lo + hi) // 2
            ts = self._index[mid][0]
            if ts <= target:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        self._current_index = best

    def _find_index_for_time(self, video_seconds: float) -> int:
        if not self._index:
            return 0
        lo, hi = 0, len(self._index) - 1
        best = 0
        target = video_seconds
        while lo <= hi:
            mid = (lo + hi) // 2
            ts = self._index[mid][0]
            if ts <= target:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _run_loop(self):
        try:
            while True:
                with self._lock:
                    if not self._running:
                        break
                    if self._paused:
                        # Sleep briefly while paused
                        sleep_time = 0.02
                    else:
                        now = time.time()
                        virtual_t = self._video_base + (now - self._wall_start)
                        # Catch-up strategy if we are behind
                        next_ts = self._index[self._current_index][0] if self._current_index < len(self._index) else float('inf')
                        lag_s = max(0.0, virtual_t - next_ts)
                        self._last_lag_s = lag_s
                        if lag_s > self._max_lag_s:
                            self._max_lag_s = lag_s

                        if lag_s > AMBILIGHT_MAX_CATCHUP_LAG_SECONDS and AMBILIGHT_CATCHUP_MODE == "last_only":
                            # Jump to last frame <= virtual_t and send only that frame
                            target_index = self._find_index_for_time(virtual_t)
                            if target_index >= self._current_index:
                                self._current_index = target_index
                                _, payload_offset, payload_len = self._index[self._current_index]
                                t_read0 = time.time()

                                # Read payload from file
                                self._f.seek(payload_offset)
                                payload = self._f.read(payload_len)
                                t_read1 = time.time()

                                if payload:
                                    self._resolve_host_if_needed()
                                    target = self._resolved_ip or self._host
                                    t_send0 = time.time()
                                    self._sock.sendto(payload, (target, self._port))
                                    t_send1 = time.time()
                                    self._last_send_ts = t_send1
                                    self._frames_sent += 1
                                    self._cumulative_read_s += (t_read1 - t_read0)
                                    self._cumulative_send_s += (t_send1 - t_send0)
                                self._current_index += 1
                        else:
                            # Send frames up to virtual_t; optionally limit burst size
                            frames_sent_this_cycle = 0
                            max_frames = AMBILIGHT_MAX_BURST_FRAMES if AMBILIGHT_CATCHUP_MODE == "burst" else float('inf')
                            while (self._current_index < len(self._index)
                                   and self._index[self._current_index][0] <= virtual_t
                                   and frames_sent_this_cycle < max_frames):
                                _, payload_offset, payload_len = self._index[self._current_index]
                                t_read0 = time.time()

                                # Read payload from file
                                self._f.seek(payload_offset)
                                payload = self._f.read(payload_len)
                                t_read1 = time.time()

                                if payload:
                                    # Resolve periodically
                                    self._resolve_host_if_needed()
                                    target = self._resolved_ip or self._host
                                    t_send0 = time.time()
                                    self._sock.sendto(payload, (target, self._port))
                                    t_send1 = time.time()
                                    self._last_send_ts = t_send1
                                    self._frames_sent += 1
                                    self._cumulative_read_s += (t_read1 - t_read0)
                                    self._cumulative_send_s += (t_send1 - t_send0)

                                self._current_index += 1
                                frames_sent_this_cycle += 1
                        # Choose a small sleep to maintain responsiveness
                        sleep_time = 1.0 / max(20.0, float(self._fps) or 20.0)
                if AMBILIGHT_BROADCAST_DEBUG:
                    try:
                        # Light periodic heartbeat every ~1s
                        if int(time.time()) % 1 == 0:
                            logger.debug(f"WLED hb: idx={self._current_index}/{len(self._index)} paused={self._paused} last_send={(time.time()-self._last_send_ts):.2f}s lag={self._last_lag_s*1000:.0f}ms")
                    except Exception:
                        pass
                time.sleep(sleep_time)
        except Exception:
            # Ensure we do not crash the process; best-effort broadcaster
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.exception("WLED broadcaster loop error")
        finally:
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.info("WLED broadcaster loop exit")

        # Periodic profiling logs
        if AMBILIGHT_PROFILE:
            now2 = time.time()
            if now2 - self._last_profile_log >= 1.0:
                self._last_profile_log = now2
                avg_read_ms = (self._cumulative_read_s / max(1, self._frames_sent)) * 1000.0
                avg_send_ms = (self._cumulative_send_s / max(1, self._frames_sent)) * 1000.0
                logger.info(
                    f"WLED profile: frames={self._frames_sent} avg_read={avg_read_ms:.2f}ms avg_send={avg_send_ms:.2f}ms max_lag={self._max_lag_s*1000:.0f}ms"
                )

    def is_thread_alive(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    def get_status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "paused": self._paused,
                "current_index": self._current_index,
                "total_frames": len(self._index),
                "last_send_age_s": (time.time() - self._last_send_ts) if self._last_send_ts else None,
                "host": self._host,
                "resolved_ip": self._resolved_ip,
                "port": self._port,
                "frames_sent": self._frames_sent,
                "avg_read_ms": (self._cumulative_read_s / max(1, self._frames_sent)) * 1000.0,
                "avg_send_ms": (self._cumulative_send_s / max(1, self._frames_sent)) * 1000.0,
                "max_lag_ms": self._max_lag_s * 1000.0,
                "last_lag_ms": self._last_lag_s * 1000.0,
            }

    def _resolve_host_if_needed(self, force: bool = False):
        # If DNS resolution is disabled, always use hostname
        if AMBILIGHT_DISABLE_DNS_RESOLVE:
            self._resolved_ip = None
            return

        now = time.time()
        # If TTL is 0, always resolve fresh
        if AMBILIGHT_DNS_TTL_SECONDS == 0:
            force = True
        if not force and self._resolved_ip and (now - self._last_resolve_ts) < AMBILIGHT_DNS_TTL_SECONDS:
            return
        try:
            # Use thread-safe timeout for DNS resolution
            import threading
            import queue

            result_queue = queue.Queue()
            exception_queue = queue.Queue()

            def dns_worker():
                try:
                    # Prefer IPv4
                    infos = socket.getaddrinfo(self._host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM)
                    if infos:
                        ip = infos[0][4][0]
                        result_queue.put(ip)
                except Exception as e:
                    exception_queue.put(e)

            # Start DNS resolution in a separate thread
            dns_thread = threading.Thread(target=dns_worker, daemon=True)
            dns_thread.start()

            # Wait for result with timeout
            dns_thread.join(timeout=3.0)

            if dns_thread.is_alive():
                # Timeout occurred
                if AMBILIGHT_BROADCAST_DEBUG:
                    logger.warning(f"DNS resolution timeout for {self._host}")
                return

            # Check for results
            if not exception_queue.empty():
                raise exception_queue.get()

            if not result_queue.empty():
                ip = result_queue.get()
                self._resolved_ip = ip
                self._last_resolve_ts = now
                if AMBILIGHT_BROADCAST_DEBUG:
                    logger.info(f"DNS resolved {self._host} → {ip}")

        except Exception as e:
            if AMBILIGHT_BROADCAST_DEBUG:
                logger.warning(f"DNS resolve failed for {self._host}: {e}")


def create_broadcaster(filename: str, wled_host: str | None = None, wled_port: int | None = None) -> AmbilightBroadcaster:
    """Factory to create a stateful broadcaster for the given file."""
    return AmbilightBroadcaster(filename, wled_host=wled_host, wled_port=wled_port)


def pause_broadcast(broadcaster: AmbilightBroadcaster):
    broadcaster.pause()


def resume_broadcast(broadcaster: AmbilightBroadcaster):
    broadcaster.resume()


def sync_broadcast_to(broadcaster: AmbilightBroadcaster, video_seconds: float, source_wall_ts: float | None = None):
    broadcaster.sync_to(video_seconds, source_wall_ts)

if __name__ == "__main__":
    print("This module is intended to be used via the broadcaster API, not as a CLI.")
