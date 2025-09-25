#!/usr/bin/env python3
"""
Simple UDP Color Visualizer (ASCII version)
===========================================

Displays LED colors using ASCII characters and brightness levels
Works in any terminal without color support.
"""

import os
import struct
import sys
from pathlib import Path
from typing import List, Tuple

def brightness_to_char(brightness: float) -> str:
    """Convert brightness (0-255) to ASCII character"""
    if brightness < 10:
        return '.'   # Very dark
    elif brightness < 30:
        return ':'   # Dark
    elif brightness < 60:
        return '*'   # Medium-dark
    elif brightness < 120:
        return 'o'   # Medium
    elif brightness < 180:
        return 'O'   # Bright
    else:
        return '#'   # Very bright

def rgb_to_brightness(r: int, g: int, b: int) -> float:
    """Calculate perceived brightness from RGB"""
    # Use standard luminance formula
    return 0.299 * r + 0.587 * g + 0.114 * b

def rgb_to_char(r: int, g: int, b: int) -> str:
    """Convert RGB to representative character"""
    brightness = rgb_to_brightness(r, g, b)

    if brightness < 5:
        return ' '   # Black/very dark
    elif r > g and r > b:
        return 'R'   # Red dominant
    elif g > r and g > b:
        return 'G'   # Green dominant
    elif b > r and b > g:
        return 'B'   # Blue dominant
    elif r > 150 and g > 150 and b < 100:
        return 'Y'   # Yellow
    elif r > 150 and g < 100 and b > 150:
        return 'M'   # Magenta
    elif r < 100 and g > 150 and b > 150:
        return 'C'   # Cyan
    elif brightness > 200:
        return 'W'   # White/very bright
    else:
        return brightness_to_char(brightness)

def read_udp_packet(file_handle) -> Tuple[float, bytes]:
    """Read a single UDP packet from file"""
    # Read timestamp (4 bytes)
    timestamp_bytes = file_handle.read(4)
    if len(timestamp_bytes) < 4:
        return None, None

    timestamp = struct.unpack('<f', timestamp_bytes)[0]

    # Read packet size (4 bytes)
    size_bytes = file_handle.read(4)
    if len(size_bytes) < 4:
        return None, None

    packet_size = struct.unpack('<I', size_bytes)[0]

    # Read UDP packet
    udp_packet = file_handle.read(packet_size)
    if len(udp_packet) < packet_size:
        return None, None

    return timestamp, udp_packet

def parse_udp_packet(packet: bytes) -> List[Tuple[int, int, int]]:
    """Parse UDP packet and extract RGB colors"""
    if len(packet) < 5 or packet[:4] != b'DRGB':
        return []

    rgb_data = packet[5:]  # Skip DRGB header and timeout byte
    led_count = len(rgb_data) // 3

    colors = []
    for i in range(led_count):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]
        colors.append((r, g, b))

    return colors

def visualize_led_rectangle_ascii(colors: List[Tuple[int, int, int]],
                                 top_count: int = 89, right_count: int = 49,
                                 bottom_count: int = 89, left_count: int = 49):
    """Visualize LEDs as ASCII rectangle"""
    if len(colors) < (top_count + right_count + bottom_count + left_count):
        print("⚠️  Not enough LED data for rectangle layout")
        return

    print(f"📺 TV Border Layout (ASCII) - {len(colors)} LEDs:")
    print()
    print("Legend: . = dark, : = dim, * = medium, o/O = bright, # = very bright")
    print("        R/G/B = red/green/blue, Y/M/C = yellow/magenta/cyan, W = white")
    print()

    # Top edge numbers
    print("     ", end="")
    for i in range(0, top_count, 10):
        print(f"{i:2d}        ", end="")
    print()

    # Top edge (left to right)
    print("Top: ", end="")
    for i in range(top_count):
        r, g, b = colors[i]
        char = rgb_to_char(r, g, b)
        print(char, end="")
    print()
    print()

    # Middle section with left and right edges
    right_start = top_count
    bottom_start = top_count + right_count
    left_start = bottom_start + bottom_count

    for i in range(right_count):
        # Left edge LED (going bottom to top)
        left_idx = left_start + (left_count - 1 - i)
        if left_idx < len(colors):
            r, g, b = colors[left_idx]
            char = rgb_to_char(r, g, b)
            print(f"L{i:2d}: {char}", end="")
        else:
            print("     ", end="")

        # Spacing for middle
        print(" " * (top_count - 10), end="")

        # Right edge LED (going top to bottom)
        right_idx = right_start + i
        if right_idx < len(colors):
            r, g, b = colors[right_idx]
            char = rgb_to_char(r, g, b)
            print(f" {char} :R{i:2d}")
        else:
            print()

    print()

    # Bottom edge numbers
    print("     ", end="")
    for i in range(0, bottom_count, 10):
        print(f"{i:2d}        ", end="")
    print()

    # Bottom edge (right to left)
    print("Bot: ", end="")
    for i in range(bottom_count):
        bottom_idx = bottom_start + (bottom_count - 1 - i)
        if bottom_idx < len(colors):
            r, g, b = colors[bottom_idx]
            char = rgb_to_char(r, g, b)
            print(char, end="")
    print()

