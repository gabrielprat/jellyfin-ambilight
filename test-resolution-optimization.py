#!/usr/bin/env python3
"""
Test different frame extraction resolutions to optimize for LED count
Compare current 320x240 vs LED-optimized resolution
"""

import os
import sys
import time
import subprocess
import numpy as np
import cv2

# Import local modules
sys.path.append('/app')

# LED Configuration
TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
BOTTOM_LED_COUNT = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
LEFT_LED_COUNT = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
RIGHT_LED_COUNT = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))
INPUT_POSITION = int(os.getenv('AMBILIGHT_INPUT_POSITION', '46'))

# Current settings
CURRENT_WIDTH = int(os.getenv('FRAME_EXTRACT_WIDTH', '320'))
CURRENT_HEIGHT = int(os.getenv('FRAME_EXTRACT_HEIGHT', '240'))

def calculate_optimal_resolution():
    """Calculate optimal resolution based on LED layout"""
    # For a rectangular layout, we want resolution that matches LED density
    # The perimeter LEDs form a rectangle, so we can map this efficiently

    total_leds = TOP_LED_COUNT + BOTTOM_LED_COUNT + LEFT_LED_COUNT + RIGHT_LED_COUNT

    # Option 1: Direct LED mapping (rectangular)
    led_width = max(TOP_LED_COUNT, BOTTOM_LED_COUNT)
    led_height = max(LEFT_LED_COUNT, RIGHT_LED_COUNT)

    # Option 2: Proportional to current aspect ratio
    current_aspect = CURRENT_WIDTH / CURRENT_HEIGHT  # 320/240 = 1.33

    # Calculate proportional LED resolution maintaining aspect ratio
    if led_width / led_height > current_aspect:
        # Width-limited
        prop_width = led_width
        prop_height = int(led_width / current_aspect)
    else:
        # Height-limited
        prop_height = led_height
        prop_width = int(led_height * current_aspect)

    return {
        'current': (CURRENT_WIDTH, CURRENT_HEIGHT),
        'led_direct': (led_width, led_height),
        'led_proportional': (prop_width, prop_height),
        'led_square': (int(total_leds**0.5), int(total_leds**0.5)),
    }

def extract_frame_with_resolution(video_path, timestamp, width, height):
    """Extract frame at specific resolution"""
    try:
        cmd = [
            'ffmpeg', '-y', '-v', 'quiet',
            '-ss', str(timestamp),
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={width}:{height}',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            'pipe:1'
        ]

        result = subprocess.run(cmd, capture_output=True, check=True)

        if result.returncode == 0 and result.stdout:
            frame_data = np.frombuffer(result.stdout, dtype=np.uint8)
            expected_size = height * width * 3
            if len(frame_data) == expected_size:
                img = frame_data.reshape((height, width, 3))
                return img
        return None

    except Exception as e:
        print(f"⚠️  Error extracting frame: {e}")
        return None

def calculate_led_positions():
    """Calculate LED positions"""
    positions = []

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
    total_leds = len(positions)
    if INPUT_POSITION > 0:
        offset = INPUT_POSITION % total_leds
        positions = positions[offset:] + positions[:offset]

    return positions

def extract_led_colors_optimized(img_array):
    """Extract LED colors with optimized sampling for low resolution"""
    if img_array is None:
        return None

    height, width = img_array.shape[:2]
    led_positions = calculate_led_positions()
    led_colors = []

    # For very low resolution, use minimal border sampling
    border_size = max(0.1, 2.0 / min(width, height))  # Adaptive border size

    for pos in led_positions:
        x, y = pos
        center_x = int(x * width)
        center_y = int(y * height)

        # For low res, use single pixel or small region
        if width <= 100 or height <= 100:
            # Single pixel sampling for very low resolution
            pixel_x = min(center_x, width - 1)
            pixel_y = min(center_y, height - 1)
            color = img_array[pixel_y, pixel_x]
            led_colors.append([int(color[0]), int(color[1]), int(color[2])])
        else:
            # Small region sampling
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
                x1 = max(0, center_x - 1)
                x2 = min(width, center_x + 1)
                y1 = max(0, center_y - 1)
                y2 = min(height, center_y + 1)

            if x2 <= x1 or y2 <= y1:
                led_colors.append([0, 0, 0])
            else:
                region = img_array[y1:y2, x1:x2]
                avg_color = np.mean(region, axis=(0, 1))
                led_colors.append([int(avg_color[0]), int(avg_color[1]), int(avg_color[2])])

    return led_colors

def benchmark_resolution(video_path, timestamp, resolution_name, width, height, iterations=5):
    """Benchmark frame extraction and processing at specific resolution"""
    print(f"\n🧪 Testing {resolution_name}: {width}×{height}")

    extraction_times = []
    processing_times = []
    pixel_count = width * height

    for i in range(iterations):
        # Time frame extraction
        start_time = time.time()
        img_array = extract_frame_with_resolution(video_path, timestamp, width, height)
        extraction_time = time.time() - start_time
        extraction_times.append(extraction_time)

        if img_array is not None:
            # Time LED color processing
            start_time = time.time()
            led_colors = extract_led_colors_optimized(img_array)
            processing_time = time.time() - start_time
            processing_times.append(processing_time)
        else:
            processing_times.append(float('inf'))

    avg_extraction = sum(extraction_times) / len(extraction_times)
    avg_processing = sum(processing_times) / len(processing_times)
    total_time = avg_extraction + avg_processing

    print(f"   📊 Results:")
    print(f"      Pixels: {pixel_count:,}")
    print(f"      Extraction: {avg_extraction*1000:.1f}ms")
    print(f"      Processing: {avg_processing*1000:.1f}ms")
    print(f"      Total: {total_time*1000:.1f}ms")
    print(f"      Throughput: {pixel_count/total_time:,.0f} pixels/sec")

    return {
        'resolution': (width, height),
        'pixel_count': pixel_count,
        'extraction_time': avg_extraction,
        'processing_time': avg_processing,
        'total_time': total_time,
        'throughput': pixel_count / total_time if total_time > 0 else 0
    }

