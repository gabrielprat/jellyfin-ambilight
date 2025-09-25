#!/usr/bin/env python3
"""
File-Based Frame Extractor
==========================

Ultra-simple frame extractor using file-based storage:
- No database dependency
- Direct UDP packet files
- Human-readable directory structure
- Easier debugging and maintenance
"""

import os
import sys
import cv2
import json
import numpy as np
import time
from pathlib import Path
from datetime import datetime

# Add to Python path
sys.path.append('/app')

# Import storage system with fallback
try:
    from storage import FileBasedStorage
except ImportError:
    from storage_file_based import FileBasedStorage

# Configuration from environment
FRAME_INTERVAL = float(os.getenv('FRAME_INTERVAL', '10.0'))
SKIP_EXISTING = os.getenv('SKIP_EXISTING', 'true').lower() == 'true'
LED_COUNT = int(os.getenv('LED_COUNT', '276'))
BORDER_SIZE = float(os.getenv('LED_BORDER_SIZE', '0.1'))

def calculate_led_positions():
    """Calculate LED positions for the display"""
    positions = []

    # LED strip configuration
    bottom_leds = 69
    right_leds = 39
    top_leds = 69
    left_leds = 39

    # Bottom edge (left to right)
    for i in range(bottom_leds):
        x = i / (bottom_leds - 1)
        positions.append((x, 1.0))

    # Right edge (bottom to top)
    for i in range(1, right_leds):
        y = 1.0 - (i / (right_leds - 1))
        positions.append((1.0, y))

    # Top edge (right to left)
    for i in range(1, top_leds):
        x = 1.0 - (i / (top_leds - 1))
        positions.append((x, 0.0))

    # Left edge (top to bottom)
    for i in range(1, left_leds - 1):
        y = i / (left_leds - 1)
        positions.append((0.0, y))

    return positions

