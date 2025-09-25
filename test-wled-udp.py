#!/usr/bin/env python3
"""
Test WLED with UDP protocol for real-time ambilight
UDP is much faster than JSON API for real-time color updates
"""

import argparse
import os
import sys
import time
import subprocess
import numpy as np
import socket
import struct

# Import local modules
sys.path.append('/app')
from database import init_database

# Environment variables
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))  # Default WLED UDP port
FRAME_WIDTH = int(os.getenv('FRAME_EXTRACT_WIDTH', '89'))
FRAME_HEIGHT = int(os.getenv('FRAME_EXTRACT_HEIGHT', '49'))

# LED Configuration
TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
BOTTOM_LED_COUNT = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
LEFT_LED_COUNT = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
RIGHT_LED_COUNT = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))
INPUT_POSITION = int(os.getenv('AMBILIGHT_INPUT_POSITION', '46'))

class WLEDUDPSender:
    """WLED UDP protocol sender"""

    def __init__(self, host, port=21324):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_colors_drgb(self, led_colors):
        """Send colors using DRGB protocol (most common)"""
        try:
            # DRGB protocol: [DRGB][timeout][led_data...]
            # timeout: 1 = 1 second, 255 = persistent
            packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])  # 1 second timeout

            for color in led_colors:
                if len(color) >= 3:
                    packet.extend([int(color[0]), int(color[1]), int(color[2])])
                else:
                    packet.extend([0, 0, 0])

            self.sock.sendto(packet, (self.host, self.port))
            return True

        except Exception as e:
            print(f"❌ UDP DRGB Error: {e}")
            return False

    def send_colors_warls(self, led_colors):
        """Send colors using WARLS protocol (supports more features)"""
        try:
            # WARLS protocol: [WARLS][timeout][start_led][rgb_data...]
            packet = bytearray([ord('W'), ord('A'), ord('R'), ord('L'), ord('S')])
            packet.append(1)  # timeout (1 second)
            packet.extend([0, 0])  # start LED (0)

            for color in led_colors:
                if len(color) >= 3:
                    packet.extend([int(color[0]), int(color[1]), int(color[2])])
                else:
                    packet.extend([0, 0, 0])

            self.sock.sendto(packet, (self.host, self.port))
            return True

        except Exception as e:
            print(f"❌ UDP WARLS Error: {e}")
            return False

    def send_colors_dnrgb(self, led_colors):
        """Send colors using DNRGB protocol (with LED count)"""
        try:
            # DNRGB protocol: [DNRGB][timeout][led_count_high][led_count_low][rgb_data...]
            led_count = len(led_colors)
            packet = bytearray([ord('D'), ord('N'), ord('R'), ord('G'), ord('B')])
            packet.append(1)  # timeout (1 second)
            packet.extend([(led_count >> 8) & 0xFF, led_count & 0xFF])  # LED count (16-bit)

            for color in led_colors:
                if len(color) >= 3:
                    packet.extend([int(color[0]), int(color[1]), int(color[2])])
                else:
                    packet.extend([0, 0, 0])

            self.sock.sendto(packet, (self.host, self.port))
            return True

        except Exception as e:
            print(f"❌ UDP DNRGB Error: {e}")
            return False

    def close(self):
        """Close UDP socket"""
        self.sock.close()

def calculate_led_positions():
    """Calculate LED positions for screen edges"""
    positions = []

    for i in range(TOP_LED_COUNT):
        x = i / (TOP_LED_COUNT - 1) if TOP_LED_COUNT > 1 else 0.5
        positions.append((x, 0.0))

    for i in range(RIGHT_LED_COUNT):
        y = i / (RIGHT_LED_COUNT - 1) if RIGHT_LED_COUNT > 1 else 0.5
        positions.append((1.0, y))

    for i in range(BOTTOM_LED_COUNT):
        x = 1.0 - (i / (BOTTOM_LED_COUNT - 1)) if BOTTOM_LED_COUNT > 1 else 0.5
        positions.append((x, 1.0))

    for i in range(LEFT_LED_COUNT):
        y = 1.0 - (i / (LEFT_LED_COUNT - 1)) if LEFT_LED_COUNT > 1 else 0.5
        positions.append((0.0, y))

    # Apply input position offset
    total_leds = len(positions)
    if INPUT_POSITION > 0:
        offset = INPUT_POSITION % total_leds
        positions = positions[offset:] + positions[:offset]

    return positions

