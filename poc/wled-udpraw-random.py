#!/usr/bin/env python3
import os
import socket
import random
import time


def send_udp_raw(sock, host: str, port: int, led_count: int):
    rgb = bytearray()
    for _ in range(led_count):
        rgb.extend((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    sock.sendto(bytes(rgb), (host, port))


def send_dnrgb(sock, host: str, port: int, led_count: int, timeout: int):
    # DNRGB supports up to 489 LEDs per packet starting at a given index
    # We will chunk the strip into runs and fill with random RGB
    start = 0
    remaining = led_count
    while remaining > 0:
        chunk_len = 489 if remaining > 489 else remaining
        payload = bytearray()
        for _ in range(chunk_len):
            payload.extend((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))

        start_hi = (start >> 8) & 0xFF
        start_lo = start & 0xFF
        pkt = bytearray([4, timeout if timeout else 1, start_hi, start_lo])
        pkt.extend(payload)
        sock.sendto(bytes(pkt), (host, port))

        start += chunk_len
        remaining -= chunk_len


def main():
    host = 'wled-ambilight-lgc1.lan'
    protocol = "UDP_RAW"
    led_count = 300
    fps = 20
    timeout = 255

    raw_port = 19446

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Streaming random colors per LED to {host} using {protocol} @ {fps} FPS. Ctrl+C to stop.")
    try:
        delay = 1.0 / fps if fps > 0 else 0.0
        while True:
            start_t = time.time()
            send_udp_raw(sock, host, raw_port, led_count)
            elapsed = time.time() - start_t
            sleep_t = delay - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


if __name__ == '__main__':
    main()
