"""
Ultra-Fast Frame Extractor - Pure Python (No NumPy!)
====================================================

Zero external dependencies except Python standard library!
- No NumPy → Pure Python with struct
- No OpenCV → Direct ffmpeg pipe
- No complex image processing libraries

Total image size: ~30MB instead of 2GB!
"""

import os
import subprocess
import struct
import sys
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Config from env
TOP = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", 89))
BOTTOM = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", 89))
LEFT = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", 49))
RIGHT = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", 49))
FPS = float(os.getenv("FRAMES_PER_SECOND", 10))
INPUT_POSITION = int(os.getenv("AMBILIGHT_INPUT_POSITION", 46))
EXPECTED_LED_COUNT = TOP + BOTTOM + LEFT + RIGHT
WLED_LED_COUNT = int(os.getenv('WLED_LED_COUNT', '300'))
WLED_UDP_TIMEOUT = int(os.getenv('WLED_UDP_TIMEOUT', '255'))


def _get_video_duration(filename: str) -> float:
    """Get video duration using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "json", filename
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout or '{}')
    return float(info.get("format", {}).get("duration", 0.0))


def _detect_black_borders_pure(frame_bytes: bytes, width: int, height: int, threshold: int = 10) -> tuple:
    """
    Detect black borders and return crop coordinates.
    Returns: (top_crop, bottom_crop, left_crop, right_crop)
    """
    def get_pixel_brightness(x: int, y: int) -> float:
        """Get brightness of pixel at (x, y)"""
        if x < 0 or x >= width or y < 0 or y >= height:
            return 0
        idx = (y * width + x) * 3
        r = frame_bytes[idx]
        g = frame_bytes[idx + 1]
        b = frame_bytes[idx + 2]
        return 0.299 * r + 0.587 * g + 0.114 * b

    def is_row_black(y: int, start_x: int = 0, end_x: int = None) -> bool:
        """Check if a horizontal row is mostly black"""
        if end_x is None:
            end_x = width

        black_pixels = 0
        sample_count = 0
        step = max(1, (end_x - start_x) // 50)

        for x in range(start_x, end_x, step):
            if get_pixel_brightness(x, y) <= threshold:
                black_pixels += 1
            sample_count += 1

        return sample_count > 0 and (black_pixels / sample_count) > 0.95

    def is_column_black(x: int, start_y: int = 0, end_y: int = None) -> bool:
        """Check if a vertical column is mostly black"""
        if end_y is None:
            end_y = height

        black_pixels = 0
        sample_count = 0
        step = max(1, (end_y - start_y) // 50)

        for y in range(start_y, end_y, step):
            if get_pixel_brightness(x, y) <= threshold:
                black_pixels += 1
            sample_count += 1

        return sample_count > 0 and (black_pixels / sample_count) > 0.95

    # Detect top border
    top_crop = 0
    for y in range(min(height // 3, height)):
        if is_row_black(y):
            top_crop = y + 1
        else:
            break

    # Detect bottom border
    bottom_crop = 0
    for y in range(height - 1, max(height * 2 // 3, 0), -1):
        if is_row_black(y):
            bottom_crop = height - y
        else:
            break

    # Detect left border (check only content area)
    left_crop = 0
    content_top = top_crop
    content_bottom = height - bottom_crop

    for x in range(min(width // 3, width)):
        if is_column_black(x, content_top, content_bottom):
            left_crop = x + 1
        else:
            break

    # Detect right border
    right_crop = 0
    for x in range(width - 1, max(width * 2 // 3, 0), -1):
        if is_column_black(x, content_top, content_bottom):
            right_crop = width - x
        else:
            break

    return top_crop, bottom_crop, left_crop, right_crop

def _extract_border_colors_pure(frame_bytes: bytes, width: int, height: int) -> bytes:
    """
    Extract border colors using pure Python with black border detection!

    Frame format: RGB24, so each pixel = 3 bytes (R, G, B)
    """
    # Check if border detection is enabled
    border_detection_enabled = os.getenv('BLACK_BORDER_DETECTION', 'false').lower() == 'true'
    border_threshold = int(os.getenv('BORDER_THRESHOLD', '10'))

    if not border_detection_enabled:
        return _extract_border_colors_original(frame_bytes, width, height)

    # Detect and crop black borders
    crop_coords = _detect_black_borders_pure(frame_bytes, width, height, border_threshold)
    top_crop, bottom_crop, left_crop, right_crop = crop_coords

    # Calculate content area
    content_left = left_crop
    content_right = width - right_crop
    content_top = top_crop
    content_bottom = height - bottom_crop

    content_width = content_right - content_left
    content_height = content_bottom - content_top

    # If crop is too aggressive, fall back to original method
    if content_width <= width // 4 or content_height <= height // 4:
        return _extract_border_colors_original(frame_bytes, width, height)

    # Log border detection (occasionally)
    import random
    if random.random() < 0.01:  # 1% of frames
        total_crop_area = (top_crop * width) + (bottom_crop * width) + (left_crop * (height - top_crop - bottom_crop)) + (right_crop * (height - top_crop - bottom_crop))
        crop_percentage = (total_crop_area / (width * height)) * 100
        if crop_percentage > 5:  # Only log significant crops
            print(f"🔲 Black border detected: {crop_percentage:.1f}% cropped (T:{top_crop}, B:{bottom_crop}, L:{left_crop}, R:{right_crop})")

    def get_pixel(x: int, y: int) -> tuple:
        """Get RGB values at pixel (x, y) in original frame coordinates"""
        idx = (y * width + x) * 3
        return frame_bytes[idx], frame_bytes[idx + 1], frame_bytes[idx + 2]

    border_pixels = []

    # Extract border from content area (excluding black borders)
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

def _extract_border_colors_original(frame_bytes: bytes, width: int, height: int) -> bytes:
    """
    Original border extraction method (fallback)
    """
    def get_pixel(x: int, y: int) -> tuple:
        """Get RGB values at pixel (x, y)"""
        idx = (y * width + x) * 3
        return frame_bytes[idx], frame_bytes[idx + 1], frame_bytes[idx + 2]

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


def _enhance_brightness_pure(border_bytes: bytes) -> bytes:
    """Enhance brightness for dark content using pure Python"""
    enhanced = bytearray()

    # Calculate average brightness
    total_brightness = 0
    led_count = len(border_bytes) // 3

    for i in range(led_count):
        r = border_bytes[i*3]
        g = border_bytes[i*3 + 1]
        b = border_bytes[i*3 + 2]
        brightness = (r + g + b) / 3
        total_brightness += brightness

    avg_brightness = total_brightness / led_count if led_count > 0 else 0

    # If content is very dark (avg < 30), apply enhancement
    if avg_brightness < 30:
        # Apply gamma correction and minimum brightness
        for i in range(led_count):
            r = border_bytes[i*3]
            g = border_bytes[i*3 + 1]
            b = border_bytes[i*3 + 2]

            # Apply gamma correction (brighten dark colors)
            r = min(255, int((r / 255.0) ** 0.7 * 255))
            g = min(255, int((g / 255.0) ** 0.7 * 255))
            b = min(255, int((b / 255.0) ** 0.7 * 255))

            # Ensure minimum brightness for very dark pixels
            if r + g + b < 15:  # Very dark pixel
                # Add subtle color based on position for ambient effect
                boost = 20
                r = min(255, r + boost)
                g = min(255, g + boost // 2)
                b = min(255, b + boost // 3)

            enhanced.extend([r, g, b])
    else:
        # Content is bright enough, no enhancement needed
        enhanced.extend(border_bytes)

    return bytes(enhanced)

def _apply_led_offset_pure(border_bytes: bytes, offset: int) -> bytes:
    """Apply LED offset rotation using pure Python"""
    # Each LED = 3 bytes (R, G, B)
    led_count = len(border_bytes) // 3
    offset = offset % led_count

    if offset == 0:
        return border_bytes

    # Rotate by offset LEDs
    split_point = offset * 3
    return border_bytes[split_point:] + border_bytes[:split_point]


def extract_fast_pure(item_id: str, video_path: str, item_name: str, storage) -> int:
    """
    Ultra-fast extractor with ZERO external dependencies!

    Uses only Python standard library + ffmpeg for video processing.
    """
    logger.info(f"   🚀 PURE PYTHON Processing: {item_name} ({item_id})")

    if not os.path.exists(video_path):
        logger.info(f"   ⚠️  Video file not found: {video_path}")
        return 0

    logger.info(f"   📂 Path: {video_path}")
    duration = _get_video_duration(video_path)
    logger.info(f"   ⏱️  Duration: {duration:.2f}s")
    logger.info(f"   💎 Zero external dependencies!")

    # Scale to cover largest edge counts
    width = max(TOP, BOTTOM)
    height = max(LEFT, RIGHT)
    total_frames = int(duration * FPS) if duration > 0 else 0

    frame_size = width * height * 3  # RGB24 = 3 bytes per pixel

    # Start ffmpeg process
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps={FPS},scale={width}:{height}",
        "-an", "-sn",  # No audio/subtitles
        "-f", "image2pipe",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo", "-"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    written = 0
    frame_index = 0

    with storage.start_udp_session(item_id) as session:
        # Write metadata header once at start
        # Header: 'UDPR'[4] + version u8 + fps f32 + wled_led_count u16 + expected_led_count u16 + protocol u8 + reserved u8
        version = 1
        protocol = 0  # 0 for RAW
        header = bytearray(b'UDPR')
        header.append(version)
        header.extend(struct.pack('<fHHBB', FPS, WLED_LED_COUNT, EXPECTED_LED_COUNT, protocol, 0))
        session.write_header(bytes(header))
        while True:
            # Read one frame
            raw_frame = proc.stdout.read(frame_size)
            if len(raw_frame) != frame_size:
                break  # End of video

            # Extract border colors (pure Python!)
            border = _extract_border_colors_pure(raw_frame, width, height)

            # Apply brightness enhancement for dark content
            border = _enhance_brightness_pure(border)

            # Apply LED offset rotation (pure Python!)
            payload = _apply_led_offset_pure(border, INPUT_POSITION)

            # Ensure correct LED count
            led_triplets = len(payload) // 3
            if led_triplets != EXPECTED_LED_COUNT:
                if led_triplets < EXPECTED_LED_COUNT:
                    # Pad with black LEDs
                    payload += bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
                else:
                    # Truncate
                    payload = payload[:EXPECTED_LED_COUNT * 3]

            timestamp = frame_index / FPS

            # Map ambilight payload (EXPECTED_LED_COUNT) to physical WLED strip length
            if EXPECTED_LED_COUNT < WLED_LED_COUNT:
                mapped = payload + bytes([0, 0, 0] * (WLED_LED_COUNT - EXPECTED_LED_COUNT))
            else:
                mapped = payload[: WLED_LED_COUNT * 3]

            # Store RAW RGB payload (no headers), exactly WLED_LED_COUNT * 3 bytes
            session.add_frame(timestamp, bytes(mapped))
            written += 1
            frame_index += 1

            # Progress indicator
            if total_frames and (frame_index % 1000 == 0 or frame_index == total_frames or frame_index == 1):
                percent = (frame_index / total_frames) * 100
                print(f"\r💎 Pure Python: {frame_index}/{total_frames} ({percent:.1f}%)")

    proc.stdout.close()
    proc.wait()

    logger.info(f"   ✅ Pure Python complete: {written} frames, zero dependencies!")
    return written


# Backward compatibility
extract_fast = extract_fast_pure
