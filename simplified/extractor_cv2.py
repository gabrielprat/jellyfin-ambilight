#!/usr/bin/env python3
"""
Simple AMBI extractor (raw). Produces a binary with exact per-LED BGR samples and timestamps.

Usage: call extract_video_to_binary(video_file, output_file, ...)
Environment-driven wrapper provided in extract_frames() at bottom.
"""
import os
import struct
import logging
from pathlib import Path
import cv2
import numpy as np

logger = logging.getLogger(__name__)

def _compute_led_zones(frame_shape, counts):
    h, w = frame_shape[:2]
    top_count, bottom_count, left_count, right_count = counts

    # Calculate consistent band sizes based on LED distribution and screen geometry
    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # Calculate LED spacing for each edge
    top_spacing = w / max(1, top_count) if top_count > 0 else w
    bottom_spacing = w / max(1, bottom_count) if bottom_count > 0 else w
    left_spacing = h / max(1, left_count) if left_count > 0 else h
    right_spacing = h / max(1, right_count) if right_count > 0 else h

    # Calculate band sizes based on LED spacing for visual consistency
    # Use 2x LED spacing for better color capture, with reasonable bounds
    top_h = clamp(int(round(top_spacing * 2.0)), 12, int(h * 0.12))
    bottom_h = clamp(int(round(bottom_spacing * 2.0)), 12, int(h * 0.12))
    left_w = clamp(int(round(left_spacing * 2.0)), 12, int(w * 0.12))
    right_w = clamp(int(round(right_spacing * 2.0)), 12, int(w * 0.12))
    zones = []
    # Clockwise starting at TOP-LEFT
    # Top: left → right (start at top-left)
    for i in range(top_count):
        x1 = int(i * w / top_count)
        x2 = int((i + 1) * w / top_count)
        zones.append((x1, 0, x2, top_h))
    # Right: top → bottom
    for i in range(right_count):
        y1 = int(i * h / right_count)
        y2 = int((i + 1) * h / right_count)
        zones.append((w - right_w, y1, w, y2))
    # Bottom: right → left
    for i in range(bottom_count):
        x2 = int(w - i * w / bottom_count)
        x1 = int(w - (i + 1) * w / bottom_count)
        zones.append((x1, h - bottom_h, x2, h))
    # Left: bottom → top
    for i in range(left_count):
        y2 = int(h - i * h / left_count)
        y1 = int(h - (i + 1) * h / left_count)
        zones.append((0, y1, left_w, y2))
    return zones


def _create_combined_weight_mask(region):
    """
    Create a combined weight mask that prioritizes edges but ensures smooth fallback.
    Combines Canny edge detection with Gaussian center weighting for robust color extraction.
    """
    h, w = region.shape[:2]

    # Create edge mask using adaptive Canny thresholds
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    min_size = min(h, w)
    if min_size < 20:
        low_thresh, high_thresh = 30, 100
    elif min_size < 50:
        low_thresh, high_thresh = 40, 120
    else:
        low_thresh, high_thresh = 50, 150

    edges = cv2.Canny(gray, low_thresh, high_thresh)

    # Create center-weighted Gaussian mask
    center_y, center_x = h // 2, w // 2
    y_coords, x_coords = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((x_coords - center_x)**2 + (y_coords - center_y)**2)
    center_weight = np.exp(-(dist_from_center**2) / (2 * (min(h, w) / 4)**2))

    # Normalize edge mask to 0-1 range
    edge_weight = edges.astype(np.float32) / 255.0

    # Combine edge and center weights with emphasis on edges
    # Edge weight gets 70% influence, center weight gets 30%
    combined_weight = (edge_weight * 0.7 + center_weight * 0.3)

    # Ensure minimum weight to avoid division by zero
    combined_weight = np.maximum(combined_weight, 0.01)

    return combined_weight.reshape(h, w, 1)

def _extract_edge_dominant_color(frame, x1, y1, x2, y2):
    """
    Extract dominant color using combined edge and center weighting.
    Provides smooth, continuous color transitions without jarring fallbacks.
    """
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return (0, 0, 0)

    # Create combined weight mask
    weights = _create_combined_weight_mask(region)

    # Apply weights and calculate weighted mean
    weighted_region = region.astype(np.float32) * weights
    total_weight = np.sum(weights)

    if total_weight > 0:
        b_mean = np.sum(weighted_region[:, :, 0]) / total_weight
        g_mean = np.sum(weighted_region[:, :, 1]) / total_weight
        r_mean = np.sum(weighted_region[:, :, 2]) / total_weight
        return (int(b_mean), int(g_mean), int(r_mean))

    # Fallback to simple mean (should rarely be needed)
    m = cv2.mean(region)
    return (int(m[0]), int(m[1]), int(m[2]))

