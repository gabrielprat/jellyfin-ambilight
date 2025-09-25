#!/usr/bin/env python3
"""
Test video frame extraction and send to WLED with proper LED count
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
from database import init_database, save_frame

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

    # Total LED count from our configuration
    total_config_leds = TOP_LED_COUNT + RIGHT_LED_COUNT + BOTTOM_LED_COUNT + LEFT_LED_COUNT

    print(f"🔧 LED Configuration:")
    print(f"   Top: {TOP_LED_COUNT}, Right: {RIGHT_LED_COUNT}")
    print(f"   Bottom: {BOTTOM_LED_COUNT}, Left: {LEFT_LED_COUNT}")
    print(f"   Total from config: {total_config_leds}")

    # Calculate positions for each edge
    # Top edge (left to right)
    for i in range(TOP_LED_COUNT):
        x = i / (TOP_LED_COUNT - 1) if TOP_LED_COUNT > 1 else 0.5
        positions.append((x, 0.0))

    # Right edge (top to bottom)
    for i in range(RIGHT_LED_COUNT):
        y = i / (RIGHT_LED_COUNT - 1) if RIGHT_LED_COUNT > 1 else 0.5
        positions.append((1.0, y))

    # Bottom edge (right to left)
    for i in range(BOTTOM_LED_COUNT):
        x = 1.0 - (i / (BOTTOM_LED_COUNT - 1)) if BOTTOM_LED_COUNT > 1 else 0.5
        positions.append((x, 1.0))

    # Left edge (bottom to top)
    for i in range(LEFT_LED_COUNT):
        y = 1.0 - (i / (LEFT_LED_COUNT - 1)) if LEFT_LED_COUNT > 1 else 0.5
        positions.append((0.0, y))

    # Apply input position offset
    if INPUT_POSITION > 0:
        offset = INPUT_POSITION % total_config_leds
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

def extract_led_colors_from_array(img_array, border_size=0.1):
    """Extract LED colors from image array"""
    if img_array is None:
        return None

    height, width = img_array.shape[:2]
    led_positions = calculate_led_positions()
    led_colors = []

    for pos in led_positions:
        color = extract_color_for_led_position_array(img_array, pos, border_size)
        led_colors.append(color)

    return led_colors

def extract_color_for_led_position_array(img_array, led_pos, border_size):
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

def send_colors_to_wled(led_colors, wled_total_leds):
    """Send colors to WLED, filling missing LEDs with black"""
    try:
        # Convert to RGBW format
        wled_colors = []

        # Add our calculated colors
        for i, color in enumerate(led_colors):
            if color and len(color) >= 3:
                wled_colors.extend([int(color[0]), int(color[1]), int(color[2]), 0])
            else:
                wled_colors.extend([0, 0, 0, 0])

        # Fill remaining LEDs with black (not white!)
        remaining_leds = wled_total_leds - len(led_colors)
        if remaining_leds > 0:
            for i in range(remaining_leds):
                wled_colors.extend([0, 0, 0, 0])  # Black for unused LEDs

        print(f"📊 Sending: {len(led_colors)} calculated colors + {remaining_leds} black = {len(wled_colors)//4} total LEDs")

        payload = {
            "on": True,
            "bri": 255,
            "seg": [{
                "start": 0,
                "stop": wled_total_leds,
                "i": wled_colors
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        return True

    except Exception as e:
        print(f"❌ Error sending to WLED: {e}")
        return False

def test_video_frames(video_path, start_time=60, count=10, interval=5):
    """Test extracting and sending video frames"""
    print(f"🎬 Testing video frames from: {os.path.basename(video_path)}")

    # Get WLED info
    wled_info = get_wled_info()
    if not wled_info:
        return False

    wled_led_count = wled_info.get('leds', {}).get('count', 300)
    print(f"🔗 WLED has {wled_led_count} LEDs")

    # Show LED configuration
    led_positions = calculate_led_positions()
    print(f"   Calculated positions: {len(led_positions)} LEDs")
    print(f"   Missing LEDs: {wled_led_count - len(led_positions)} (will be black)")

    success_count = 0

    for i in range(count):
        current_time = start_time + (i * interval)
        print(f"\n🎯 Frame {i+1}/{count} at {current_time}s:")

        # Extract frame
        img_array = extract_frame_to_memory(video_path, current_time)
        if img_array is None:
            print(f"   ❌ Failed to extract frame")
            continue

        # Extract LED colors
        led_colors = extract_led_colors_from_array(img_array)
        if not led_colors:
            print(f"   ❌ Failed to extract colors")
            continue

        print(f"   ✅ Extracted {len(led_colors)} LED colors")

        # Send to WLED
        if send_colors_to_wled(led_colors, wled_led_count):
            success_count += 1
            print(f"   ✅ Sent to WLED successfully")
        else:
            print(f"   ❌ Failed to send to WLED")

        # Wait before next frame
        time.sleep(2)

    print(f"\n📊 Results: {success_count}/{count} frames sent successfully")
    return success_count == count

def main():
    parser = argparse.ArgumentParser(description='Test Video Frames with WLED')
    parser.add_argument('--file', type=str, required=True,
                        help='Video file path to test')
    parser.add_argument('--start', type=int, default=60,
                        help='Start time in seconds (default: 60)')
    parser.add_argument('--count', type=int, default=10,
                        help='Number of frames to test (default: 10)')
    parser.add_argument('--interval', type=int, default=5,
                        help='Interval between frames in seconds (default: 5)')

    args = parser.parse_args()

    print("🧪 Video Frame Test")
    print(f"🔗 WLED: {WLED_HOST}:{WLED_PORT}")
    print("=" * 50)

    if not os.path.exists(args.file):
        print(f"❌ Video file not found: {args.file}")
        return

    init_database()

    test_video_frames(
        video_path=args.file,
        start_time=args.start,
        count=args.count,
        interval=args.interval
    )

if __name__ == "__main__":
    main()
