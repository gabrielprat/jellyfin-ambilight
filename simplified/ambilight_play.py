import socket
import struct
import time
import threading
import argparse
import os

MAGIC = b"AMBI"

import struct
import socket
import time

class AmbilightBinaryPlayer:
    def __init__(self, filepath, host="127.0.0.1", port=19446):
        self.filepath = filepath
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._load_file()
        self._stop = False
        self._paused = False
        self._current_frame = 0
        self._start_perf = 0.0  # base perf counter so that target time = _start_perf + ts
        self._paused_video_time = 0.0  # video seconds at the moment of pause
        self._last_payload = None  # last sent UDP payload used for keepalive during pause
        self._last_keepalive_ts = 0.0
        # Lead configuration (seconds): allow lights to run slightly ahead of video
        try:
            self._lead_s = float(os.getenv("AMBILIGHT_LEAD_SECONDS", "0.0"))
        except Exception:
            self._lead_s = 0.0
        print(f"AMBILIGHT_LEAD_SECONDS={self._lead_s:.3f}")

    def _load_file(self):
        with open(self.filepath, "rb") as f:
            if f.read(4) != b"AMBI":
                raise ValueError("Invalid file format")

            self.fps = struct.unpack("<H", f.read(2))[0]
            self.led_count = struct.unpack("<H", f.read(2))[0]
            fmt = struct.unpack("<B", f.read(1))[0]
            self.offset = struct.unpack("<H", f.read(2))[0]
            self.rgbw = (fmt == 1)

            self.frames = []
            frame_size = self.led_count * (4 if self.rgbw else 3) + 8  # 8 bytes timestamp
            while True:
                frame_data = f.read(frame_size)
                if not frame_data:
                    break
                self.frames.append(frame_data)

        print(f"Loaded {len(self.frames)} frames, LEDs={self.led_count}, RGBW={self.rgbw}, FPS={self.fps}")

    def _find_index_for_time(self, target_seconds: float) -> int:
        """Return index of first frame with ts >= target_seconds."""
        best = 0
        for i, frame in enumerate(self.frames):
            ts_us = struct.unpack("<Q", frame[:8])[0]
            if (ts_us / 1_000_000) <= target_seconds:
                best = i
            else:
                return i
        return best

    def _get_payload_at_index(self, index: int) -> bytes | None:
        if 0 <= index < len(self.frames):
            frame = self.frames[index]
            return frame[8:]
        return None

    def play(self, start_time=0.0):
        if start_time is None:
            start_time = 0.0  # fallback to zero
        self._stop = False
        self._paused = False
        self._current_frame = 0
        # Align scheduling base with requested start (+ lead) and skip overdue frames from load time
        base_now = time.perf_counter()
        start_eff = max(0.0, start_time + self._lead_s)
        self._start_perf = base_now - start_eff
        # Account for any load/scheduling delay before we start sending
        effective_video_time = start_eff + (time.perf_counter() - base_now)
        self._current_frame = self._find_index_for_time(effective_video_time)

        while self._current_frame < len(self.frames) and not self._stop:
            if self._paused:
                # Periodic keepalive to prevent WLED from reverting to previous state
                now_paused = time.perf_counter()
                if now_paused - self._last_keepalive_ts >= 0.9:
                    payload_ka = self._last_payload
                    if payload_ka is None:
                        # Build black frame matching LED format
                        led_bytes = self.led_count * (4 if self.rgbw else 3)
                        payload_ka = bytes([0] * led_bytes)
                    try:
                        self.sock.sendto(payload_ka, (self.host, self.port))
                    except Exception:
                        pass
                    self._last_keepalive_ts = now_paused
                time.sleep(0.05)
                continue

            frame_data = self.frames[self._current_frame]
            timestamp_us = struct.unpack("<Q", frame_data[:8])[0]
            payload = frame_data[8:]

            # Wait until correct timestamp
            now = time.perf_counter()
            target_time = self._start_perf + (timestamp_us / 1_000_000)
            sleep_time = target_time - now
            if sleep_time > 0:
                time.sleep(sleep_time)

            self.sock.sendto(payload, (self.host, self.port))
            self._last_payload = payload
            self._current_frame += 1

        print("✅ Playback finished")

    def pause(self):
        if not self._paused:
            # Capture current virtual video time so we can resume without backlog
            now = time.perf_counter()
            self._paused_video_time = max(0.0, now - self._start_perf)
            # Snap to the nearest frame at pause time and display it once
            target_idx = self._find_index_for_time(self._paused_video_time)
            self._current_frame = target_idx
            payload = self._get_payload_at_index(target_idx)
            if payload:
                try:
                    self.sock.sendto(payload, (self.host, self.port))
                except Exception:
                    pass
                self._last_payload = payload
                self._last_keepalive_ts = time.perf_counter()
            self._paused = True

    def resume(self):
        if self._paused:
            # Align scheduling base so next frames schedule from paused video time
            self._start_perf = time.perf_counter() - self._paused_video_time
            self._paused = False

    def stop(self):
        self._stop = True

    def resync(self, timestamp_sec):
        """Jump to timestamp in seconds"""
        # Apply lead to effective timestamp
        effective_ts = max(0.0, float(timestamp_sec) + self._lead_s)
        for i, frame in enumerate(self.frames):
            ts_us = struct.unpack("<Q", frame[:8])[0]
            if ts_us / 1_000_000 >= effective_ts:
                self._current_frame = i
                # Reset scheduling base so next frames align to wall clock smoothly
                self._start_perf = time.perf_counter() - effective_ts
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play Ambilight binary to WLED over UDP")
    parser.add_argument("file", help="Path to ambilight .bin file")
    parser.add_argument("--host", required=True, help="WLED host/IP")
    parser.add_argument("--port", type=int, default=21324, help="WLED UDP port")
    parser.add_argument("--start", type=float, help="Start time in seconds", default=None)

    args = parser.parse_args()

    player = AmbilightBinaryPlayer(args.file, args.host, args.port)
    player.play(args.start)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        player.stop()