def extract_frame_to_memory(video_path, timestamp):
    """Extract frame directly to memory"""
    try:
        cmd = [
            'ffmpeg', '-y', '-v', 'quiet',
            '-ss', str(timestamp),
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={FRAME_WIDTH}:{FRAME_HEIGHT}',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            'pipe:1'
        ]

        result = subprocess.run(cmd, capture_output=True, check=True)

        if result.returncode == 0 and result.stdout:
            frame_data = np.frombuffer(result.stdout, dtype=np.uint8)
            expected_size = FRAME_HEIGHT * FRAME_WIDTH * 3
            if len(frame_data) == expected_size:
                img = frame_data.reshape((FRAME_HEIGHT, FRAME_WIDTH, 3))
                return img
        return None

    except Exception as e:
        print(f"⚠️  Error extracting frame: {e}")
        return None

def extract_color_for_led_position_array(img_array, led_pos, border_size=0.1):
    """Extract color for a single LED position"""
    try:
        height, width = img_array.shape[:2]
        x, y = led_pos
        center_x = int(x * width)
        center_y = int(y * height)

        border_width = max(1, int(width * border_size))
        border_height = max(1, int(height * border_size))

        # Define sampling region based on LED position
        if y == 0:  # Top edge
            y1, y2 = 0, min(height, border_height)
            x1 = max(0, center_x - border_width // 2)
            x2 = min(width, center_x + border_width // 2)
        elif y == 1:  # Bottom edge
            y1 = max(0, height - border_height)
            y2 = height
            x1 = max(0, center_x - border_width // 2)
            x2 = min(width, center_x + border_width // 2)
        elif x == 0:  # Left edge
            x1, x2 = 0, min(width, border_width)
            y1 = max(0, center_y - border_height // 2)
            y2 = min(height, center_y + border_height // 2)
        elif x == 1:  # Right edge
            x1 = max(0, width - border_width)
            x2 = width
            y1 = max(0, center_y - border_height // 2)
            y2 = min(height, center_y + border_height // 2)
        else:
            x1 = max(0, center_x - border_width // 4)
            x2 = min(width, center_x + border_width // 4)
            y1 = max(0, center_y - border_height // 4)
            y2 = min(height, center_y + border_height // 4)

        if x2 <= x1 or y2 <= y1:
            return [0, 0, 0]

        region = img_array[y1:y2, x1:x2]
        avg_color = np.mean(region, axis=(0, 1))

        return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]

    except Exception as e:
        return [0, 0, 0]

def extract_led_colors_from_array(img_array):
    """Extract LED colors from image array"""
    if img_array is None:
        return None

    led_positions = calculate_led_positions()
    led_colors = []

    for pos in led_positions:
        color = extract_color_for_led_position_array(img_array, pos)
        led_colors.append(color)

    return led_colors

def test_udp_protocols():
    """Test different UDP protocols"""
    print("🧪 Testing WLED UDP Protocols")
    print(f"🔗 Target: {WLED_HOST}:{WLED_UDP_PORT}")
    print("=" * 50)

    sender = WLEDUDPSender(WLED_HOST, WLED_UDP_PORT)

    # Test colors
    test_colors = [
        ([255, 0, 0], "🔴 Red"),
        ([0, 255, 0], "🟢 Green"),
        ([0, 0, 255], "🔵 Blue"),
        ([255, 255, 255], "⚪ White")
    ]

    led_positions = calculate_led_positions()
    led_count = len(led_positions)

    print(f"📊 Testing with {led_count} LEDs")

    for color, name in test_colors:
        print(f"\n{name} - Testing all protocols:")

        # Create color array
        colors = [color for _ in range(led_count)]

        # Test DRGB protocol
        print("   DRGB: ", end="")
        if sender.send_colors_drgb(colors):
            print("✅ Sent")
        else:
            print("❌ Failed")
        time.sleep(2)

        # Test WARLS protocol
        print("   WARLS: ", end="")
        if sender.send_colors_warls(colors):
            print("✅ Sent")
        else:
            print("❌ Failed")
        time.sleep(2)

        # Test DNRGB protocol
        print("   DNRGB: ", end="")
        if sender.send_colors_dnrgb(colors):
            print("✅ Sent")
        else:
            print("❌ Failed")
        time.sleep(2)

    sender.close()

def test_video_udp(video_path, start_time=60, duration=30, interval=0.1, protocol="drgb"):
    """Test video ambilight with UDP"""
    print(f"\n🎬 Video UDP Test: {os.path.basename(video_path)}")
    print(f"🔗 Protocol: {protocol.upper()}")
    print(f"⏱️  Start: {start_time}s, Duration: {duration}s, Interval: {interval}s")

    sender = WLEDUDPSender(WLED_HOST, WLED_UDP_PORT)
    led_positions = calculate_led_positions()

    print(f"🌈 Starting UDP ambilight...")
    print("   Press Ctrl+C to stop")

    start = time.time()
    frame_count = 0
    success_count = 0

    try:
        current_time = start_time
        end_time = start_time + duration

        while current_time < end_time:
            frame_start = time.time()

            # Extract frame
            img_array = extract_frame_to_memory(video_path, current_time)
            if img_array is not None:
                # Extract colors
                led_colors = extract_led_colors_from_array(img_array)
                if led_colors:
                    # Send via UDP
                    success = False
                    if protocol.lower() == "drgb":
                        success = sender.send_colors_drgb(led_colors)
                    elif protocol.lower() == "warls":
                        success = sender.send_colors_warls(led_colors)
                    elif protocol.lower() == "dnrgb":
                        success = sender.send_colors_dnrgb(led_colors)

                    if success:
                        success_count += 1
                        print(f"⚡ {current_time:6.1f}s -> UDP ({len(led_colors)} LEDs)", end='\r')
                    else:
                        print(f"❌ {current_time:6.1f}s -> UDP Error", end='\r')

            frame_count += 1
            current_time += interval

            # Small delay to maintain interval
            frame_time = time.time() - frame_start
            sleep_time = max(0, interval - frame_time)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\n⏹️  Stopped by user")

    total_time = time.time() - start
    sender.close()

    print(f"\n\n📊 UDP Performance Results:")
    print(f"   🎬 Frames processed: {frame_count}")
    print(f"   🌈 Successfully sent: {success_count}")
    print(f"   ❌ Errors: {frame_count - success_count}")
    print(f"   📈 Success rate: {(success_count/frame_count*100) if frame_count > 0 else 0:.1f}%")
    print(f"   ⚡ Average FPS: {frame_count/total_time:.1f}")
    print(f"   ⏱️  Average frame time: {(total_time/frame_count*1000) if frame_count > 0 else 0:.1f}ms")

def main():
    parser = argparse.ArgumentParser(description='Test WLED UDP Protocol')
    parser.add_argument('--test-protocols', action='store_true',
                        help='Test all UDP protocols with solid colors')
    parser.add_argument('--video', type=str,
                        help='Video file to test with')
    parser.add_argument('--start', type=int, default=60,
                        help='Start time in seconds (default: 60)')
    parser.add_argument('--duration', type=int, default=30,
                        help='Test duration in seconds (default: 30)')
    parser.add_argument('--interval', type=float, default=0.1,
                        help='Frame interval in seconds (default: 0.1)')
    parser.add_argument('--protocol', type=str, default='drgb',
                        choices=['drgb', 'warls', 'dnrgb'],
                        help='UDP protocol to use (default: drgb)')

    args = parser.parse_args()

    print("⚡ WLED UDP Tester")
    print(f"🔗 Target: {WLED_HOST}:{WLED_UDP_PORT}")
    print("=" * 50)

    init_database()

    if args.test_protocols:
        test_udp_protocols()

    if args.video:
        if os.path.exists(args.video):
            test_video_udp(
                video_path=args.video,
                start_time=args.start,
                duration=args.duration,
                interval=args.interval,
                protocol=args.protocol
            )
        else:
            print(f"❌ Video file not found: {args.video}")

    if not args.test_protocols and not args.video:
        print("💡 Use --test-protocols to test UDP protocols")
        print("💡 Use --video <file> to test video ambilight")

if __name__ == "__main__":
    main()
