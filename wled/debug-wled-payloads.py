#!/usr/bin/env python3
"""
Debug WLED payloads - show exactly what we're sending
"""

import argparse
import os
import sys
import time
import subprocess
import numpy as np
import requests
import json

# Import local modules
sys.path.append('/app')
from database import init_database

# Environment variables
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))
FRAME_WIDTH = int(os.getenv('FRAME_EXTRACT_WIDTH', '320'))
FRAME_HEIGHT = int(os.getenv('FRAME_EXTRACT_HEIGHT', '240'))

# LED Configuration
TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
BOTTOM_LED_COUNT = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
LEFT_LED_COUNT = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
RIGHT_LED_COUNT = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))
INPUT_POSITION = int(os.getenv('AMBILIGHT_INPUT_POSITION', '46'))

def get_wled_info():
    """Get WLED device information"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/info"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        info = response.json()
        return info
    except Exception as e:
        print(f"❌ Error getting WLED info: {e}")
        return None

def calculate_led_positions():
    """Calculate LED positions for screen edges"""
    positions = []

    # Calculate positions for each edge
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

def debug_wled_payload(led_colors, wled_total_leds, description=""):
    """Create and display WLED payload with detailed debugging"""
    print(f"\n🔍 DEBUG: {description}")
    print("=" * 60)

    # Show LED color summary
    print(f"📊 Input LED Colors: {len(led_colors)} colors")
    if led_colors:
        print(f"   First 5 colors: {led_colors[:5]}")
        print(f"   Last 5 colors: {led_colors[-5:]}")

        # Show color statistics
        max_r = max(color[0] for color in led_colors if len(color) >= 3)
        max_g = max(color[1] for color in led_colors if len(color) >= 3)
        max_b = max(color[2] for color in led_colors if len(color) >= 3)
        print(f"   Max RGB values: R={max_r}, G={max_g}, B={max_b}")

    # Convert to WLED RGBW format
    wled_colors = []
    for i, color in enumerate(led_colors):
        if color and len(color) >= 3:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            w = 0  # White channel
            wled_colors.extend([r, g, b, w])
        else:
            wled_colors.extend([0, 0, 0, 0])

    # Fill remaining LEDs with black
    remaining_leds = wled_total_leds - len(led_colors)
    if remaining_leds > 0:
        for i in range(remaining_leds):
            wled_colors.extend([0, 0, 0, 0])

    print(f"🎨 WLED Payload Details:")
    print(f"   Total LED count: {wled_total_leds}")
    print(f"   Calculated colors: {len(led_colors)}")
    print(f"   Black fill: {remaining_leds}")
    print(f"   RGBW values count: {len(wled_colors)} (should be {wled_total_leds * 4})")

    # Show first few RGBW values
    print(f"   First 20 RGBW values: {wled_colors[:20]}")
    print(f"   Last 20 RGBW values: {wled_colors[-20:]}")

    # Create payload
    payload = {
        "on": True,
        "bri": 255,
        "seg": [{
            "start": 0,
            "stop": wled_total_leds,
            "i": wled_colors
        }]
    }

    # Show payload structure (without the huge color array)
    payload_summary = {
        "on": payload["on"],
        "bri": payload["bri"],
        "seg": [{
            "start": payload["seg"][0]["start"],
            "stop": payload["seg"][0]["stop"],
            "i": f"[{len(payload['seg'][0]['i'])} RGBW values]"
        }]
    }

    print(f"📦 JSON Payload Structure:")
    print(json.dumps(payload_summary, indent=2))

    # Send to WLED
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        print(f"\n📡 Sending to: {url}")

        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        print(f"📬 Response: Status {response.status_code}")

        if response.status_code == 200:
            response_data = response.json()
            print(f"   Response data: {response_data}")
            print("✅ Payload sent successfully")
            return True
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"   Response text: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Error sending payload: {e}")
        return False

def test_simple_payloads():
    """Test simple payloads first"""
    wled_info = get_wled_info()
    if not wled_info:
        return False

    wled_led_count = wled_info.get('leds', {}).get('count', 300)
    print(f"🔗 WLED has {wled_led_count} LEDs")

    # Test 1: All red
    print("\n" + "="*60)
    print("🔴 TEST 1: All LEDs Red")
    red_colors = [[255, 0, 0] for _ in range(wled_led_count)]
    debug_wled_payload(red_colors, wled_led_count, "All Red LEDs")
    time.sleep(3)

    # Test 2: Rainbow pattern
    print("\n" + "="*60)
    print("🌈 TEST 2: Rainbow Pattern")
    rainbow_colors = []
    for i in range(min(wled_led_count, 276)):  # Our LED count
        hue = (i * 360 // 276) % 360
        if hue < 60:
            r, g, b = 255, int(hue * 255 / 60), 0
        elif hue < 120:
            r, g, b = int((120 - hue) * 255 / 60), 255, 0
        elif hue < 180:
            r, g, b = 0, 255, int((hue - 120) * 255 / 60)
        elif hue < 240:
            r, g, b = 0, int((240 - hue) * 255 / 60), 255
        elif hue < 300:
            r, g, b = int((hue - 240) * 255 / 60), 0, 255
        else:
            r, g, b = 255, 0, int((360 - hue) * 255 / 60)

        rainbow_colors.append([r, g, b])

    debug_wled_payload(rainbow_colors, wled_led_count, "Rainbow Pattern")
    time.sleep(3)

    return True

def test_video_frame_payload(video_path, timestamp=60):
    """Test with actual video frame"""
    wled_info = get_wled_info()
    if not wled_info:
        return False

    wled_led_count = wled_info.get('leds', {}).get('count', 300)

    print("\n" + "="*60)
    print(f"🎬 VIDEO FRAME TEST: {os.path.basename(video_path)} at {timestamp}s")

    # Extract frame
    img_array = extract_frame_to_memory(video_path, timestamp)
    if img_array is None:
        print("❌ Failed to extract frame")
        return False

    # Extract LED colors
    led_colors = extract_led_colors_from_array(img_array)
    if not led_colors:
        print("❌ Failed to extract colors")
        return False

    debug_wled_payload(led_colors, wled_led_count, f"Video Frame at {timestamp}s")

    return True

def main():
    parser = argparse.ArgumentParser(description='Debug WLED Payloads')
    parser.add_argument('--video', type=str,
                        help='Video file to test with')
    parser.add_argument('--timestamp', type=int, default=60,
                        help='Timestamp to extract (default: 60)')
    parser.add_argument('--simple-only', action='store_true',
                        help='Only test simple payloads')

    args = parser.parse_args()

    print("🔍 WLED Payload Debugger")
    print(f"🔗 Target: {WLED_HOST}:{WLED_PORT}")
    print("=" * 60)

    init_database()

    # Test simple payloads first
    if not test_simple_payloads():
        return

    # Test video frame if provided
    if not args.simple_only and args.video:
        if os.path.exists(args.video):
            test_video_frame_payload(args.video, args.timestamp)
        else:
            print(f"❌ Video file not found: {args.video}")

if __name__ == "__main__":
    main()
