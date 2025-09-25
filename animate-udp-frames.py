#!/usr/bin/env python3
"""
UDP Frame Animation Player
==========================

Plays through all frames in a UDP data file sequentially,
showing the LED colors changing over time like an animation.
"""

import os
import struct
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def rgb_to_char(r: int, g: int, b: int) -> str:
    """Convert RGB to representative character"""
    brightness = 0.299 * r + 0.587 * g + 0.114 * b

    if brightness < 5:
        return ' '   # Black/very dark
    elif r > g and r > b and r > 100:
        return 'R'   # Red dominant
    elif g > r and g > b and g > 100:
        return 'G'   # Green dominant
    elif b > r and b > g and b > 100:
        return 'B'   # Blue dominant
    elif r > 150 and g > 150 and b < 100:
        return 'Y'   # Yellow
    elif r > 150 and g < 100 and b > 150:
        return 'M'   # Magenta
    elif r < 100 and g > 150 and b > 150:
        return 'C'   # Cyan
    elif brightness > 200:
        return 'W'   # White/very bright
    elif brightness < 10:
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

def rgb_to_ansi_bg(r: int, g: int, b: int) -> str:
    """Convert RGB to ANSI background color"""
    return f"\033[48;2;{r};{g};{b}m"

def reset_color() -> str:
    """Reset terminal color"""
    return "\033[0m"

def read_udp_packet(file_handle) -> Tuple[Optional[float], Optional[bytes]]:
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

