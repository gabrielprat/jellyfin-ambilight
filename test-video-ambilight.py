#!/usr/bin/env python3
"""
Test script to extract colors from a video file and send them to WLED
Usage: python test-video-ambilight.py --file <video_file> [--duration <seconds>] [--start <seconds>]
"""

import argparse
import os
import sys
import time
import subprocess
import numpy as np
import cv2
import requests
import json
import socket
# Import local modules
sys.path.append('/app')
from database import init_database, save_frame

# Environment variables
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))
USE_UDP = os.getenv('WLED_USE_UDP', 'true').lower() == 'true'
FRAME_WIDTH = int(os.getenv('FRAME_EXTRACT_WIDTH', '89'))
FRAME_HEIGHT = int(os.getenv('FRAME_EXTRACT_HEIGHT', '49'))
FRAME_INTERVAL = float(os.getenv('FRAME_EXTRACT_INTERVAL', '0.067'))

# LED Configuration
TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
BOTTOM_LED_COUNT = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
LEFT_LED_COUNT = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
RIGHT_LED_COUNT = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))
INPUT_POSITION = int(os.getenv('AMBILIGHT_INPUT_POSITION', '46'))

def calculate_led_positions():
    """Calculate LED positions for screen edges (Hyperion.ng compatible)"""
    positions = []

    # Total LED count
    total_leds = TOP_LED_COUNT + RIGHT_LED_COUNT + BOTTOM_LED_COUNT + LEFT_LED_COUNT

    # Calculate positions for each edge
    # Top edge (left to right)
    for i in range(TOP_LED_COUNT):
        x = i / (TOP_LED_COUNT - 1) if TOP_LED_COUNT > 1 else 0.5
        positions.append((x, 0.0))  # y=0 is top

    # Right edge (top to bottom)
    for i in range(RIGHT_LED_COUNT):
        y = i / (RIGHT_LED_COUNT - 1) if RIGHT_LED_COUNT > 1 else 0.5
        positions.append((1.0, y))  # x=1 is right

    # Bottom edge (right to left)
    for i in range(BOTTOM_LED_COUNT):
        x = 1.0 - (i / (BOTTOM_LED_COUNT - 1)) if BOTTOM_LED_COUNT > 1 else 0.5
        positions.append((x, 1.0))  # y=1 is bottom

    # Left edge (bottom to top)
    for i in range(LEFT_LED_COUNT):
        y = 1.0 - (i / (LEFT_LED_COUNT - 1)) if LEFT_LED_COUNT > 1 else 0.5
        positions.append((0.0, y))  # x=0 is left

    # Apply input position offset (Hyperion.ng compatibility)
    if INPUT_POSITION > 0:
        offset = INPUT_POSITION % total_leds
        positions = positions[offset:] + positions[:offset]

    return positions

def extract_frame_to_memory(video_path, timestamp):
    """Extract frame directly to memory without saving to disk"""
    try:
        cmd = [
            'ffmpeg', '-y', '-v', 'quiet',
            '-ss', str(timestamp),
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={FRAME_WIDTH}:{FRAME_HEIGHT}',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            'pipe:1'  # Output to stdout
        ]

        result = subprocess.run(cmd, capture_output=True, check=True)

        if result.returncode == 0 and result.stdout:
            # Convert raw bytes to numpy array
            frame_data = np.frombuffer(result.stdout, dtype=np.uint8)

            # Reshape to image dimensions (height, width, channels)
            expected_size = FRAME_HEIGHT * FRAME_WIDTH * 3
            if len(frame_data) == expected_size:
                img = frame_data.reshape((FRAME_HEIGHT, FRAME_WIDTH, 3))
                return img
            else:
                print(f"⚠️  Unexpected frame data size: {len(frame_data)} vs expected {expected_size}")
                return None

        return None

    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error extracting frame at {timestamp}s from {video_path}: {e}")
        return None
    except Exception as e:
        print(f"⚠️  Unexpected error extracting frame: {e}")
        return None

def extract_led_colors_from_array(img_array, border_size=0.1):
    """Extract LED colors directly from numpy array (in-memory)"""
    try:
        if img_array is None:
            return None

        height, width = img_array.shape[:2]

        led_positions = calculate_led_positions()
        led_colors = []

        for pos in led_positions:
            color = extract_color_for_led_position_array(img_array, pos, border_size)
            led_colors.append(color)

        return led_colors

    except Exception as e:
        print(f"⚠️  Error extracting LED colors from array: {e}")
        return None