def extract_video_to_binary(video_file, output_file, top=200, bottom=200, left=None, right=None,
                            rgbw=False):
    cap = None
    try:
        cap = cv2.VideoCapture(video_file)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video {video_file}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 24.0
            logger.warning("Video FPS not found, defaulting to 24.0")
        logger.info(f"Video FPS source: {fps}")

        ret, first = cap.read()
        if not ret:
            raise RuntimeError("Cannot read first frame")

        # Derive left/right counts for visually balanced LED distribution
        h, w = first.shape[:2]
        if left is None or right is None:
            # Calculate based on perimeter ratio for visual balance
            # This approach assumes we want proportional LED density around the screen perimeter
            # rather than equal LED counts on each side. This provides better visual balance
            # especially for wide/tall screens where equal counts would look uneven.
            vertical_perimeter_share = (2 * h) / (2 * (h + w))  # vertical portion of perimeter
            horizontal_leds = top + bottom  # total horizontal LEDs
            # Distribute vertical LEDs based on perimeter ratio for balanced appearance
            proportional_lr = int(round(horizontal_leds * vertical_perimeter_share))
            left = proportional_lr
            right = proportional_lr
        counts = (top, bottom, left, right)
        logger.info(f"LED distribution: top={top}, bottom={bottom}, left={left}, right={right} (total={sum(counts)})")
        zones = _compute_led_zones(first.shape, counts)
        fmt_word = 1 if rgbw else 0

        # Header v2: "AMb2" + f32 fps + u16 top + u16 bottom + u16 left + u16 right + u8 fmt
        data = bytearray()
        data += struct.pack("<4sfHHHHB", b"AMb2", float(fps), top, bottom, left, right, fmt_word)

        # Sampling strategy: sequential frames with natural timestamps
        total_frames_written = 0
        frame_idx = 0

        # Fast path: read sequential frames
        # We already consumed first frame in "first"
        cap.set(cv2.CAP_PROP_POS_MSEC, 0)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Calculate frame-accurate timestamp in microseconds directly
            # This ensures consistent, mathematically precise timestamps without rounding errors
            ts_us = int((frame_idx / fps) * 1_000_000)
            data += struct.pack("<Q", ts_us)
            # extract colors (clockwise starting top-left) using edge detection
            bgr_colors = [_extract_edge_dominant_color(frame, *z) for z in zones]
            # pack
            if rgbw:
                for (b,g,r) in bgr_colors:
                    data += struct.pack("BBBB", r & 0xFF, g & 0xFF, b & 0xFF, 0)
            else:
                for (b,g,r) in bgr_colors:
                    data += struct.pack("BBB", r & 0xFF, g & 0xFF, b & 0xFF)
            total_frames_written += 1
            frame_idx += 1
            if frame_idx % 200 == 0:
                logger.info(f"Processed {frame_idx} frames...")

        # write file atomically using temporary file
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temporary file in the same directory to ensure atomic rename
        temp_path = out_path.with_suffix(out_path.suffix + '.tmp')

        try:
            # Write to temporary file first
            with open(temp_path, "wb") as f:
                f.write(data)

            # Atomically rename temporary file to final destination
            temp_path.replace(out_path)

            logger.info(f"✅ Done! Saved to '{output_file}' ({total_frames_written} frames, fps={fps})")
            return True

        except Exception as e:
            # Clean up temporary file if something went wrong
            if temp_path.exists():
                temp_path.unlink()
            raise e
    finally:
        # Ensure VideoCapture is properly released
        if cap is not None:
            cap.release()


# wrapper used by your daemon integration; reads env and calls extractor
def extract_frames(video_file, jellyfin_item_id):
    try:
        # Fixed reference: top/bottom = 200; left/right derived proportionally in extractor
        top = 200
        bottom = 200
        left = None
        right = None
        rgbw = os.getenv("AMBILIGHT_RGBW", "false").lower() in ("1","true","yes")
        data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
        binary_dir = data_dir / "binaries"
        data_dir.mkdir(parents=True, exist_ok=True)
        binary_dir.mkdir(parents=True, exist_ok=True)
        out_path = binary_dir / f"{jellyfin_item_id}.bin"
    except Exception as e:
        logger.error(f"Config error: {e}")
        return False

    try:
        return extract_video_to_binary(
            video_file,
            str(out_path),
            top=top,
            bottom=bottom,
            left=left,
            right=right,
            rgbw=rgbw,
        )
    except Exception as e:
        logger.exception(f"Extraction failed: {e}")
        return False
