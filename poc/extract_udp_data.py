import os
import subprocess
import numpy as np
import struct
import sys
import json

# ===== CONFIG =====

width = os.getenv("AMBILIGHT_TOP_LED_COUNT", 89)
height = os.getenv("AMBILIGHT_LEFT_LED_COUNT", 49)
fps = os.getenv("FRAMES_PER_SECOND", 10)
input_position = os.getenv("AMBILIGHT_INPUT_POSITION", 46)
input_video = "Sonic.The.Hedgehog.3.2024.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv"
output_file = "frames_with_payload.bin"
# ==================


def get_video_duration(filename: str) -> float:
    """Return duration of video in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "json", filename
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def extract_border_colors(frame: np.ndarray) -> np.ndarray:
    """Extract border pixels in clockwise order starting from top-left."""
    h, w, _ = frame.shape
    top = frame[0, :, :]              # top row left→right
    right = frame[:, -1, :]           # right col top→bottom
    bottom = frame[-1, ::-1, :]       # bottom row right→left
    left = frame[::-1, 0, :]          # left col bottom→top
    border = np.concatenate([top, right, bottom, left])
    return border.astype(np.uint8)


def apply_led_offset(border: np.ndarray, offset: int) -> bytes:
    """Rotate LED order by offset."""
    n = len(border)
    offset = offset % n
    rotated = np.roll(border, -offset, axis=0)
    return rotated.astype(np.uint8).tobytes()


def extract_udp_data(filename: str):
    frame_size = width * height * 3
    duration = get_video_duration(input_video)
    total_frames = int(duration * fps)

    cmd = [
        "ffmpeg",
        "-i", input_video,
        "-vf", f"fps={fps},scale={width}:{height}",
        "-f", "image2pipe",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo", "-"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # use a bytearray to accumulate everything in memory
    all_data = bytearray()
    frame_index = 0

    while True:
        raw = proc.stdout.read(frame_size)
        if len(raw) != frame_size:
            break

        frame = np.frombuffer(raw, np.uint8).reshape((height, width, 3))
        border = extract_border_colors(frame)
        payload = apply_led_offset(border, input_position)
        timestamp = frame_index / fps
        frame_index += 1

        # append [timestamp][payload_len][payload] to bytearray
        all_data.extend(struct.pack("<dH", timestamp, len(payload)))
        all_data.extend(payload)

        # ---- progress output ----
        if frame_index % 10 == 0 or frame_index == total_frames:
            percent = (frame_index / total_frames) * 100
            sys.stdout.write(f"\rProcessing frame {frame_index}/{total_frames} ({percent:.1f}%)")
            sys.stdout.flush()

    proc.stdout.close()
    proc.wait()

    # write all at once
    with open(output_file, "wb") as f:
        f.write(all_data)

    print(f"\n[OK] File generated: {output_file}")


if __name__ == "__main__":
    extract_udp_data(input_video)