def analyze_colors_ascii(colors: List[Tuple[int, int, int]]):
    """Analyze and display color distribution"""
    if not colors:
        return

    # Count unique colors
    unique_colors = set(colors)

    # Calculate brightness distribution
    brightnesses = [rgb_to_brightness(r, g, b) for r, g, b in colors]
    avg_brightness = sum(brightnesses) / len(brightnesses)

    # Count brightness levels
    brightness_counts = {
        'black': sum(1 for b in brightnesses if b < 5),
        'very_dark': sum(1 for b in brightnesses if 5 <= b < 30),
        'dark': sum(1 for b in brightnesses if 30 <= b < 80),
        'medium': sum(1 for b in brightnesses if 80 <= b < 150),
        'bright': sum(1 for b in brightnesses if 150 <= b < 220),
        'very_bright': sum(1 for b in brightnesses if b >= 220)
    }

    # Find most common colors
    color_counts = {}
    for color in colors:
        color_counts[color] = color_counts.get(color, 0) + 1

    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)

    print(f"\n📊 Color Analysis:")
    print(f"   Total LEDs: {len(colors)}")
    print(f"   Unique colors: {len(unique_colors)}")
    print(f"   Average brightness: {avg_brightness:.1f}")
    print()

    print(f"   Brightness distribution:")
    for level, count in brightness_counts.items():
        if count > 0:
            percentage = (count / len(colors)) * 100
            print(f"      {level:12s}: {count:3d} LEDs ({percentage:4.1f}%)")
    print()

    print(f"   Most common colors:")
    for i, ((r, g, b), count) in enumerate(sorted_colors[:10]):
        percentage = (count / len(colors)) * 100
        char = rgb_to_char(r, g, b)
        brightness = rgb_to_brightness(r, g, b)
        print(f"      {i+1}. [{char}] RGB({r:3d},{g:3d},{b:3d}) brightness={brightness:5.1f}: {count:3d} LEDs ({percentage:4.1f}%)")

def visualize_frame(file_path: str, frame_number: int = 0):
    """Visualize a specific frame from UDP file"""
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🎬 File: {Path(file_path).name}")
    print(f"📍 Frame: {frame_number}")
    print("=" * 80)

    try:
        with open(file_path, 'rb') as f:
            current_frame = 0

            while True:
                timestamp, packet = read_udp_packet(f)

                if timestamp is None:
                    break

                if current_frame == frame_number:
                    colors = parse_udp_packet(packet)

                    print(f"⏰ Timestamp: {timestamp:.2f}s")
                    print()

                    visualize_led_rectangle_ascii(colors)
                    analyze_colors_ascii(colors)
                    return

                current_frame += 1

            print(f"❌ Frame {frame_number} not found (file has {current_frame} frames)")

    except Exception as e:
        print(f"❌ Error reading file: {e}")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Simple UDP Color Visualizer (ASCII)")
        print("===================================")
        print()
        print("Usage: python3 simple-udp-visualizer.py <udp_file> [frame_number]")
        print()
        print("Example: python3 simple-udp-visualizer.py data.udpdata 5")
        return

    file_path = sys.argv[1]
    frame_number = 0

    if len(sys.argv) > 2:
        try:
            frame_number = int(sys.argv[2])
        except ValueError:
            print(f"❌ Invalid frame number: {sys.argv[2]}")
            return

    visualize_frame(file_path, frame_number)

if __name__ == "__main__":
    main()
