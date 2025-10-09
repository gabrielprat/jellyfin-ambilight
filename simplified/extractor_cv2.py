import os
import struct
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

def _compute_led_zones(frame_shape, counts, border_fraction):
    """Compute LED sampling rectangles in clockwise order: right → bottom → left → top."""
    h, w = frame_shape[:2]
    top_count, bottom_count, left_count, right_count = counts

    top_h = max(1, int(border_fraction * h))
    bottom_h = max(1, int(border_fraction * h))
    left_w = max(1, int(border_fraction * w))
    right_w = max(1, int(border_fraction * w))

    zones = []

    # Right: top → bottom (starts at top-right)
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

    # Top: left → right (finishes back near top-right)
    for i in range(top_count):
        x1 = int(i * w / top_count)
        x2 = int((i + 1) * w / top_count)
        zones.append((x1, 0, x2, top_h))

    return zones

def _extract_led_colors_bgr(frame, zones,
                            gamma=2.2,
                            saturation_boost=1.3,
                            brightness_clip=245,
                            dark_scene_boost=1.2):
    """
    Extract average BGR colors with adaptive gamma correction and brightness balancing.
    Dark scenes stay dim; bright scenes stay vivid but not overexposed.
    """
    colors = []

    for (x1, y1, x2, y2) in zones:
        region = frame[y1:y2, x1:x2]
        if region.size == 0:
            colors.append((0, 0, 0))
            continue

        # Convert to HSV to work with brightness and saturation
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.float32)

        # Mask out overexposed whites (too bright regions)
        mask = (hsv[..., 2] < brightness_clip)
        if np.any(mask):
            valid = hsv[mask]
        else:
            valid = hsv.reshape(-1, 3)

        if valid.shape[0] == 0:
            colors.append((0, 0, 0))
            continue

        # Compute average brightness and saturation of the valid region
        avg_v = np.mean(valid[:, 2])
        avg_s = np.mean(valid[:, 1])

        # Adaptive saturation boost (less boost in very bright scenes)
        if avg_v < 120:
            valid[:, 1] *= saturation_boost
        elif avg_v < 200:
            valid[:, 1] *= 1.1  # mild boost

        valid[:, 1] = np.clip(valid[:, 1], 0, 255)

        # Apply gamma correction to brightness (make darks darker, lights smoother)
        valid[:, 2] = 255.0 * ((valid[:, 2] / 255.0) ** (1.0 / gamma))
        valid[:, 2] = np.clip(valid[:, 2], 0, 255)

        # Reconstruct region and average
        avg_hsv = np.mean(valid, axis=0)
        avg_hsv = avg_hsv.reshape(1, 1, 3).astype(np.uint8)
        avg_bgr = cv2.cvtColor(avg_hsv, cv2.COLOR_HSV2BGR)[0, 0]

        # Optional: global brightness adaptation per LED
        # If the overall brightness is low, dim the LED accordingly
        brightness_factor = (avg_v / 255.0) ** 1.5
        brightness_factor = max(0.05, min(brightness_factor * dark_scene_boost, 1.0))

        final_color = tuple(int(c * brightness_factor) for c in avg_bgr)
        colors.append(final_color)

    return colors

def extract_video_to_binary(video_file, output_file, top=89, bottom=89, left=49, right=49,
                            offset=46, rgbw=False, border_fraction=0.05):
    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video {video_file}")

    try:
        # Use exact video FPS for precise timing
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps and fps > 0:
            logger.info(f"\t🎬 Video FPS: {fps}")
        else:
            fps = 24
            logger.warning(f"\t⚠️ Video FPS not found, using default: {fps}")

        ret, first = cap.read()
        if not ret:
            raise RuntimeError("Cannot read first frame")

        counts = (top, bottom, left, right)
        zones = _compute_led_zones(first.shape, counts, border_fraction)
        led_count = len(zones)
        fmt_byte = 1 if rgbw else 0

        safe_led_count = max(1, led_count)
        offset_mod = offset % safe_led_count

        # Build binary in memory - store exact FPS as float
        data = bytearray()
        data += struct.pack("<4sfHHH", b"AMBI", fps, led_count, fmt_byte, offset_mod)

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            ts_us = int(ts_ms * 1000)
            data += struct.pack("<Q", ts_us)

            # Extract colors in clockwise order starting at top-right
            bgr_colors = _extract_led_colors_bgr(frame, zones)

            # Apply offset as COUNTER-CLOCKWISE rotation:
            # offset = 46 means the physical first LED is 46 LEDs to the left of top-right,
            # therefore we move the last `offset` elements to the front.
            if offset_mod:
                bgr_colors = bgr_colors[-offset_mod:] + bgr_colors[:-offset_mod]

            if rgbw:
                for (b, g, r) in bgr_colors:
                    data += struct.pack("BBBB", r & 0xFF, g & 0xFF, b & 0xFF, 0)
            else:
                for (b, g, r) in bgr_colors:
                    data += struct.pack("BBB", r & 0xFF, g & 0xFF, b & 0xFF)

            frame_idx += 1
            if frame_idx % 100 == 0:
                logger.info(f"Processed {frame_idx} frames...")

        with open(output_file, "wb") as f:
            f.write(data)

        logger.info(f"\n✅ Done! Saved to '{output_file}' ({frame_idx} frames, FPS={fps})")
    finally:
        cap.release()


# --- Daemon integration wrapper ---
def _mark_extraction_failed(jellyfin_item_id, error_message):
    try:
        from storage.storage import FileBasedStorage
        storage = FileBasedStorage()
        storage.mark_extraction_failed(jellyfin_item_id, error_message)
    except Exception as e:
        logger.error(f"❌ Failed to mark extraction as failed: {e}")


def _mark_extraction_completed(jellyfin_item_id):
    try:
        from storage.storage import FileBasedStorage
        storage = FileBasedStorage()
        storage.mark_extraction_completed(jellyfin_item_id)
    except Exception as e:
        logger.error(f"❌ Failed to mark extraction as completed: {e}")


def extract_frames(video_file, jellyfin_item_id):
    """Wrapper used by ambilight-daemon-files.py.

    Reads configuration from environment, writes AMBI binary to
    $AMBILIGHT_DATA_DIR/binaries/{item_id}.bin and returns True/False.
    """
    try:
        top = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", "89"))
        bottom = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", "89"))
        left = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", "49"))
        right = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", "49"))
        offset = int(os.getenv("AMBILIGHT_OFFSET", "46"))
        rgbw = os.getenv("AMBILIGHT_RGBW", "false").lower() in ("1", "true", "yes")
        border_fraction = float(os.getenv("EXTRACTOR_BORDER_FRACTION", "0.05"))

        data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
        binary_dir = data_dir / "binaries"
        data_dir.mkdir(parents=True, exist_ok=True)
        binary_dir.mkdir(parents=True, exist_ok=True)
        out_path = binary_dir / f"{jellyfin_item_id}.bin"
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        _mark_extraction_failed(jellyfin_item_id, str(e))
        return False

    try:
        extract_video_to_binary(
            video_file,
            str(out_path),
            top=top,
            bottom=bottom,
            left=left,
            right=right,
            offset=offset,
            rgbw=rgbw,
            border_fraction=border_fraction,
        )
        _mark_extraction_completed(jellyfin_item_id)
        return True
    except Exception as e:
        logger.error(f"❌ Extraction failed: {e}")
        _mark_extraction_failed(jellyfin_item_id, str(e))
        return False

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

if __name__ == "__main__":
    main()