def test_color_accuracy(video_path, timestamp):
    """Test if lower resolution affects color accuracy"""
    print(f"\n🎨 Color Accuracy Test")

    resolutions = calculate_optimal_resolution()

    # Extract at different resolutions
    reference_img = extract_frame_with_resolution(video_path, timestamp,
                                                resolutions['current'][0],
                                                resolutions['current'][1])

    test_img = extract_frame_with_resolution(video_path, timestamp,
                                           resolutions['led_direct'][0],
                                           resolutions['led_direct'][1])

    if reference_img is not None and test_img is not None:
        ref_colors = extract_led_colors_optimized(reference_img)
        test_colors = extract_led_colors_optimized(test_img)

        if ref_colors and test_colors and len(ref_colors) == len(test_colors):
            # Calculate color differences
            total_diff = 0
            max_diff = 0

            for i, (ref, test) in enumerate(zip(ref_colors, test_colors)):
                # Calculate Euclidean distance in RGB space
                diff = ((ref[0] - test[0])**2 + (ref[1] - test[1])**2 + (ref[2] - test[2])**2)**0.5
                total_diff += diff
                max_diff = max(max_diff, diff)

            avg_diff = total_diff / len(ref_colors)

            print(f"   📏 Color Difference Analysis:")
            print(f"      Average difference: {avg_diff:.1f} (RGB units)")
            print(f"      Maximum difference: {max_diff:.1f} (RGB units)")
            print(f"      Accuracy: {max(0, 100 - avg_diff/2.55):.1f}%")

            if avg_diff < 10:
                print("   ✅ Excellent color accuracy")
            elif avg_diff < 25:
                print("   ✅ Good color accuracy")
            elif avg_diff < 50:
                print("   ⚠️  Acceptable color accuracy")
            else:
                print("   ❌ Poor color accuracy")

def main():
    video_path = "/app/test/Sonic.The.Hedgehog.3.2024.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv"

    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}")
        return

    timestamp = 60  # Test at 60 seconds

    print("🚀 Frame Resolution Optimization Analysis")
    print(f"🎬 Video: {os.path.basename(video_path)}")
    print(f"💡 LED Configuration: T:{TOP_LED_COUNT} R:{RIGHT_LED_COUNT} B:{BOTTOM_LED_COUNT} L:{LEFT_LED_COUNT}")
    print("=" * 60)

    # Calculate different resolution options
    resolutions = calculate_optimal_resolution()

    print(f"📐 Resolution Options:")
    for name, (w, h) in resolutions.items():
        efficiency = (TOP_LED_COUNT + BOTTOM_LED_COUNT + LEFT_LED_COUNT + RIGHT_LED_COUNT) / (w * h)
        print(f"   {name.ljust(15)}: {w:3d}×{h:3d} = {w*h:5,} pixels (efficiency: {efficiency:.3f})")

    # Benchmark each resolution
    results = []
    for name, (width, height) in resolutions.items():
        try:
            result = benchmark_resolution(video_path, timestamp, name, width, height)
            result['name'] = name
            results.append(result)
        except Exception as e:
            print(f"   ❌ Failed: {e}")

    # Performance comparison
    if results:
        print(f"\n🏁 Performance Comparison:")
        print("-" * 60)

        # Sort by total time (fastest first)
        results.sort(key=lambda x: x['total_time'])

        baseline = next((r for r in results if r['name'] == 'current'), results[0])

        for result in results:
            speedup = baseline['total_time'] / result['total_time'] if result['total_time'] > 0 else float('inf')
            print(f"   {result['name'].ljust(15)}: {result['total_time']*1000:6.1f}ms "
                  f"({speedup:.1f}x {'faster' if speedup > 1 else 'slower'})")

        # Best option
        best = results[0]
        pixel_reduction = (1 - best['pixel_count'] / baseline['pixel_count']) * 100

        print(f"\n🎯 Recommendation:")
        print(f"   Best option: {best['name']} ({best['resolution'][0]}×{best['resolution'][1]})")
        print(f"   Speed improvement: {baseline['total_time']/best['total_time']:.1f}x faster")
        print(f"   Pixel reduction: {pixel_reduction:.1f}%")
        print(f"   Storage savings: {pixel_reduction:.1f}%")

    # Test color accuracy
    test_color_accuracy(video_path, timestamp)

    print(f"\n💡 Implementation Recommendation:")
    best_option = resolutions['led_direct']
    print(f"   Set FRAME_EXTRACT_WIDTH={best_option[0]}")
    print(f"   Set FRAME_EXTRACT_HEIGHT={best_option[1]}")
    print(f"   Expected benefits:")
    print(f"   - {(CURRENT_WIDTH*CURRENT_HEIGHT)/(best_option[0]*best_option[1]):.1f}x fewer pixels to process")
    print(f"   - {(CURRENT_WIDTH*CURRENT_HEIGHT)/(best_option[0]*best_option[1]):.1f}x faster frame processing")
    print(f"   - {((CURRENT_WIDTH*CURRENT_HEIGHT)-(best_option[0]*best_option[1]))/(CURRENT_WIDTH*CURRENT_HEIGHT)*100:.1f}% storage reduction")

if __name__ == "__main__":
    main()
