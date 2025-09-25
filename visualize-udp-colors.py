#!/usr/bin/env python3
"""
UDP Color Visualizer
===================

Reads UDP data files and displays colored dots on screen to visualize
the actual LED colors being extracted from video frames.
"""

import os
import struct
import sys
from pathlib import Path
from typing import List, Tuple

def rgb_to_ansi(r: int, g: int, b: int) -> str:
    """Convert RGB values to ANSI color escape sequence"""
    return f"\033[48;2;{r};{g};{b}m"

def reset_color() -> str:
    """Reset terminal color"""
    return "\033[0m"

def print_colored_dot(r: int, g: int, b: int):
    """Print a colored dot (space character with background color)"""
    print(f"{rgb_to_ansi(r, g, b)}  {reset_color()}", end="")

def read_udp_packet(file_handle, expected_timestamp: float = None) -> Tuple[float, bytes]:
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

def visualize_led_strip(colors: List[Tuple[int, int, int]], width: int = 80):
    """Visualize LED strip as colored dots"""
    led_count = len(colors)

    if led_count == 0:
        print("No LED data found")
        return

    print(f"💡 {led_count} LEDs:")

    # Calculate LEDs per row
    leds_per_row = min(width // 2, led_count)  # 2 chars per LED (dot + space)

    for i in range(0, led_count, leds_per_row):
        row_colors = colors[i:i + leds_per_row]

        # Print LED numbers (every 10th)
        print("   ", end="")
        for j, _ in enumerate(row_colors):
            led_num = i + j
            if led_num % 10 == 0:
                print(f"{led_num:2d}", end="")
            else:
                print("  ", end="")
        print()

        # Print colored dots
        print("   ", end="")
        for r, g, b in row_colors:
            print_colored_dot(r, g, b)
        print()  # New line after each row
        print()  # Extra space between rows

def visualize_led_rectangle(colors: List[Tuple[int, int, int]],
                          top_count: int = 89, right_count: int = 49,
                          bottom_count: int = 89, left_count: int = 49):
    """Visualize LEDs as a rectangle (TV border layout)"""
    if len(colors) < (top_count + right_count + bottom_count + left_count):
        print("⚠️  Not enough LED data for rectangle layout")
        visualize_led_strip(colors)
        return

    print(f"📺 TV Border Layout ({top_count}+{right_count}+{bottom_count}+{left_count} = {len(colors)} LEDs):")
    print()

    # Top edge (left to right)
    print("   Top:", end=" ")
    for i in range(top_count):
        r, g, b = colors[i]
        print_colored_dot(r, g, b)
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
            print("      ", end="")
            print_colored_dot(r, g, b)

        # Spacing
        print("  " * (top_count - 2), end="")

        # Right edge LED (going top to bottom)
        right_idx = right_start + i
        if right_idx < len(colors):
            r, g, b = colors[right_idx]
            print_colored_dot(r, g, b)

        print()

    print()
    # Bottom edge (right to left)
    print("Bottom:", end=" ")
    for i in range(bottom_count):
        bottom_idx = bottom_start + (bottom_count - 1 - i)
        if bottom_idx < len(colors):
            r, g, b = colors[bottom_idx]
            print_colored_dot(r, g, b)
    print()

def analyze_colors(colors: List[Tuple[int, int, int]]):
    """Analyze color distribution"""
    if not colors:
        return

    # Count unique colors
    unique_colors = set(colors)

    # Calculate brightness
    brightnesses = [(r + g + b) / 3 for r, g, b in colors]
    avg_brightness = sum(brightnesses) / len(brightnesses)

    # Find most common colors
    color_counts = {}
    for color in colors:
        color_counts[color] = color_counts.get(color, 0) + 1

    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)

    print(f"\n📊 Color Analysis:")
    print(f"   Total LEDs: {len(colors)}")
    print(f"   Unique colors: {len(unique_colors)}")
    print(f"   Average brightness: {avg_brightness:.1f}")

    print(f"   Most common colors:")
    for i, ((r, g, b), count) in enumerate(sorted_colors[:5]):
        percentage = (count / len(colors)) * 100
        print(f"      {i+1}. ", end="")
        print_colored_dot(r, g, b)
        print(f" RGB({r:3d},{g:3d},{b:3d}): {count:3d} LEDs ({percentage:4.1f}%)")

def visualize_udp_file(file_path: str, frame_number: int = 0, layout: str = "strip"):
    """Visualize a specific frame from UDP file"""
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🎬 Visualizing: {Path(file_path).name}")
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

                    if layout == "rectangle":
                        visualize_led_rectangle(colors)
                    else:
                        visualize_led_strip(colors)

                    analyze_colors(colors)
                    return

                current_frame += 1

            print(f"❌ Frame {frame_number} not found (file has {current_frame} frames)")

    except Exception as e:
        print(f"❌ Error reading file: {e}")

def list_frames(file_path: str, max_frames: int = 10):
    """List available frames in UDP file"""
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"📋 Frames in {Path(file_path).name}:")

    try:
        with open(file_path, 'rb') as f:
            frame_count = 0

            while frame_count < max_frames:
                timestamp, packet = read_udp_packet(f)

                if timestamp is None:
                    break

                colors = parse_udp_packet(packet)
                unique_colors = len(set(colors)) if colors else 0
                avg_brightness = sum((r+g+b)/3 for r,g,b in colors) / len(colors) if colors else 0

                print(f"   Frame {frame_count}: {timestamp:6.2f}s - {len(colors)} LEDs, {unique_colors} colors, brightness {avg_brightness:.1f}")

                frame_count += 1

            # Count remaining frames
            remaining = 0
            while True:
                timestamp, packet = read_udp_packet(f)
                if timestamp is None:
                    break
                remaining += 1

            total_frames = frame_count + remaining
            print(f"\n📊 Total frames: {total_frames}")
            if remaining > 0:
                print(f"   (showing first {frame_count}, {remaining} more available)")

    except Exception as e:
        print(f"❌ Error reading file: {e}")

def main():
    """Main function with command line interface"""
    if len(sys.argv) < 2:
        print("UDP Color Visualizer")
        print("===================")
        print()
        print("Usage:")
        print("  python3 visualize-udp-colors.py <udp_file> [frame_number] [layout]")
        print("  python3 visualize-udp-colors.py <udp_file> --list")
        print()
        print("Arguments:")
        print("  udp_file      Path to .udpdata file")
        print("  frame_number  Frame to visualize (default: 0)")
        print("  layout        'strip' or 'rectangle' (default: strip)")
        print("  --list        List all frames in file")
        print()
        print("Examples:")
        print("  python3 visualize-udp-colors.py data.udpdata")
        print("  python3 visualize-udp-colors.py data.udpdata 5 rectangle")
        print("  python3 visualize-udp-colors.py data.udpdata --list")
        return

    file_path = sys.argv[1]

    if len(sys.argv) > 2 and sys.argv[2] == "--list":
        list_frames(file_path)
        return

    frame_number = 0
    if len(sys.argv) > 2:
        try:
            frame_number = int(sys.argv[2])
        except ValueError:
            print(f"❌ Invalid frame number: {sys.argv[2]}")
            return

    layout = "strip"
    if len(sys.argv) > 3:
        layout = sys.argv[3]
        if layout not in ["strip", "rectangle"]:
            print(f"❌ Invalid layout: {layout} (use 'strip' or 'rectangle')")
            return

    # Check terminal color support
    if not sys.stdout.isatty():
        print("⚠️  Terminal may not support colors properly")

    visualize_udp_file(file_path, frame_number, layout)

if __name__ == "__main__":
    main()
