#!/usr/bin/env python3
"""
Black Border Detection Test
==========================

Test black border detection on sample frames to see how it works
before implementing in the main extractor.
"""

import sys
from typing import Tuple, Optional

def detect_black_borders(frame_data: bytes, width: int, height: int,
                        threshold: int = 10) -> Tuple[int, int, int, int]:
    """
    Detect black borders in a frame and return crop coordinates.

    Returns: (top_crop, bottom_crop, left_crop, right_crop)
    These are the number of pixels to crop from each edge.
    """

    def get_pixel_brightness(x: int, y: int) -> float:
        """Get brightness of pixel at (x, y)"""
        if x < 0 or x >= width or y < 0 or y >= height:
            return 0
        idx = (y * width + x) * 3
        r = frame_data[idx]
        g = frame_data[idx + 1]
        b = frame_data[idx + 2]
        return 0.299 * r + 0.587 * g + 0.114 * b

    def is_row_black(y: int, start_x: int = 0, end_x: int = None) -> bool:
        """Check if a horizontal row is mostly black"""
        if end_x is None:
            end_x = width

        black_pixels = 0
        sample_count = 0

        # Sample every 20th pixel for speed (but ensure we sample enough)
        step = max(1, (end_x - start_x) // 50)
        for x in range(start_x, end_x, step):
            if get_pixel_brightness(x, y) <= threshold:
                black_pixels += 1
            sample_count += 1

        # Consider row black if >95% of sampled pixels are black
        return sample_count > 0 and (black_pixels / sample_count) > 0.95

    def is_column_black(x: int, start_y: int = 0, end_y: int = None) -> bool:
        """Check if a vertical column is mostly black"""
        if end_y is None:
            end_y = height

        black_pixels = 0
        sample_count = 0

        # Sample every 20th pixel for speed
        step = max(1, (end_y - start_y) // 50)
        for y in range(start_y, end_y, step):
            if get_pixel_brightness(x, y) <= threshold:
                black_pixels += 1
            sample_count += 1

        # Consider column black if >95% of sampled pixels are black
        return sample_count > 0 and (black_pixels / sample_count) > 0.95

    # Detect top border
    top_crop = 0
    for y in range(min(height // 3, height)):  # Check up to 1/3 of height
        if is_row_black(y):
            top_crop = y + 1
        else:
            break

    # Detect bottom border
    bottom_crop = 0
    for y in range(height - 1, max(height * 2 // 3, 0), -1):  # Check up to 1/3 of height
        if is_row_black(y):
            bottom_crop = height - y
        else:
            break

    # Detect left border (check only the content area, not the top/bottom borders)
    left_crop = 0
    content_top = top_crop
    content_bottom = height - bottom_crop

    for x in range(min(width // 3, width)):  # Check up to 1/3 of width
        if is_column_black(x, content_top, content_bottom):
            left_crop = x + 1
        else:
            break

    # Detect right border
    right_crop = 0
    for x in range(width - 1, max(width * 2 // 3, 0), -1):  # Check up to 1/3 of width
        if is_column_black(x, content_top, content_bottom):
            right_crop = width - x
        else:
            break

    return top_crop, bottom_crop, left_crop, right_crop

def extract_border_colors_with_crop(frame_data: bytes, width: int, height: int,
                                  crop_coords: Tuple[int, int, int, int]) -> bytes:
    """
    Extract border colors from the cropped content area (excluding black borders)
    """
    top_crop, bottom_crop, left_crop, right_crop = crop_coords

    # Calculate content area
    content_left = left_crop
    content_right = width - right_crop
    content_top = top_crop
    content_bottom = height - bottom_crop

    content_width = content_right - content_left
    content_height = content_bottom - content_top

    if content_width <= 0 or content_height <= 0:
        # Fallback to original if crop is too aggressive
        print("⚠️  Crop too aggressive, using original frame")
        return extract_border_colors_original(frame_data, width, height)

    def get_pixel(x: int, y: int) -> tuple:
        """Get RGB values at pixel (x, y) in original frame coordinates"""
        idx = (y * width + x) * 3
        return frame_data[idx], frame_data[idx + 1], frame_data[idx + 2]

    border_pixels = []

    # Top edge of content (left to right)
    for x in range(content_left, content_right):
        border_pixels.extend(get_pixel(x, content_top))

    # Right edge of content (top to bottom)
    for y in range(content_top, content_bottom):
        border_pixels.extend(get_pixel(content_right - 1, y))

    # Bottom edge of content (right to left)
    for x in range(content_right - 1, content_left - 1, -1):
        border_pixels.extend(get_pixel(x, content_bottom - 1))

    # Left edge of content (bottom to top)
    for y in range(content_bottom - 1, content_top - 1, -1):
        border_pixels.extend(get_pixel(content_left, y))

    return bytes(border_pixels)

def extract_border_colors_original(frame_data: bytes, width: int, height: int) -> bytes:
    """Original border extraction (for comparison)"""
    def get_pixel(x: int, y: int) -> tuple:
        """Get RGB values at pixel (x, y)"""
        idx = (y * width + x) * 3
        return frame_data[idx], frame_data[idx + 1], frame_data[idx + 2]

    border_pixels = []

    # Top edge (left to right)
    for x in range(width):
        border_pixels.extend(get_pixel(x, 0))

    # Right edge (top to bottom)
    for y in range(height):
        border_pixels.extend(get_pixel(width - 1, y))

    # Bottom edge (right to left)
    for x in range(width - 1, -1, -1):
        border_pixels.extend(get_pixel(x, height - 1))

    # Left edge (bottom to top)
    for y in range(height - 1, -1, -1):
        border_pixels.extend(get_pixel(0, y))

    return bytes(border_pixels)

def test_border_detection():
    """Test border detection with synthetic frames"""
    print("🧪 Testing Black Border Detection")
    print("=" * 50)

    # Test case 1: Letterbox frame (black top/bottom)
    width, height = 1920, 1080
    letterbox_frame = create_letterbox_frame(width, height, bar_height=135)  # 16:9 content in letterbox

    print("\n📺 Test 1: Letterbox Frame (black top/bottom bars)")
    crop_coords = detect_black_borders(letterbox_frame, width, height)
    print(f"   Detected crops: top={crop_coords[0]}, bottom={crop_coords[1]}, left={crop_coords[2]}, right={crop_coords[3]}")

    # Extract colors both ways
    original_colors = extract_border_colors_original(letterbox_frame, width, height)
    cropped_colors = extract_border_colors_with_crop(letterbox_frame, width, height, crop_coords)

    analyze_color_difference(original_colors, cropped_colors, "Letterbox")

    # Test case 2: Pillarbox frame (black left/right)
    pillarbox_frame = create_pillarbox_frame(width, height, bar_width=240)  # 4:3 content in pillarbox

    print("\n📺 Test 2: Pillarbox Frame (black left/right bars)")
    crop_coords = detect_black_borders(pillarbox_frame, width, height)
    print(f"   Detected crops: top={crop_coords[0]}, bottom={crop_coords[1]}, left={crop_coords[2]}, right={crop_coords[3]}")

    original_colors = extract_border_colors_original(pillarbox_frame, width, height)
    cropped_colors = extract_border_colors_with_crop(pillarbox_frame, width, height, crop_coords)

    analyze_color_difference(original_colors, cropped_colors, "Pillarbox")

    # Test case 3: Full frame (no borders)
    full_frame = create_gradient_frame(width, height)

    print("\n📺 Test 3: Full Frame (no black borders)")
    crop_coords = detect_black_borders(full_frame, width, height)
    print(f"   Detected crops: top={crop_coords[0]}, bottom={crop_coords[1]}, left={crop_coords[2]}, right={crop_coords[3]}")

    original_colors = extract_border_colors_original(full_frame, width, height)
    cropped_colors = extract_border_colors_with_crop(full_frame, width, height, crop_coords)

    analyze_color_difference(original_colors, cropped_colors, "Full Frame")

def create_letterbox_frame(width: int, height: int, bar_height: int) -> bytes:
    """Create a letterbox frame with black top/bottom bars"""
    frame = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 3

            if y < bar_height or y >= height - bar_height:
                # Black bars
                frame[idx] = 0
                frame[idx + 1] = 0
                frame[idx + 2] = 0
            else:
                # Colorful content area
                progress_x = x / width
                progress_y = (y - bar_height) / (height - 2 * bar_height)

                frame[idx] = int(255 * progress_x)      # Red gradient
                frame[idx + 1] = int(255 * progress_y)  # Green gradient
                frame[idx + 2] = int(128)               # Blue constant

    return bytes(frame)

def create_pillarbox_frame(width: int, height: int, bar_width: int) -> bytes:
    """Create a pillarbox frame with black left/right bars"""
    frame = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 3

            if x < bar_width or x >= width - bar_width:
                # Black bars
                frame[idx] = 0
                frame[idx + 1] = 0
                frame[idx + 2] = 0
            else:
                # Colorful content area
                progress_x = (x - bar_width) / (width - 2 * bar_width)
                progress_y = y / height

                frame[idx] = int(255 * (1 - progress_x))  # Red
                frame[idx + 1] = int(255 * progress_y)    # Green
                frame[idx + 2] = int(255 * progress_x)    # Blue

    return bytes(frame)

def create_gradient_frame(width: int, height: int) -> bytes:
    """Create a full gradient frame (no black borders)"""
    frame = bytearray(width * height * 3)

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 3

            progress_x = x / width
            progress_y = y / height

            frame[idx] = int(255 * progress_x)      # Red
            frame[idx + 1] = int(255 * progress_y)  # Green
            frame[idx + 2] = int(128 + 127 * ((progress_x + progress_y) / 2))  # Blue

    return bytes(frame)

def analyze_color_difference(original_colors: bytes, cropped_colors: bytes, test_name: str):
    """Analyze the difference between original and cropped color extraction"""

    def get_color_stats(colors: bytes) -> dict:
        led_count = len(colors) // 3
        unique_colors = set()
        brightness_sum = 0
        black_count = 0

        for i in range(led_count):
            r = colors[i*3]
            g = colors[i*3 + 1]
            b = colors[i*3 + 2]

            unique_colors.add((r, g, b))
            brightness = 0.299 * r + 0.587 * g + 0.114 * b
            brightness_sum += brightness

            if brightness < 5:
                black_count += 1

        return {
            'led_count': led_count,
            'unique_colors': len(unique_colors),
            'avg_brightness': brightness_sum / led_count if led_count > 0 else 0,
            'black_count': black_count,
            'black_percentage': (black_count / led_count * 100) if led_count > 0 else 0
        }

    original_stats = get_color_stats(original_colors)
    cropped_stats = get_color_stats(cropped_colors)

    print(f"   📊 {test_name} Results:")
    print(f"      Original: {original_stats['led_count']} LEDs, {original_stats['unique_colors']} colors, "
          f"brightness {original_stats['avg_brightness']:.1f}, {original_stats['black_percentage']:.1f}% black")
    print(f"      Cropped:  {cropped_stats['led_count']} LEDs, {cropped_stats['unique_colors']} colors, "
          f"brightness {cropped_stats['avg_brightness']:.1f}, {cropped_stats['black_percentage']:.1f}% black")

    # Calculate improvement
    brightness_improvement = cropped_stats['avg_brightness'] - original_stats['avg_brightness']
    black_reduction = original_stats['black_percentage'] - cropped_stats['black_percentage']
    color_improvement = cropped_stats['unique_colors'] - original_stats['unique_colors']

    print(f"      Improvement: brightness +{brightness_improvement:.1f}, black -{black_reduction:.1f}%, colors +{color_improvement}")

if __name__ == "__main__":
    test_border_detection()
