import socket
import time
import os

WLED_IP = os.getenv("WLED_HOST", "wled-ambilight-lgc1.lan")
WLED_PORT = int(os.getenv("WLED_UDP_PORT", "21324"))

def play_binary(filename: str, start_time: float = 0.0, fps: float = 25.0, num_leds: int = 150):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    frame_size = int(num_leds) * 3
    frame_time = 1.0 / float(fps)

    start_frame = int(start_time * fps)
    offset = start_frame * frame_size

    with open(filename, "rb") as f:
        f.seek(offset)
        while True:
            data = f.read(frame_size)
            if not data:
                break
            sock.sendto(data, (WLED_IP, WLED_PORT))
            time.sleep(frame_time)

__all__ = ["play_binary"]
