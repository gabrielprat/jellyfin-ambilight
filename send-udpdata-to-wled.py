#!/usr/bin/env python3
import os
import socket
import struct
import sys
import time


def iter_udp_packets(file_path: str):
    """Yield (timestamp, packet_bytes) for each record in the .udpdata file."""
    with open(file_path, 'rb') as f:
        while True:
            ts_bytes = f.read(4)
            if len(ts_bytes) < 4:
                return
            timestamp = struct.unpack('<f', ts_bytes)[0]

            size_bytes = f.read(4)
            if len(size_bytes) < 4:
                return
            packet_size = struct.unpack('<I', size_bytes)[0]
            if packet_size <= 0:
                return

            packet = f.read(packet_size)
            if len(packet) < packet_size:
                return

            yield timestamp, packet


def drgb_to_warls(drgb_packet: bytes, timeout: int, expected_leds: int) -> bytes:
    # Accept DRGB; fall back to raw RGB payload if not DRGB
    if len(drgb_packet) >= 5 and drgb_packet[:4] == b'DRGB':
        rgb_payload = drgb_packet[5:]
    else:
        rgb_payload = drgb_packet

    # Pad/truncate to expected LED count
    led_triplets = len(rgb_payload) // 3
    if expected_leds is not None and expected_leds > 0:
        if led_triplets < expected_leds:
            rgb_payload = rgb_payload + bytes([0, 0, 0] * (expected_leds - led_triplets))
        elif led_triplets > expected_leds:
            rgb_payload = rgb_payload[: expected_leds * 3]

    # WARLS header
    num_leds = len(rgb_payload) // 3
    max_leds = min(num_leds, 255)
    data = bytearray([1, timeout if timeout else 1])
    for i in range(max_leds):
        base = i * 3
        r, g, b = rgb_payload[base], rgb_payload[base + 1], rgb_payload[base + 2]
        data.extend([i & 0xFF, r, g, b])
    return bytes(data)


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 send-udpdata-to-wled.py <file.udpdata> [protocol]')
        print('  protocol: DRGB | WARLS (default: env WLED_UDP_PROTOCOL or WARLS)')
        sys.exit(1)

    file_path = sys.argv[1]
    protocol = (sys.argv[2] if len(sys.argv) > 2 else os.getenv('WLED_UDP_PROTOCOL', 'WARLS')).upper()

    wled_host = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
    wled_port = int(os.getenv('WLED_UDP_PORT', '21324'))
    wled_timeout = int(os.getenv('WLED_UDP_TIMEOUT', '255'))

    top = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
    bottom = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
    left = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
    right = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))
    expected_leds = top + bottom + left + right

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f'Streaming frames from {file_path} to {wled_host}:{wled_port} via {protocol}. Press Ctrl+C to stop.')

    try:
        # Loop indefinitely until interrupted; restart at EOF
        while True:
            prev_ts = None
            for ts, pkt in iter_udp_packets(file_path):
                # Timing to simulate playback
                if prev_ts is not None:
                    delay = max(0.0, ts - prev_ts)
                    if delay > 0:
                        time.sleep(delay)
                prev_ts = ts

                if protocol == 'DRGB':
                    # Ensure DRGB header
                    if not (len(pkt) >= 5 and pkt[:4] == b'DRGB'):
                        rgb = pkt
                        leds = len(rgb) // 3
                        if leds < expected_leds:
                            rgb = rgb + bytes([0, 0, 0] * (expected_leds - leds))
                        elif leds > expected_leds:
                            rgb = rgb[: expected_leds * 3]
                        data = b'DRGB' + bytes([1]) + rgb
                    else:
                        data = pkt
                else:
                    data = drgb_to_warls(pkt, wled_timeout, expected_leds)

                sock.sendto(data, (wled_host, wled_port))

            # End of file reached: loop back to start
    except KeyboardInterrupt:
        print('\nStopped by user.')
    finally:
        sock.close()


if __name__ == '__main__':
    main()