def display_frame_compact(colors: List[Tuple[int, int, int]], frame_num: int, timestamp: float,
                         display_mode: str = "ascii", width: int = 80):
    """Display a single frame in compact format"""

    if not colors:
        print(f"Frame {frame_num:4d} @ {timestamp:6.2f}s: No data")
        return

    # Frame header
    unique_colors = len(set(colors))
    avg_brightness = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in colors) / len(colors)

    print(f"Frame {frame_num:4d} @ {timestamp:6.2f}s | {len(colors)} LEDs | {unique_colors} colors | brightness {avg_brightness:5.1f}")

    if display_mode == "strip":
        # Single line strip view
        print("Strip: ", end="")
        for i, (r, g, b) in enumerate(colors):
            if i >= width - 10:  # Leave space for header
                print("...")
                break
            if display_mode == "color":
                print(f"{rgb_to_ansi_bg(r, g, b)} {reset_color()}", end="")
            else:
                print(rgb_to_char(r, g, b), end="")
        print()

    elif display_mode == "rectangle" or display_mode == "rect":
        # Compact rectangle view
        top_count = min(89, len(colors) // 4)
        right_count = min(49, len(colors) // 4)
        bottom_count = min(89, len(colors) // 4)
        left_count = min(49, len(colors) // 4)

        # Top edge (abbreviated)
        print("T: ", end="")
        for i in range(min(top_count, 40)):
            r, g, b = colors[i] if i < len(colors) else (0, 0, 0)
            print(rgb_to_char(r, g, b), end="")
        if top_count > 40:
            print("...", end="")
        print()

        # Show just a few middle rows
        for row in range(min(3, right_count)):
            # Left edge
            left_idx = len(colors) - left_count + (left_count - 1 - row)
            l_char = rgb_to_char(*colors[left_idx]) if left_idx < len(colors) else ' '

            # Right edge
            right_idx = top_count + row
            r_char = rgb_to_char(*colors[right_idx]) if right_idx < len(colors) else ' '

            print(f"L:{l_char}" + " " * 35 + f"{r_char}:R")
            print()

        if right_count > 3:
            print("  :" + " " * 35 + ":  ")
            print()

        # Bottom edge (abbreviated)
        bottom_start = top_count + right_count
        print("B: ", end="")
        for i in range(min(bottom_count, 40)):
            bottom_idx = bottom_start + (bottom_count - 1 - i)
            r, g, b = colors[bottom_idx] if bottom_idx < len(colors) else (0, 0, 0)
            print(rgb_to_char(r, g, b), end="")
        if bottom_count > 40:
            print("...", end="")
        print()

    elif display_mode == "summary":
        # Just show color summary
        color_counts = {}
        for color in colors:
            color_counts[color] = color_counts.get(color, 0) + 1

        sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
        print("Top colors: ", end="")
        for i, ((r, g, b), count) in enumerate(sorted_colors[:5]):
            char = rgb_to_char(r, g, b)
            pct = count * 100 // len(colors)
            print(f"{char}({pct}%)", end=" ")
        print()

    print()  # Empty line between frames

def animate_udp_file(file_path: str, fps: float = 2.0, display_mode: str = "ascii",
                    start_frame: int = 0, max_frames: int = None, step: int = 1):
    """Animate through all frames in UDP file"""

    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    delay = 1.0 / fps

    print(f"🎬 Animating: {Path(file_path).name}")
    print(f"⚙️  Settings: {fps} FPS, mode={display_mode}, start={start_frame}, step={step}")
    print(f"🎮 Controls: Ctrl+C to stop")
    print("=" * 80)

    try:
        with open(file_path, 'rb') as f:
            frame_count = 0
            displayed_frames = 0

            # Skip to start frame
            while frame_count < start_frame:
                timestamp, packet = read_udp_packet(f)
                if timestamp is None:
                    print(f"❌ Start frame {start_frame} not found")
                    return
                frame_count += 1

            # Animate frames
            while True:
                timestamp, packet = read_udp_packet(f)

                if timestamp is None:
                    break  # End of file

                if frame_count % step == 0:  # Apply step interval
                    colors = parse_udp_packet(packet)

                    if display_mode != "summary":
                        clear_screen()
                        print(f"🎬 {Path(file_path).name} | Frame {frame_count}/{frame_count + 1000} | {fps} FPS")
                        print("=" * 80)

                    display_frame_compact(colors, frame_count, timestamp, display_mode)

                    displayed_frames += 1

                    # Check max frames limit
                    if max_frames and displayed_frames >= max_frames:
                        break

                    # Sleep for frame rate
                    time.sleep(delay)

                frame_count += 1

        print(f"\n✅ Animation complete: {displayed_frames} frames displayed")

    except KeyboardInterrupt:
        print(f"\n⏹️  Animation stopped by user at frame {frame_count}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

def preview_frames(file_path: str, sample_count: int = 10):
    """Show a preview of frames throughout the file"""

    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🔍 Preview: {Path(file_path).name}")
    print("=" * 80)

    # First, count total frames
    total_frames = 0
    try:
        with open(file_path, 'rb') as f:
            while True:
                timestamp, packet = read_udp_packet(f)
                if timestamp is None:
                    break
                total_frames += 1
    except Exception as e:
        print(f"❌ Error counting frames: {e}")
        return

    print(f"📊 Total frames: {total_frames}")

    if total_frames == 0:
        print("No frames found")
        return

    # Sample frames throughout the file
    sample_indices = []
    if sample_count >= total_frames:
        sample_indices = list(range(total_frames))
    else:
        step = total_frames // sample_count
        sample_indices = [i * step for i in range(sample_count)]

    print(f"🎯 Sampling {len(sample_indices)} frames: {sample_indices}")
    print()

    try:
        with open(file_path, 'rb') as f:
            frame_count = 0

            for target_frame in sample_indices:
                # Seek to target frame
                f.seek(0)  # Reset to beginning
                current_frame = 0

                while current_frame <= target_frame:
                    timestamp, packet = read_udp_packet(f)
                    if timestamp is None:
                        break

                    if current_frame == target_frame:
                        colors = parse_udp_packet(packet)
                        display_frame_compact(colors, current_frame, timestamp, "summary")
                        break

                    current_frame += 1

    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Main function with command line interface"""
    if len(sys.argv) < 2:
        print("UDP Frame Animation Player")
        print("=========================")
        print()
        print("Usage:")
        print("  python3 animate-udp-frames.py <udp_file> [options]")
        print()
        print("Animation modes:")
        print("  --animate [fps] [mode]     Animate all frames (default: 2 fps, ascii mode)")
        print("  --preview [count]          Show sample frames (default: 10 frames)")
        print("  --range start end [step]   Animate specific frame range")
        print()
        print("Display modes:")
        print("  ascii      ASCII characters (default)")
        print("  strip      Single line strip view")
        print("  rectangle  Compact TV border layout")
        print("  summary    Color summary only")
        print()
        print("Examples:")
        print("  python3 animate-udp-frames.py data.udpdata --animate")
        print("  python3 animate-udp-frames.py data.udpdata --animate 5 rectangle")
        print("  python3 animate-udp-frames.py data.udpdata --preview 20")
        print("  python3 animate-udp-frames.py data.udpdata --range 100 200 5")
        return

    file_path = sys.argv[1]

    # Parse arguments
    if len(sys.argv) == 2 or (len(sys.argv) > 2 and sys.argv[2] == "--animate"):
        # Default animation
        fps = 10
        mode = "ascii"

        if len(sys.argv) > 3:
            try:
                fps = float(sys.argv[3])
            except ValueError:
                mode = sys.argv[3]

        if len(sys.argv) > 4:
            mode = sys.argv[4]

        animate_udp_file(file_path, fps, mode)

    elif len(sys.argv) > 2 and sys.argv[2] == "--preview":
        count = 10
        if len(sys.argv) > 3:
            try:
                count = int(sys.argv[3])
            except ValueError:
                print(f"❌ Invalid preview count: {sys.argv[3]}")
                return

        preview_frames(file_path, count)

    elif len(sys.argv) > 4 and sys.argv[2] == "--range":
        try:
            start = int(sys.argv[3])
            end = int(sys.argv[4])
            step = 1
            if len(sys.argv) > 5:
                step = int(sys.argv[5])

            max_frames = end - start + 1
            animate_udp_file(file_path, fps=2.0, start_frame=start, max_frames=max_frames, step=step)

        except ValueError:
            print(f"❌ Invalid range parameters")
            return

    else:
        print(f"❌ Unknown option: {sys.argv[2]}")
        print("Use --animate, --preview, or --range")

if __name__ == "__main__":
    main()
