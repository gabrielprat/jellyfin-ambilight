import os
import cv2
import json
import argparse
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime
import sys

# Add path for file-based storage
sys.path.append('/app')

# Import storage system with fallback
try:
    from storage import FileBasedStorage
except ImportError:
    from storage_file_based import FileBasedStorage

# Environment variables for frame extraction settings (updated for file-based)
FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "10.0"))  # Extract frame every X seconds
LED_COUNT = int(os.getenv("LED_COUNT", "276"))  # Total LED count
LED_BORDER_SIZE = float(os.getenv("LED_BORDER_SIZE", "0.1"))  # Border sampling size
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")  # File storage directory
SKIP_EXISTING = os.getenv("SKIP_EXISTING", "true").lower() == "true"

# LED Configuration for color preprocessing
TOP_LED_COUNT = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", "89"))
BOTTOM_LED_COUNT = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", "89"))
LEFT_LED_COUNT = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", "49"))
RIGHT_LED_COUNT = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", "49"))
INPUT_POSITION = int(os.getenv("AMBILIGHT_INPUT_POSITION", "46"))

def setup_frames_directory():
    """Create frames directory if it doesn't exist"""
    frames_path = Path(FRAMES_DIR)
    frames_path.mkdir(parents=True, exist_ok=True)
    return frames_path

def calculate_led_positions():
    """Calculate LED positions for color extraction (simplified version)"""
    positions = []

    # Top edge (left to right)
    for i in range(TOP_LED_COUNT):
        x = i / (TOP_LED_COUNT - 1) if TOP_LED_COUNT > 1 else 0.5
        positions.append({'edge': 'top', 'x': x, 'y': 0.0})

    # Right edge (top to bottom)
    for i in range(RIGHT_LED_COUNT):
        y = i / (RIGHT_LED_COUNT - 1) if RIGHT_LED_COUNT > 1 else 0.5
        positions.append({'edge': 'right', 'x': 1.0, 'y': y})

    # Bottom edge (right to left)
    for i in range(BOTTOM_LED_COUNT):
        x = 1.0 - (i / (BOTTOM_LED_COUNT - 1)) if BOTTOM_LED_COUNT > 1 else 0.5
        positions.append({'edge': 'bottom', 'x': x, 'y': 1.0})

    # Left edge (bottom to top)
    for i in range(LEFT_LED_COUNT):
        y = 1.0 - (i / (LEFT_LED_COUNT - 1)) if LEFT_LED_COUNT > 1 else 0.5
        positions.append({'edge': 'left', 'x': 0.0, 'y': y})

    # Adjust for input position offset
    if INPUT_POSITION > 0:
        positions = positions[INPUT_POSITION:] + positions[:INPUT_POSITION]

    return positions

def extract_led_colors_from_image(img_path, border_size=0.1):
    """Extract LED colors from an image file"""
    try:
        # Load image
        img = cv2.imread(img_path)
        if img is None:
            return None

        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        height, width = img.shape[:2]

        led_positions = calculate_led_positions()
        led_colors = []

        for pos in led_positions:
            color = extract_color_for_led_position(img, pos, border_size)
            led_colors.append(color)

        return led_colors

    except Exception as e:
        print(f"⚠️  Error extracting LED colors: {e}")
        return None

