import socket
import struct
import time
import threading
import argparse

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

    def play(self, start_time=0.0):
        if start_time is None:
            start_time = 0.0  # fallback to zero
        self._stop = False
        self._paused = False
        self._current_frame = 0

        start_perf = time.perf_counter() - start_time

        while self._current_frame < len(self.frames) and not self._stop:
            if self._paused:
                time.sleep(0.05)
                continue

            frame_data = self.frames[self._current_frame]
            timestamp_us = struct.unpack("<Q", frame_data[:8])[0]
            payload = frame_data[8:]

            # Wait until correct timestamp
            now = time.perf_counter()
            target_time = start_perf + (timestamp_us / 1_000_000)
            sleep_time = target_time - now
            if sleep_time > 0:
                time.sleep(sleep_time)

            self.sock.sendto(payload, (self.host, self.port))
            self._current_frame += 1

        print("✅ Playback finished")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._stop = True

    def resync(self, timestamp_sec):
        """Jump to timestamp in seconds"""
        for i, frame in enumerate(self.frames):
            ts_us = struct.unpack("<Q", frame[:8])[0]
            if ts_us / 1_000_000 >= timestamp_sec:
                self._current_frame = i
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
