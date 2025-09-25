#!/usr/bin/env python3
"""
Test Frame Extraction with Synthetic Data
==========================================

Create test video frames and verify border color extraction works correctly
"""

import os
from pathlib import Path
import socket
import time

def create_test_frame_rgb24(width: int, height: int, pattern: str) -> bytes:
    """Create a test frame in RGB24 format"""
    frame = bytearray(width * height * 3)

    if pattern == "rainbow_corners":
        # Different colored corners
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3

                if x < width // 2 and y < height // 2:
                    # Top-left: Red
                    frame[idx] = 255
                    frame[idx + 1] = 0
                    frame[idx + 2] = 0
                elif x >= width // 2 and y < height // 2:
                    # Top-right: Green
                    frame[idx] = 0
                    frame[idx + 1] = 255
                    frame[idx + 2] = 0
                elif x < width // 2 and y >= height // 2:
                    # Bottom-left: Blue
                    frame[idx] = 0
                    frame[idx + 1] = 0
                    frame[idx + 2] = 255
                else:
                    # Bottom-right: Yellow
                    frame[idx] = 255
                    frame[idx + 1] = 255
                    frame[idx + 2] = 0

    elif pattern == "bright_gradient":
        # Horizontal gradient from red to blue
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3
                progress = x / max(1, width - 1)

                frame[idx] = int(255 * (1 - progress))      # Red
                frame[idx + 1] = int(128 * abs(0.5 - progress) * 2)  # Green
                frame[idx + 2] = int(255 * progress)        # Blue

    elif pattern == "border_colors":
        # Black center, colored borders
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3

                # Check if on border
                is_border = (x < 10 or x >= width - 10 or y < 10 or y >= height - 10)

                if is_border:
                    if y < 10:  # Top
                        frame[idx] = 255  # Red
                    elif x >= width - 10:  # Right
                        frame[idx + 1] = 255  # Green
                    elif y >= height - 10:  # Bottom
                        frame[idx + 2] = 255  # Blue
                    else:  # Left
                        frame[idx] = 255
                        frame[idx + 1] = 255  # Yellow
                # Center stays black (0,0,0)

    return bytes(frame)

def test_border_extraction(frame_data: bytes, width: int, height: int, pattern_name: str):
    """Test border extraction function"""
    print(f"\n🧪 Testing border extraction: {pattern_name}")
    print(f"   Frame: {width}x{height} = {len(frame_data)} bytes")

    # Import the actual extraction function
    try:
        import sys
        sys.path.append('./frames')
        from fast_extractor_pure import _extract_border_colors_pure, _apply_led_offset_pure

        # Extract border colors
        border_data = _extract_border_colors_pure(frame_data, width, height)
        led_count = len(border_data) // 3

        print(f"   Border LEDs: {led_count}")

        # Analyze colors
        colors = {}
        for i in range(led_count):
            r = border_data[i*3]
            g = border_data[i*3 + 1]
            b = border_data[i*3 + 2]
            color = (r, g, b)
            colors[color] = colors.get(color, 0) + 1

        print(f"   Unique colors: {len(colors)}")

        # Show most common colors
        sorted_colors = sorted(colors.items(), key=lambda x: x[1], reverse=True)
        print(f"   Top colors:")
        for i, ((r, g, b), count) in enumerate(sorted_colors[:5]):
            percentage = (count / led_count) * 100
            print(f"      RGB({r:3d},{g:3d},{b:3d}): {count:3d} LEDs ({percentage:4.1f}%)")

        # Apply LED offset
        EXPECTED_LED_COUNT = 276
        INPUT_POSITION = 46

        payload = _apply_led_offset_pure(border_data, INPUT_POSITION)

        # Ensure correct LED count
        led_triplets = len(payload) // 3
        if led_triplets != EXPECTED_LED_COUNT:
            if led_triplets < EXPECTED_LED_COUNT:
                payload += bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
            else:
                payload = payload[:EXPECTED_LED_COUNT * 3]

        # Create UDP packet
        packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])
        packet.extend(payload)

        print(f"   Final packet: {len(packet)} bytes")

        # Send to WLED
        send_to_wled(bytes(packet), pattern_name)

        return bytes(packet)

    except ImportError as e:
        print(f"   ❌ Cannot import extraction functions: {e}")
        return None

def send_to_wled(packet: bytes, description: str):
    """Send packet to WLED"""
    try:
        wled_host = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
        wled_port = int(os.getenv('WLED_UDP_PORT', '21324'))

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bytes_sent = sock.sendto(packet, (wled_host, wled_port))
        sock.close()

        print(f"   📡 Sent to WLED: {bytes_sent} bytes ({description})")

    except Exception as e:
        print(f"   ❌ WLED send failed: {e}")

def test_realtime_mode():
    """Test WLED realtime mode with continuous packets"""
    print(f"\n🔴 Testing WLED Realtime Mode Activation")
    print("=" * 50)

    # Create a simple animated pattern
    led_count = 276

    print("Sending continuous packets (should activate realtime mode)...")

    for frame in range(100):  # 10 seconds at 10 FPS
        # Create rotating rainbow
        packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])

        for led in range(led_count):
            # Rotating hue based on LED position and frame
            hue = ((led * 360 // led_count) + (frame * 5)) % 360
            r, g, b = hsv_to_rgb(hue, 255, 200)  # High saturation, medium brightness
            packet.extend([r, g, b])

        send_to_wled(bytes(packet), f"animated_frame_{frame}")
        time.sleep(0.1)  # 10 FPS

        if frame % 10 == 0:
            print(f"   Frame {frame}/100")

    print("✅ Animation complete - WLED should have entered realtime mode!")

def hsv_to_rgb(h: int, s: int, v: int) -> tuple:
    """Convert HSV to RGB"""
    h = h % 360
    c = v * s // 255
    x = c * (1 - abs((h // 60) % 2 - 1))
    m = v - c

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return r + m, g + m, b + m

def main():
    """Main test function"""
    print("🧪 Frame Extraction & WLED Testing")
    print("=" * 60)

    # Test different frame patterns
    width, height = 1920, 1080

    patterns = [
        "rainbow_corners",
        "bright_gradient",
        "border_colors"
    ]

    for pattern in patterns:
        frame_data = create_test_frame_rgb24(width, height, pattern)
        test_border_extraction(frame_data, width, height, pattern)
        time.sleep(2)  # Wait between tests

    # Test realtime mode
    test_realtime_mode()

if __name__ == "__main__":
    main()
