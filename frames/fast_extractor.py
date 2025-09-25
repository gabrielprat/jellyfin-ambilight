import os
import subprocess
import numpy as np
import struct
import sys
import json
import logging

from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,  # make sure it logs to stdout
)

logger = logging.getLogger(__name__)

# Config from env with sane defaults
TOP = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", 89))
BOTTOM = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", 89))
LEFT = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", 49))
RIGHT = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", 49))
FPS = float(os.getenv("FRAMES_PER_SECOND", 10))
INPUT_POSITION = int(os.getenv("AMBILIGHT_INPUT_POSITION", 46))
EXPECTED_LED_COUNT = TOP + BOTTOM + LEFT + RIGHT

def _get_video_duration(filename: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "json", filename
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout or '{}')
    return float(info.get("format", {}).get("duration", 0.0))

def _extract_border_colors(frame: np.ndarray) -> np.ndarray:
    h, w, _ = frame.shape
    top = frame[0, :, :]
    right = frame[:, -1, :]
    bottom = frame[-1, ::-1, :]
    left = frame[::-1, 0, :]
    border = np.concatenate([top, right, bottom, left])
    return border.astype(np.uint8)

def _apply_led_offset(border: np.ndarray, offset: int) -> bytes:
    n = len(border)
    offset = offset % n
    rotated = np.roll(border, -offset, axis=0)
    return rotated.astype(np.uint8).tobytes()

def extract_fast(item_id: str, video_path: str, item_name: str, storage) -> int:
    """Ultra-fast extractor that streams frames via ffmpeg and writes a single UDP file.

    - Extract frames at FPS
    - Resize to TOP x LEFT
    - Build [timestamp(double)][payload_len(uint16)][payload(bytes)] records
    - Buffer everything in memory and write once via storage session
    """
    logger.info(f"   🎬 Processing: {item_name},{item_id}")
    if not os.path.exists(video_path):
        logger.info(f"   ⚠️  Video file not found: {video_path}")
        logger.info(f"   🚫 Skipping (will retry on next boot)")
        return 0
    logger.info(f"   📂 Path: {video_path}")
    logger.info(f"   ⏱️  Duration: {_get_video_duration(video_path):.2f}s")
    logger.info(f"   🚀 Using fast extractor")
    # Scale to cover largest edge counts to keep border sampling quality
    width = max(TOP, BOTTOM)
    height = max(LEFT, RIGHT)
    duration = _get_video_duration(video_path)
    total_frames = int(duration * FPS) if duration > 0 else 0

    frame_size = width * height * 3
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", f"fps={FPS},scale={width}:{height}",
        "-an", "-sn",
        "-f", "image2pipe",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo", "-"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # Use storage session for memory-buffered single-file write
    written = 0
    frame_index = 0
    with storage.start_udp_session(item_id) as session:
        while True:
            raw = proc.stdout.read(frame_size)
            if len(raw) != frame_size:
                break

            frame = np.frombuffer(raw, np.uint8).reshape((height, width, 3))
            border = _extract_border_colors(frame)
            payload = _apply_led_offset(border, INPUT_POSITION)
            # Ensure payload length matches expected LED count
            led_triplets = len(payload) // 3
            if led_triplets != EXPECTED_LED_COUNT:
                if led_triplets < EXPECTED_LED_COUNT:
                    payload += bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
                else:
                    payload = payload[: EXPECTED_LED_COUNT * 3]
            timestamp = frame_index / FPS
            frame_index += 1

            # Build DRGB UDP packet from payload (payload is RGB sequence)
            # DRGB header + payload
            packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])
            packet.extend(payload)

            session.add_frame(timestamp, bytes(packet))
            written += 1

            if total_frames and (frame_index % 1000 == 0 or frame_index == total_frames or frame_index == 1):
                percent = (frame_index / total_frames) * 100
                print(f"\r📈 Fast extractor: {frame_index}/{total_frames} ({percent:.1f}%)")

    proc.stdout.close()
    proc.wait()
    logger.info(f"   ✅ Fast extractor complete: {written} frames → single UDP file")
    return written