def extract_color_for_led_position_array(img_array, led_pos, border_size):
    """Extract average color for a single LED position from numpy array"""
    try:
        height, width = img_array.shape[:2]

        # Convert normalized position to pixel coordinates
        x, y = led_pos
        center_x = int(x * width)
        center_y = int(y * height)

        # Calculate border region size
        border_width = max(1, int(width * border_size))
        border_height = max(1, int(height * border_size))

        # Define sampling region based on LED position
        if y == 0:  # Top edge
            y1 = 0
            y2 = min(height, border_height)
            x1 = max(0, center_x - border_width // 2)
            x2 = min(width, center_x + border_width // 2)
        elif y == 1:  # Bottom edge
            y1 = max(0, height - border_height)
            y2 = height
            x1 = max(0, center_x - border_width // 2)
            x2 = min(width, center_x + border_width // 2)
        elif x == 0:  # Left edge
            x1 = 0
            x2 = min(width, border_width)
            y1 = max(0, center_y - border_height // 2)
            y2 = min(height, center_y + border_height // 2)
        elif x == 1:  # Right edge
            x1 = max(0, width - border_width)
            x2 = width
            y1 = max(0, center_y - border_height // 2)
            y2 = min(height, center_y + border_height // 2)
        else:
            # Corner or middle position - use small region around center
            x1 = max(0, center_x - border_width // 4)
            x2 = min(width, center_x + border_width // 4)
            y1 = max(0, center_y - border_height // 4)
            y2 = min(height, center_y + border_height // 4)

        # Ensure valid region
        if x2 <= x1 or y2 <= y1:
            return [0, 0, 0]

        # Extract region and calculate average color
        region = img_array[y1:y2, x1:x2]
        avg_color = np.mean(region, axis=(0, 1))

        return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]

    except Exception as e:
        print(f"⚠️  Error extracting color for LED position {led_pos}: {e}")
        return [0, 0, 0]

def get_video_duration(video_path):
    """Get video duration using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"⚠️  Error getting video duration: {e}")
        return None

# Global UDP socket for performance
_udp_socket = None

def get_udp_socket():
    """Get or create UDP socket"""
    global _udp_socket
    if _udp_socket is None:
        _udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return _udp_socket

def send_colors_to_wled_udp(led_colors):
    """Send LED colors via UDP (faster)"""
    try:
        sock = get_udp_socket()

        # DRGB protocol: [DRGB][timeout][rgb_data...]
        packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])  # 1 second timeout

        for color in led_colors:
            if color and len(color) >= 3:
                packet.extend([int(color[0]), int(color[1]), int(color[2])])
            else:
                packet.extend([0, 0, 0])

        sock.sendto(packet, (WLED_HOST, WLED_UDP_PORT))
        return True

    except Exception as e:
        print(f"⚠️  UDP Error: {e}")
        return False

def send_colors_to_wled_json(led_colors):
    """Send LED colors via JSON API (slower but reliable)"""
    try:
        # Get WLED LED count
        info_url = f"http://{WLED_HOST}:{WLED_PORT}/json/info"
        info_response = requests.get(info_url, timeout=WLED_TIMEOUT)
        wled_led_count = 300  # Default
        if info_response.status_code == 200:
            info = info_response.json()
            wled_led_count = info.get('leds', {}).get('count', 300)

        # Convert colors to WLED RGBW format
        wled_colors = []
        for color in led_colors:
            if color and len(color) >= 3:
                # Add RGB + White channel (0 for now)
                wled_colors.extend([int(color[0]), int(color[1]), int(color[2]), 0])
            else:
                wled_colors.extend([0, 0, 0, 0])  # Black for invalid colors

        # Fill remaining LEDs with black (not white!)
        remaining_leds = wled_led_count - len(led_colors)
        if remaining_leds > 0:
            for i in range(remaining_leds):
                wled_colors.extend([0, 0, 0, 0])  # Black for unused LEDs

        # WLED JSON API payload
        payload = {
            "on": True,
            "bri": 255,
            "seg": [{
                "start": 0,
                "stop": wled_led_count,
                "i": wled_colors
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        return True

    except requests.exceptions.RequestException as e:
        print(f"⚠️  JSON API Error: {e}")
        return False
    except Exception as e:
        print(f"⚠️  Unexpected error: {e}")
        return False

def send_colors_to_wled(led_colors):
    """Send LED colors to WLED (UDP or JSON based on config)"""
    if USE_UDP:
        return send_colors_to_wled_udp(led_colors)
    else:
        return send_colors_to_wled_json(led_colors)

def test_wled_connection():
    """Test if WLED device is reachable"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/info"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        info = response.json()
        print(f"✅ WLED connected: {info.get('name', 'Unknown')} (Version: {info.get('ver', 'Unknown')})")
        print(f"   LEDs: {info.get('leds', {}).get('count', 'Unknown')}")
        return True
    except Exception as e:
        print(f"❌ WLED connection failed: {e}")
        return False

def extract_and_send_colors(video_path, start_time=0, duration=30, interval=1.0):
    """Extract colors from video and send to WLED in real-time"""
    print(f"🎬 Processing video: {os.path.basename(video_path)}")
    print(f"⏱️  Duration: {duration}s, Start: {start_time}s, Interval: {interval}s")

    led_count = 0
    sent_count = 0
    error_count = 0

    current_time = start_time
    end_time = start_time + duration

    video_duration = get_video_duration(video_path)
    if video_duration:
        end_time = min(end_time, video_duration)
        print(f"📹 Video duration: {video_duration:.1f}s")

    print(f"🌈 Starting ambilight simulation...")
    print("   Press Ctrl+C to stop")

    try:
        while current_time < end_time:
            # Extract frame in memory
            img_array = extract_frame_to_memory(video_path, current_time)

            if img_array is not None:
                # Extract LED colors
                led_colors = extract_led_colors_from_array(img_array)

                if led_colors:
                    # Send to WLED
                    if send_colors_to_wled(led_colors):
                        sent_count += 1
                        print(f"⏯️  {current_time:6.1f}s -> WLED ({len(led_colors)} LEDs)", end='\r')
                    else:
                        error_count += 1
                        print(f"❌ {current_time:6.1f}s -> WLED Error", end='\r')
                else:
                    error_count += 1
                    print(f"⚠️  {current_time:6.1f}s -> No colors extracted", end='\r')
            else:
                error_count += 1
                print(f"⚠️  {current_time:6.1f}s -> Frame extraction failed", end='\r')

            led_count += 1
            current_time += interval

            # Small delay to avoid overwhelming WLED
            time.sleep(0.1)

    except KeyboardInterrupt:
        print(f"\n\n⏹️  Stopped by user")

    print(f"\n\n📊 Results:")
    print(f"   🎬 Frames processed: {led_count}")
    print(f"   🌈 Successfully sent: {sent_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"   📈 Success rate: {(sent_count/led_count*100) if led_count > 0 else 0:.1f}%")

def main():
    parser = argparse.ArgumentParser(description='Test Video Ambilight with WLED')
    parser.add_argument('--file', type=str,
                        help='Video file path to test')
    parser.add_argument('--duration', type=int, default=30,
                        help='Test duration in seconds (default: 30)')
    parser.add_argument('--start', type=int, default=0,
                        help='Start time in seconds (default: 0)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Frame extraction interval in seconds (default: 1.0)')
    parser.add_argument('--test-connection', action='store_true',
                        help='Only test WLED connection')

    args = parser.parse_args()

    # File is required unless we're just testing connection
    if not args.test_connection and not args.file:
        parser.error("--file is required unless using --test-connection")

    print("🧪 Video Ambilight Test")
    print(f"🔗 WLED: {WLED_HOST}:{WLED_PORT}")
    print()

    # Test WLED connection first
    if not test_wled_connection():
        print("❌ Cannot connect to WLED. Check configuration and try again.")
        sys.exit(1)

    if args.test_connection:
        print("✅ WLED connection test successful!")
        return

    # Check if video file exists
    if not os.path.exists(args.file):
        print(f"❌ Video file not found: {args.file}")
        sys.exit(1)

    print()

    # Initialize database (needed for LED calculations)
    init_database()

    # Extract and send colors
    extract_and_send_colors(
        video_path=args.file,
        start_time=args.start,
        duration=args.duration,
        interval=args.interval
    )

if __name__ == "__main__":
    main()