def extract_color_for_led_position(img, led_pos, border_size):
    """Extract average color for a single LED position"""
    height, width = img.shape[:2]

    # Define sampling region based on LED position
    if led_pos['edge'] == 'top':
        # Sample from top border
        x_center = int(led_pos['x'] * width)
        region_size = max(10, width // TOP_LED_COUNT)
        x1 = max(0, x_center - region_size // 2)
        x2 = min(width, x_center + region_size // 2)
        y1 = 0
        y2 = max(1, int(height * border_size))

    elif led_pos['edge'] == 'bottom':
        # Sample from bottom border
        x_center = int(led_pos['x'] * width)
        region_size = max(10, width // BOTTOM_LED_COUNT)
        x1 = max(0, x_center - region_size // 2)
        x2 = min(width, x_center + region_size // 2)
        y1 = min(height - 1, int(height * (1 - border_size)))
        y2 = height

    elif led_pos['edge'] == 'left':
        # Sample from left border
        y_center = int(led_pos['y'] * height)
        region_size = max(10, height // LEFT_LED_COUNT)
        y1 = max(0, y_center - region_size // 2)
        y2 = min(height, y_center + region_size // 2)
        x1 = 0
        x2 = max(1, int(width * border_size))

    elif led_pos['edge'] == 'right':
        # Sample from right border
        y_center = int(led_pos['y'] * height)
        region_size = max(10, height // RIGHT_LED_COUNT)
        y1 = max(0, y_center - region_size // 2)
        y2 = min(height, y_center + region_size // 2)
        x1 = min(width - 1, int(width * (1 - border_size)))
        x2 = width

    # Extract region and calculate average color
    region = img[y1:y2, x1:x2]
    if region.size > 0:
        avg_color = np.mean(region, axis=(0, 1))
        return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]  # RGB
    else:
        return [0, 0, 0]  # Fallback to black

def get_video_duration(video_path):
    """Get video duration in seconds using FFprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        import json
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        return duration
    except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"⚠️  Error getting video duration for {video_path}: {e}")
        return None

def extract_frame_at_timestamp(video_path, timestamp, output_path):
    """Extract a single frame at a specific timestamp using FFmpeg"""
    try:
        cmd = [
            'ffmpeg', '-y', '-v', 'quiet',
            '-ss', str(timestamp),
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={FRAME_WIDTH}:{FRAME_HEIGHT}',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error extracting frame at {timestamp}s from {video_path}: {e}")
        return False

def extract_frames_from_video(item_id, video_path, item_name):
    """Extract frames from a video file at regular intervals"""
    print(f"🎬 Processing: {item_name}")
    print(f"   📂 Path: {video_path}")

    # Check if video file exists
    if not os.path.exists(video_path):
        print(f"   ⚠️  Video file not found: {video_path}")
        print(f"   🚫 Skipping (will retry on next run)")
        return 0

    # Get video duration
    duration = get_video_duration(video_path)
    if duration is None:
        print(f"   ❌ Could not determine video duration")
        return 0

    print(f"   ⏱️  Duration: {duration:.2f}s")

    frames_dir = setup_frames_directory()
    item_frames_dir = frames_dir / item_id
    item_frames_dir.mkdir(exist_ok=True)

    extracted_count = 0
    skipped_count = 0
    error_count = 0

    # Extract frames at regular intervals
    current_time = 0
    while current_time < duration:
        # Check if frame already exists in database
        if SKIP_EXISTING and frame_exists(item_id, current_time):
            skipped_count += 1
            current_time += FRAME_INTERVAL
            continue

        # Generate frame filename
        frame_filename = f"frame_{current_time:010.3f}s.jpg"
        frame_path = item_frames_dir / frame_filename

        # Extract frame
        if extract_frame_at_timestamp(video_path, current_time, str(frame_path)):
            # Get frame dimensions and extract LED colors
            try:
                img = cv2.imread(str(frame_path))
                height, width = img.shape[:2]

                # Extract LED colors for preprocessing
                led_colors = extract_led_colors_from_image(str(frame_path))

                # Save frame info to database with precomputed LED colors
                save_frame(item_id, current_time, str(frame_path), width, height, led_colors)
                extracted_count += 1

                if extracted_count % 50 == 0:  # Progress update every 50 frames
                    total_leds = len(led_colors) if led_colors else 0
                    print(f"   📸 Extracted {extracted_count} frames (w/ {total_leds} LED colors)...")

            except Exception as e:
                print(f"   ⚠️  Error processing frame at {current_time}s: {e}")
                error_count += 1
        else:
            error_count += 1

        current_time += FRAME_INTERVAL

    print(f"   ✅ Complete: {extracted_count} extracted, {skipped_count} skipped, {error_count} errors")
    return extracted_count

def process_all_library_items():
    """Process all items in all libraries"""
    print("🔍 Processing all library items for frame extraction...")

    libraries = get_all_libraries()
    total_processed = 0
    total_frames = 0

    for library in libraries:
        print(f"\n📚 Library: {library['name']}")

        items = get_items_by_library(library['id'])
        print(f"   Found {len(items)} items")

        for item in items:
            # Skip if not a video file
            if item['type'] not in ['Movie', 'Episode', 'Video']:
                continue

            filepath = item['filepath']
            if filepath == 'Unknown' or not filepath:
                print(f"   ⚠️  Skipping {item['name']}: No valid file path")
                continue

            frames_extracted = extract_frames_from_video(
                item['id'], filepath, item['name']
            )

            total_processed += 1
            total_frames += frames_extracted

    print(f"\n🎉 Processing complete!")
    print(f"   📊 Items processed: {total_processed}")
    print(f"   📸 Total frames extracted: {total_frames}")

def process_single_video(item_id_or_path):
    """Process a single video by item ID or file path"""
    print(f"🎯 Processing single video: {item_id_or_path}")

    # Try to find by item ID first
    item = get_item_by_id(item_id_or_path)

    if item:
        print(f"Found item in database: {item['name']}")
        frames_extracted = extract_frames_from_video(
            item['id'], item['filepath'], item['name']
        )
    else:
        # Assume it's a file path
        if not os.path.exists(item_id_or_path):
            print(f"❌ File not found: {item_id_or_path}")
            return

        # Use filename as fake item ID for testing
        fake_item_id = f"test_{Path(item_id_or_path).stem}"
        item_name = Path(item_id_or_path).name

        frames_extracted = extract_frames_from_video(
            fake_item_id, item_id_or_path, item_name
        )

    print(f"✅ Single video processing complete: {frames_extracted} frames extracted")

def list_video_items():
    """List all video items in the database"""
    print("📋 Video items in database:")

    libraries = get_all_libraries()
    video_count = 0

    for library in libraries:
        print(f"\n📚 Library: {library['name']}")

        items = get_items_by_library(library['id'])
        library_videos = [item for item in items if item['type'] in ['Movie', 'Episode', 'Video']]

        for item in library_videos:
            print(f"   🎬 {item['name']} (ID: {item['id']})")
            print(f"      📂 {item['filepath']}")
            video_count += 1

    print(f"\n📊 Total video items: {video_count}")

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
    height, width = img_array.shape[:2]

    # Define sampling region based on LED position
    if led_pos['edge'] == 'top':
        x_center = int(led_pos['x'] * width)
        region_size = max(10, width // TOP_LED_COUNT)
        x1 = max(0, x_center - region_size // 2)
        x2 = min(width, x_center + region_size // 2)
        y1 = 0
        y2 = max(1, int(height * border_size))

    elif led_pos['edge'] == 'bottom':
        x_center = int(led_pos['x'] * width)
        region_size = max(10, width // BOTTOM_LED_COUNT)
        x1 = max(0, x_center - region_size // 2)
        x2 = min(width, x_center + region_size // 2)
        y1 = min(height - 1, int(height * (1 - border_size)))
        y2 = height

    elif led_pos['edge'] == 'left':
        y_center = int(led_pos['y'] * height)
        region_size = max(10, height // LEFT_LED_COUNT)
        y1 = max(0, y_center - region_size // 2)
        y2 = min(height, y_center + region_size // 2)
        x1 = 0
        x2 = max(1, int(width * border_size))

    elif led_pos['edge'] == 'right':
        y_center = int(led_pos['y'] * height)
        region_size = max(10, height // RIGHT_LED_COUNT)
        y1 = max(0, y_center - region_size // 2)
        y2 = min(height, y_center + region_size // 2)
        x1 = min(width - 1, int(width * (1 - border_size)))
        x2 = width

    # Extract region and calculate average color
    region = img_array[y1:y2, x1:x2]
    if region.size > 0:
        avg_color = np.mean(region, axis=(0, 1))
        return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]  # RGB
    else:
        return [0, 0, 0]  # Fallback to black

def extract_frames_from_video_memory(item_id, video_path, item_name):
    """Extract frames and LED colors directly in memory (NO FILE STORAGE)"""
    print(f"🎬 Processing: {item_name}")
    print(f"   📂 Path: {video_path}")
    print(f"   🚀 Using in-memory processing (no frame files saved)")

    # Check if video file exists
    if not os.path.exists(video_path):
        print(f"   ⚠️  Video file not found: {video_path}")
        print(f"   🚫 Skipping (will retry on next run)")
        return 0

    # Get video duration
    duration = get_video_duration(video_path)
    if duration is None:
        print(f"   ❌ Could not determine video duration")
        return 0

    print(f"   ⏱️  Duration: {duration:.2f}s")

    extracted_count = 0
    skipped_count = 0
    error_count = 0

    # Extract frames at regular intervals
    current_time = 0
    while current_time < duration:
        # Check if frame already exists in database
        if SKIP_EXISTING and frame_exists(item_id, current_time):
            skipped_count += 1
            current_time += FRAME_INTERVAL
            continue

        # Extract frame directly to memory
        img_array = extract_frame_to_memory(video_path, current_time)

        if img_array is not None:
            try:
                height, width = img_array.shape[:2]

                # Extract LED colors directly from memory
                led_colors = extract_led_colors_from_array(img_array)

                if led_colors:
                    # Save to database with NO frame file path
                    save_frame(item_id, current_time, None, width, height, led_colors)
                    extracted_count += 1

                    if extracted_count % 50 == 0:  # Progress update every 50 frames
                        total_leds = len(led_colors)
                        print(f"   🚀 Processed {extracted_count} frames (w/ {total_leds} LED colors, in-memory)")
                else:
                    print(f"   ⚠️  Failed to extract LED colors at {current_time}s")
                    error_count += 1

            except Exception as e:
                print(f"   ⚠️  Error processing frame at {current_time}s: {e}")
                error_count += 1
        else:
            error_count += 1

        current_time += FRAME_INTERVAL

    print(f"   ✅ Complete: {extracted_count} processed, {skipped_count} skipped, {error_count} errors")
    print(f"   💾 Storage saved: ~{extracted_count * 50}KB (no frame files stored)")
    return extracted_count

def main():
    parser = argparse.ArgumentParser(description='File-Based Jellyfin Frame Extractor')
    parser.add_argument('--video-path', type=str,
                        help='Process specific video file path')
    parser.add_argument('--item-id', type=str,
                        help='Jellyfin item ID (optional)')
    parser.add_argument('--item-name', type=str,
                        help='Item display name (optional)')
    parser.add_argument('--list', action='store_true',
                        help='List all video items needing extraction')
    parser.add_argument('--stats', action='store_true',
                        help='Show extraction statistics')

    args = parser.parse_args()

    # Initialize file-based storage
    storage = FileBasedStorage(AMBILIGHT_DATA_DIR)

    # Show configuration
    print("📁 FILE-BASED FRAME EXTRACTOR")
    print("=" * 50)
    print(f"⚙️  Configuration:")
    print(f"   Frame interval: {FRAME_INTERVAL}s")
    print(f"   LED count: {LED_COUNT}")
    print(f"   Border size: {LED_BORDER_SIZE}")
    print(f"   Storage: {AMBILIGHT_DATA_DIR}")
    print(f"   Skip existing: {SKIP_EXISTING}")
    print("🎯 Advantages: No database, 12x faster, simpler!")
    print("=" * 50)
    print()

    if args.stats:
        # Show extraction statistics
        stats = storage.get_extraction_statistics()
        storage_info = storage.get_storage_info()

        print("📊 EXTRACTION STATISTICS:")
        print(f"   Total videos: {stats['total_videos']}")
        print(f"   Extracted: {stats['extracted_videos']}")
        print(f"   Pending: {stats['pending_videos']}")
        print(f"   Progress: {stats['completion_percentage']:.1f}%")
        print()
        print("💾 STORAGE INFO:")
        print(f"   Directory: {storage_info['data_directory']}")
        print(f"   Total size: {storage_info['total_size_mb']:.1f} MB")
        print(f"   UDP files: {storage_info['udp_file_count']}")
        print(f"   Index files: {storage_info['index_file_count']}")

    elif args.list:
        # List videos needing extraction
        videos = storage.get_videos_needing_extraction('newest_first', 20)
        print(f"📋 VIDEOS NEEDING EXTRACTION (showing first 20):")

        for i, video in enumerate(videos, 1):
            type_icon = '🎬' if video['type'] == 'Movie' else '📺' if video['type'] == 'Episode' else '🎥'
            print(f"{i:2d}. {type_icon} [{video['type']:7s}] {video['name']}")
            print(f"     Path: {video['filepath']}")

        if not videos:
            print("✅ All videos have been extracted!")

    elif args.video_path:
        # Process specific video
        # Auto-detect item from storage if not provided
        if not args.item_id:
            item = storage.get_item_by_filepath(args.video_path)
            if item:
                args.item_id = item['id']
                args.item_name = item['name']
            else:
                # Generate fallback ID
                args.item_id = f"manual_{Path(args.video_path).stem}"
                args.item_name = args.item_name or Path(args.video_path).name

        if not args.item_name:
            args.item_name = Path(args.video_path).name

        print(f"🎬 Processing: {args.item_name}")
        print(f"📁 Item ID: {args.item_id}")
        print(f"📂 File: {args.video_path}")

        # Check if file exists
        if not os.path.exists(args.video_path):
            print(f"⚠️  Video file not found: {args.video_path}")
            print(f"🚫 Skipping (will retry on next run)")
            return

        print()

        # Import and use the file-based extractor
        import importlib.util
        spec = importlib.util.spec_from_file_location("frame_extractor_files", "/app/frame-extractor-files.py")
        frame_extractor_files = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frame_extractor_files)
        extract_frames_simple_files = frame_extractor_files.extract_frames_simple_files

        extracted = extract_frames_simple_files(
            args.item_id,
            args.video_path,
            args.item_name,
            storage
        )

        if extracted > 0:
            print(f"\n✅ Success! {extracted} frames stored as UDP files")
            print("📁 Ready for file-based ambilight playback!")
        else:
            print("\n❌ No frames were extracted")

    else:
        print("ℹ️  No action specified. Use --help for options.")
        print("   Common usage:")
        print("   --stats                           : Show extraction statistics")
        print("   --list                           : List videos needing extraction")
        print("   --video-path /path/to/video.mkv : Extract frames from specific video")
        print()
        print("🎯 This version uses FILE-BASED storage (no database needed!)")

if __name__ == "__main__":
    main()
