import socket
import time
import os
import struct

WLED_IP = "wled-ambilight-lgc1.lan"
WLED_PORT = 4048   # port DDP per defecte
FPS = 25
NUM_LEDS = 150
FRAME_SIZE = NUM_LEDS * 3
FRAME_TIME = 1 / FPS

def build_ddp_packet(data: bytes, offset: int = 0) -> bytes:
    """Construeix un paquet DDP per WLED amb dades RGB."""
    data_len = len(data)
    header = bytearray(10)
    header[0] = 0x41  # flags: V=1, push flag
    header[1] = 0x01  # data type: RGB
    # offset (4 bytes, big endian)
    header[2:4] = (offset >> 16 & 0xFFFF).to_bytes(2, "big")
    header[4:8] = (offset & 0xFFFFFFFF).to_bytes(4, "big")
    # length (2 bytes, big endian)
    header[8:10] = data_len.to_bytes(2, "big")
    return bytes(header) + data

def play_binary(filename, start_time=0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    start_frame = int(start_time * FPS)
    offset = start_frame * FRAME_SIZE

    filesize = os.path.getsize(filename)
    total_frames = filesize // FRAME_SIZE

    with open(filename, "rb") as f:
        f.seek(offset)
        print(f"Starting playback at {start_time:.2f}s (frame {start_frame}/{total_frames})")

        start_clock = time.perf_counter()
        frame_index = 0

        while True:
            data = f.read(FRAME_SIZE)
            if not data:
                break

            # Construeix paquet DDP i envia'l
            packet = build_ddp_packet(data)
            sock.sendto(packet, (WLED_IP, WLED_PORT))

            frame_index += 1
            next_time = start_clock + frame_index * FRAME_TIME
            delay = next_time - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

if __name__ == "__main__":
    play_binary("led_data.bin", start_time=0)