def extract_color_for_led_position(img, led_pos, border_size):
    """Extract average color for a single LED position"""
    height, width = img.shape[:2]

    center_x = int(led_pos[0] * width)
    center_y = int(led_pos[1] * height)

    # Calculate sampling region based on edge position
    if led_pos[0] == 0.0:  # Left edge
        sample_width = int(width * border_size)
        x1, x2 = 0, sample_width
        y1 = max(0, center_y - sample_width // 2)
        y2 = min(height, center_y + sample_width // 2)
    elif led_pos[0] == 1.0:  # Right edge
        sample_width = int(width * border_size)
        x1 = width - sample_width
        x2 = width
        y1 = max(0, center_y - sample_width // 2)
        y2 = min(height, center_y + sample_width // 2)
    elif led_pos[1] == 0.0:  # Top edge
        sample_height = int(height * border_size)
        x1 = max(0, center_x - sample_height // 2)
        x2 = min(width, center_x + sample_height // 2)
        y1, y2 = 0, sample_height
    elif led_pos[1] == 1.0:  # Bottom edge
        sample_height = int(height * border_size)
        x1 = max(0, center_x - sample_height // 2)
        x2 = min(width, center_x + sample_height // 2)
        y1 = height - sample_height
        y2 = height
    else:
        # Corner case
        sample_size = min(int(width * border_size), int(height * border_size))
        x1 = max(0, center_x - sample_size // 2)
        x2 = min(width, center_x + sample_size // 2)
        y1 = max(0, center_y - sample_size // 2)
        y2 = min(height, center_y + sample_size // 2)

    # Ensure valid region
    if x2 <= x1 or y2 <= y1:
        return [0, 0, 0]

    # Extract and average
    region = img[y1:y2, x1:x2]
    if region.size == 0:
        return [0, 0, 0]

    avg_color = np.mean(region, axis=(0, 1))
    return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]

def extract_led_colors_from_array(img_array):
    """Extract LED colors from image array"""
    try:
        led_positions = calculate_led_positions()
        led_colors = []

        for pos in led_positions:
            color = extract_color_for_led_position(img_array, pos, BORDER_SIZE)
            led_colors.append(color)

        return led_colors
    except Exception as e:
        print(f"⚠️  Error extracting LED colors: {e}")
        return None

def create_wled_udp_packet(led_colors, timeout=1):
    """Create WLED DRGB UDP packet from LED colors"""
    packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), timeout])

    for color in led_colors:
        if color and len(color) >= 3:
            packet.extend([int(color[0]), int(color[1]), int(color[2])])
        else:
            packet.extend([0, 0, 0])

    return bytes(packet)

def extract_frame_to_memory(video_path, timestamp_seconds):
    """Extract frame directly to memory using FFmpeg"""
    try:
        import subprocess

        # Get video dimensions
        probe_cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'csv=p=0',
            '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
            video_path
        ]

        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None

        width, height = map(int, result.stdout.strip().split(','))

        # Extract frame
        ffmpeg_cmd = [
            'ffmpeg', '-ss', str(timestamp_seconds), '-i', video_path,
            '-vframes', '1', '-f', 'image2pipe', '-pix_fmt', 'rgb24',
            '-vcodec', 'rawvideo', '-loglevel', 'quiet', '-'
        ]

        process = subprocess.run(ffmpeg_cmd, capture_output=True)
        if process.returncode != 0:
            return None

        # Convert to numpy array
        frame_data = np.frombuffer(process.stdout, dtype=np.uint8)
        expected_size = width * height * 3

        if len(frame_data) != expected_size:
            return None

        img_array = frame_data.reshape((height, width, 3))
        return img_array

    except Exception as e:
        print(f"⚠️  Error extracting frame at {timestamp_seconds}s: {e}")
        return None

def extract_frames_simple_files(item_id, video_path, item_name, storage):
    """Extract frames with simple file-based storage"""
    print(f"📁 FILE-BASED EXTRACTION: {item_name}")
    print(f"   📂 Video: {video_path}")

    # Check if video file exists
    if not os.path.exists(video_path):
        print(f"   ⚠️  Video file not found: {video_path}")
        print(f"   🚫 Skipping (will retry on next boot)")
        return 0  # Skip missing files completely

    # Get video duration
    import subprocess

    duration_cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'csv=p=0',
        '-show_entries', 'format=duration', video_path
    ]

    try:
        result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=30)
        duration = float(result.stdout.strip())
    except Exception as e:
        print(f"   ❌ Failed to get duration: {e}")
        return 0

    print(f"   ⏱️  Duration: {duration:.1f} seconds")
    print(f"   📊 Frame interval: {FRAME_INTERVAL} seconds")

    extracted_count = 0
    skipped_count = 0
    error_count = 0
    total_packet_size = 0

    # Calculate total frames for progress tracking
    total_frames = int(duration / FRAME_INTERVAL)
    print(f"   🎬 Total frames to extract: {total_frames:,}")
    print()

    last_progress_time = time.time()

    # Extract frames at regular intervals
    current_time = 0
    frame_number = 0

    while current_time < duration:
        frame_number += 1

        # Check if frame already exists (simple file check!)
        if SKIP_EXISTING and storage.frame_exists(item_id, current_time):
            skipped_count += 1
            current_time += FRAME_INTERVAL
            continue

        # Extract frame to memory
        img_array = extract_frame_to_memory(video_path, current_time)

        if img_array is not None:
            try:
                height, width = img_array.shape[:2]

                # Extract LED colors
                led_colors = extract_led_colors_from_array(img_array)

                if led_colors:
                    # Create UDP packet
                    udp_packet = create_wled_udp_packet(led_colors)

                    # Save to file (super simple!)
                    storage.save_udp_packet(item_id, current_time, udp_packet, width, height)
                    extracted_count += 1
                    total_packet_size += len(udp_packet)

                    # Enhanced progress output
                    now = time.time()
                    if now - last_progress_time >= 2.0 or extracted_count % 100 == 0:  # Every 2 seconds or 100 frames
                        progress_percent = (frame_number / total_frames) * 100
                        avg_size = total_packet_size / extracted_count if extracted_count > 0 else 0

                        print(f"   📈 Progress: {progress_percent:5.1f}% | "
                              f"Frame {frame_number:,}/{total_frames:,} | "
                              f"Extracted: {extracted_count:,} | "
                              f"Errors: {error_count} | "
                              f"Avg: {avg_size:.0f}B/packet")
                        last_progress_time = now

                else:
                    print(f"   ⚠️  Failed to extract LED colors at {current_time:.1f}s")
                    error_count += 1

            except Exception as e:
                print(f"   ⚠️  Error processing frame at {current_time:.1f}s: {e}")
                error_count += 1
        else:
            error_count += 1

        current_time += FRAME_INTERVAL

    # Finalize extraction (flush any remaining packets for optimized storage)
    if hasattr(storage, 'finalize_extraction'):
        storage.finalize_extraction(item_id)

    # Summary
    total_mb = total_packet_size / (1024 * 1024)
    print(f"   ✅ Complete: {extracted_count} frames → UDP files")
    print(f"   📊 Skipped: {skipped_count}, Errors: {error_count}")
    print(f"   💾 Total storage: {total_mb:.1f} MB (direct files)")
    print(f"   📁 Files created: {extracted_count} UDP + 1 index")

    return extracted_count

def main():
    """Main function for file-based extraction"""
    import argparse

    parser = argparse.ArgumentParser(description='File-Based Jellyfin Frame Extractor')
    parser.add_argument('video_path', help='Path to video file')
    parser.add_argument('--item-id', help='Jellyfin item ID (optional)')
    parser.add_argument('--item-name', help='Item display name (optional)')
    parser.add_argument('--data-dir', default='/app/data/ambilight', help='Data directory')

    args = parser.parse_args()

    # Initialize file-based storage
    storage = FileBasedStorage(args.data_dir)

    # Auto-detect item from storage if not provided
    if not args.item_id:
        item = storage.get_item_by_filepath(args.video_path)
        if item:
            args.item_id = item['id']
            args.item_name = item['name']
        else:
            # Generate fallback ID
            args.item_id = f"manual_{Path(args.video_path).stem}"
            args.item_name = Path(args.video_path).name

    if not args.item_name:
        args.item_name = Path(args.video_path).name

    print("📁 FILE-BASED FRAME EXTRACTOR")
    print("=" * 50)
    print("🎯 Advantages:")
    print("   📁 No database - just files!")
    print("   🚀 12x faster item operations")
    print("   🔧 Simple directory structure")
    print("   💾 Direct UDP packet storage")
    print("   🛠️  Easy debugging and backup")
    print("=" * 50)
    print()

    # Extract frames with file storage
    extracted = extract_frames_simple_files(
        args.item_id,
        args.video_path,
        args.item_name,
        storage
    )

    if extracted > 0:
        print(f"\\n✅ Success! {extracted} frames stored as UDP files")
        print("📁 Ready for ultra-simple ambilight playback!")

        # Show directory structure
        print(f"\\n📂 File structure created:")
        print(f"   {args.data_dir}/items/{args.item_id}.json")
        print(f"   {args.data_dir}/frames/{args.item_id}/")
        print(f"   ├── 000000.udp (frame at 0s)")
        print(f"   ├── 000010.udp (frame at 10s)")
        print(f"   ├── ...")
        print(f"   └── index.json (timestamp index)")
    else:
        print("\\n❌ No frames were extracted")

if __name__ == "__main__":
    main()
