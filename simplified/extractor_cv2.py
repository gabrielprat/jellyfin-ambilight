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

logger = logging.getLogger(__name__)

def _compute_led_zones(frame_shape, counts, border_fraction):
    h, w = frame_shape[:2]
    top_count, bottom_count, left_count, right_count = counts
    top_h = max(1, int(border_fraction * h))
    bottom_h = max(1, int(border_fraction * h))
    left_w = max(1, int(border_fraction * w))
    right_w = max(1, int(border_fraction * w))
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

def _avg_region_bgr(frame, x1, y1, x2, y2, min_lum=10):
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return (0,0,0)
    m = cv2.mean(region)
    b, g, r = int(m[0]), int(m[1]), int(m[2])
    # compute perceived brightness
    lum = 0.2126*r + 0.7152*g + 0.0722*b
    if lum < float(min_lum):
        return (0,0,0)
    return (b,g,r)

def extract_video_to_binary(video_file, output_file, top=89, bottom=89, left=49, right=49,
                            offset=46, rgbw=False, border_fraction=0.05, multiplier=1.0):
    """
    multiplier: if >1.0, attempt to sample more frequently than source FPS.
                e.g. multiplier=2.0 -> twice as many samples as video FPS.
    NOTE: multiplier > 1 seeks the video per sample which is slower but allows oversampling.
    """
    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video {video_file}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 24.0
            logger.warning("Video FPS not found, defaulting to 24.0")
        logger.info(f"Video FPS source: {fps}")

        ret, first = cap.read()
        if not ret:
            raise RuntimeError("Cannot read first frame")

        counts = (top, bottom, left, right)
        zones = _compute_led_zones(first.shape, counts, border_fraction)
        led_count = len(zones)
        fmt_word = 1 if rgbw else 0

        safe_led_count = max(1, led_count)
        offset_mod = offset % safe_led_count

        # Header: "AMBI" + f32 fps + u16 led_count + u16 fmt + u16 offset
        data = bytearray()
        data += struct.pack("<4sfHHH", b"AMBI", float(fps), led_count, fmt_word, offset_mod)

        # Sampling strategy
        # desired sample interval in seconds
        sample_interval_s = (1.0 / fps) / float(multiplier if multiplier > 0 else 1.0)
        total_frames_written = 0
        frame_idx = 0

        if multiplier == 1.0:
            # Fast path: read sequential frames
            # We already consumed first frame in "first"
            cap.set(cv2.CAP_PROP_POS_MSEC, 0)
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                ts_us = int(ts_ms * 1000)
                data += struct.pack("<Q", ts_us)
                # extract colors (clockwise starting top-right)
                min_lum = os.getenv("AMBILIGHT_MIN_LED_LUMINANCE", "30")
                bgr_colors = [_avg_region_bgr(frame, *z, min_lum=min_lum) for z in zones]
                # apply offset counted from TOP-LEFT, CLOCKWISE: rotate LEFT by offset
                if offset_mod:
                    bgr_colors = bgr_colors[offset_mod:] + bgr_colors[:offset_mod]
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
        else:
            # Oversampling path: perform seeks at each desired timestamp.
            # get estimated total duration using frame count if possible
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if frame_count > 0:
                video_duration_s = frame_count / fps
            else:
                # fallback: read through once to compute duration (rare)
                cap.set(cv2.CAP_PROP_POS_MSEC, 0)
                while True:
                    ret, _ = cap.read()
                    if not ret:
                        break
                video_duration_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            # iterate desired timestamps
            t = 0.0
            sample_idx = 0
            while t < video_duration_s:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ret, frame = cap.read()
                if not ret:
                    break
                ts_us = int(cap.get(cv2.CAP_PROP_POS_MSEC) * 1000)
                data += struct.pack("<Q", ts_us)
                bgr_colors = [ _avg_region_bgr(frame, *z) for z in zones ]
                if offset_mod:
                    bgr_colors = bgr_colors[offset_mod:] + bgr_colors[:offset_mod]
                if rgbw:
                    for (b,g,r) in bgr_colors:
                        data += struct.pack("BBBB", r & 0xFF, g & 0xFF, b & 0xFF, 0)
                else:
                    for (b,g,r) in bgr_colors:
                        data += struct.pack("BBB", r & 0xFF, g & 0xFF, b & 0xFF)
                total_frames_written += 1
                sample_idx += 1
                if sample_idx % 200 == 0:
                    logger.info(f"Processed {sample_idx} samples...")
                t += sample_interval_s

        # write file atomically
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)

        logger.info(f"✅ Done! Saved to '{output_file}' ({total_frames_written} frames, fps={fps}, multiplier={multiplier})")
        return True
    finally:
        cap.release()


# wrapper used by your daemon integration; reads env and calls extractor
def extract_frames(video_file, jellyfin_item_id):
    try:
        top = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", "89"))
        bottom = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", "89"))
        left = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", "49"))
        right = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", "49"))
        offset = int(os.getenv("AMBILIGHT_OFFSET", "46"))
        rgbw = os.getenv("AMBILIGHT_RGBW", "false").lower() in ("1","true","yes")
        border_fraction = float(os.getenv("EXTRACTOR_BORDER_FRACTION", "0.05"))
        multiplier = float(os.getenv("EXTRACTOR_MULTIPLIER", "1.0"))
        data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
        binary_dir = data_dir / "binaries"
        data_dir.mkdir(parents=True, exist_ok=True)
        binary_dir.mkdir(parents=True, exist_ok=True)
        out_path = binary_dir / f"{jellyfin_item_id}.bin"
    except Exception as e:
        logger.error(f"Config error: {e}")
        return False

    try:
        return extract_video_to_binary(video_file, str(out_path), top=top, bottom=bottom, left=left, right=right,
                                       offset=offset, rgbw=rgbw, border_fraction=border_fraction, multiplier=multiplier)
    except Exception as e:
        logger.exception(f"Extraction failed: {e}")
        return False
