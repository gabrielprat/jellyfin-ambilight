import os
import subprocess
import struct
import io
from pathlib import Path
import json

import numpy as np


def _mark_extraction_failed(jellyfin_item_id, error_message):
    """Mark extraction as failed in storage system"""
    try:
        from storage.storage import FileBasedStorage
        storage = FileBasedStorage()
        storage.mark_extraction_failed(jellyfin_item_id, error_message)
    except Exception as e:
        print(f"❌ Failed to mark extraction as failed: {e}")


def _mark_extraction_completed(jellyfin_item_id):
    """Mark extraction as completed in storage system"""
    try:
        from storage.storage import FileBasedStorage
        storage = FileBasedStorage()
        storage.mark_extraction_completed(jellyfin_item_id)
    except Exception as e:
        print(f"❌ Failed to mark extraction as completed: {e}")

def _safe_parse_fps_ratio(ratio: str) -> float:
    try:
        if not ratio or ratio == "0/0":
            return 0.0
        if "/" in ratio:
            num, den = ratio.split("/", 1)
            num_f = float(num)
            den_f = float(den) if float(den) != 0 else 1.0
            return num_f / den_f
        return float(ratio)
    except Exception:
        return 0.0


def _probe_video_fps(video_file: str) -> tuple[float, str]:
    """Return (fps_float, fps_expr) using ffprobe avg_frame_rate or r_frame_rate.

    fps_expr is a value suitable for ffmpeg fps filter (e.g., "24000/1001").
    """
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,r_frame_rate",
            "-of", "json",
            video_file,
        ]
        out = subprocess.check_output(cmd)
        info = json.loads(out.decode("utf-8", errors="ignore"))
        streams = info.get("streams", [])
        if streams:
            s0 = streams[0]
            avg = s0.get("avg_frame_rate") or "0/0"
            r = s0.get("r_frame_rate") or "0/0"
            fps_expr = avg if avg != "0/0" else r
            fps_float = _safe_parse_fps_ratio(fps_expr)
            if fps_float <= 0 and r and r != "0/0":
                fps_expr = r
                fps_float = _safe_parse_fps_ratio(r)
            # Fallback to 24 if still invalid
            if fps_float <= 0:
                fps_float = 24.0
                fps_expr = "24"
            return fps_float, fps_expr
    except Exception:
        pass
    # Fallback
    return 24.0, "24"


def extract_frames(video_file, jellyfin_item_id):
    """Extract frames from video file with comprehensive error handling"""
    try:
        # --- Load configuration from environment ---
        fps_env = os.getenv("AMBILIGHT_FPS", "20").strip().lower()
        fps_max = float(os.getenv("AMBILIGHT_FPS_MAX", "60"))
        fps_min = float(os.getenv("AMBILIGHT_FPS_MIN", "10"))
        target_w = int(os.getenv("AMBILIGHT_WIDTH", "89"))
        target_h = int(os.getenv("AMBILIGHT_HEIGHT", "49"))
        rgbw = os.getenv("AMBILIGHT_RGBW", "false").lower() in ("1", "true", "yes")
        offset = int(os.getenv("AMBILIGHT_OFFSET", "46"))   # COUNTER-CLOCKWISE offset semantics
        data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))

        # --- Prepare directories ---
        binary_dir = data_dir / "binaries"
        items_dir = data_dir / "items"
        data_dir.mkdir(parents=True, exist_ok=True)
        binary_dir.mkdir(parents=True, exist_ok=True)
        items_dir.mkdir(parents=True, exist_ok=True)

        data_file = binary_dir / f"{jellyfin_item_id}.bin"
    except Exception as e:
        error_msg = f"Configuration error: {str(e)}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    # Check if video file exists and is readable
    if not os.path.exists(video_file):
        error_msg = f"Video file does not exist: {video_file}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    if not os.access(video_file, os.R_OK):
        error_msg = f"Video file is not readable: {video_file}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    # Decide FPS
    try:
        if fps_env == "auto":
            src_fps_float, src_fps_expr = _probe_video_fps(video_file)
            # Clamp within bounds
            chosen_fps_float = max(fps_min, min(fps_max, src_fps_float))
            # If clamped changes value, use float value; else preserve source expression
            if abs(chosen_fps_float - src_fps_float) < 1e-3:
                fps_expr = src_fps_expr  # keep rational if provided
            else:
                fps_expr = f"{chosen_fps_float}"
            header_fps = int(round(chosen_fps_float))
            print(f"🎬 Extracting {video_file} ({jellyfin_item_id})")
            print(f"⚙️ Resolution: {target_w}x{target_h}, FPS: auto→{chosen_fps_float:.3f} (expr {fps_expr}), Offset: {offset} (CCW), RGBW: {rgbw}")
        else:
            # Fixed FPS from env
            try:
                chosen_fps_float = float(fps_env)
            except Exception:
                chosen_fps_float = 20.0
            chosen_fps_float = max(fps_min, min(fps_max, chosen_fps_float))
            fps_expr = f"{chosen_fps_float}"
            header_fps = int(round(chosen_fps_float))
            print(f"🎬 Extracting {video_file} ({jellyfin_item_id})")
            print(f"⚙️ Resolution: {target_w}x{target_h}, FPS: {chosen_fps_float:.3f}, Offset: {offset} (CCW), RGBW: {rgbw}")
    except Exception as e:
        error_msg = f"FPS detection failed: {str(e)}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    # --- Start FFmpeg process (stream raw RGB24 frames) ---
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", video_file,
            "-vf", f"fps={fps_expr},scale={target_w}:{target_h}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10**8)
    except Exception as e:
        error_msg = f"Failed to start ffmpeg process: {str(e)}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    frame_size = target_w * target_h * 3  # RGB24 = 3 bytes per pixel
    border_data = io.BytesIO()

    # --- Compute LED count (perimeter) ---
    led_count = (2 * target_w + 2 * target_h)
    bytes_per_led = 4 if rgbw else 3

    # --- Write header ---
    border_data.write(b"AMBI")                       # Magic signature
    border_data.write(struct.pack("<H", header_fps))        # Frames per second (uint16)
    border_data.write(struct.pack("<H", led_count))  # Total LEDs (uint16)
    border_data.write(struct.pack("<B", 1 if rgbw else 0))  # Format: 1=RGBW, 0=RGB
    border_data.write(struct.pack("<H", offset))     # Offset from top-right corner (uint16)

    frame_idx = 0
    extracted_frames = 0

    try:
        while True:
            # Check if ffmpeg process is still alive
            if proc.poll() is not None:
                # Process has terminated, check for errors
                stderr_output = proc.stderr.read().decode('utf-8', errors='ignore')
                if stderr_output:
                    error_msg = f"FFmpeg process terminated with error: {stderr_output.strip()}"
                    print(f"❌ {error_msg}")
                    _mark_extraction_failed(jellyfin_item_id, error_msg)
                    return False
                else:
                    # Process ended normally (EOF)
                    break

            # --- robust read: ensure we get exactly frame_size bytes ---
            buf = bytearray()
            to_read = frame_size
            while to_read:
                chunk = proc.stdout.read(to_read)
                if not chunk:
                    # EOF
                    to_read = 0
                    break
                buf += chunk
                to_read -= len(chunk)

            if len(buf) < frame_size:
                break  # finished

            raw = bytes(buf)
            # reshape into (h, w, 3)
            frame = np.frombuffer(raw, np.uint8).reshape((target_h, target_w, 3))

            h = target_h
            w = target_w

            # --- Extract border CLOCKWISE starting at TOP-RIGHT (includes all corners) ---
            # right: top -> bottom (includes all pixels)  len = h
            right = frame[0:h, w - 1, :] if w >= 1 else np.zeros((0,3), dtype=np.uint8)

            # bottom: right -> left (includes all pixels)  len = w
            bottom = frame[h - 1, w - 1::-1, :] if w >= 1 else np.zeros((0,3), dtype=np.uint8)

            # left: bottom -> top (includes all pixels)  len = h
            left = frame[h - 1::-1, 0, :] if h >= 1 else np.zeros((0,3), dtype=np.uint8)

            # top: left -> right (includes all pixels)  len = w
            top = frame[0, 0:w, :] if w >= 1 else np.zeros((0,3), dtype=np.uint8)

            # Concatenate in canonical clockwise order: right, bottom, left, top
            border_pixels = np.concatenate([right, bottom, left, top], axis=0)

            # --- APPLY OFFSET (COUNTER-CLOCKWISE semantics) ---
            # Positive offset means LED 0 will be offset leds to the LEFT (counter-clockwise) from top-right.
            if offset != 0:
                border_pixels = np.roll(border_pixels, offset, axis=0)

            # --- Optional RGBW conversion ---
            if rgbw:
                R = border_pixels[:, 0].astype(np.int32)
                G = border_pixels[:, 1].astype(np.int32)
                B = border_pixels[:, 2].astype(np.int32)
                W = np.minimum.reduce([R, G, B])
                Rn = (R - W).clip(0, 255).astype(np.uint8)
                Gn = (G - W).clip(0, 255).astype(np.uint8)
                Bn = (B - W).clip(0, 255).astype(np.uint8)
                Wn = W.clip(0, 255).astype(np.uint8)
                border_pixels = np.column_stack((Rn, Gn, Bn, Wn))

            # --- Timestamp & payload ---
            timestamp = frame_idx / float(chosen_fps_float)
            payload = border_pixels.tobytes()

            # sanity check payload length
            expected_payload_len = led_count * bytes_per_led
            if len(payload) != expected_payload_len:
                # If mismatch, raise — better to catch mistakes early
                error_msg = f"Payload length mismatch: got {len(payload)} expected {expected_payload_len}"
                print(f"❌ {error_msg}")
                _mark_extraction_failed(jellyfin_item_id, error_msg)
                return False

            border_data.write(struct.pack("<dH", timestamp, len(payload)))  # timestamp (double), payload_len (uint16)
            border_data.write(payload)

            frame_idx += 1
            extracted_frames += 1

            # occasional progress print
            if extracted_frames % 100 == 0:
                print(f"Processed {extracted_frames} frames...")

    except Exception as e:
        error_msg = f"Frame extraction error: {str(e)}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False
    finally:
        # clean up ffmpeg
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.stderr.close()
        except Exception:
            pass
        proc.wait()

    # Check if we got any frames
    if extracted_frames == 0:
        error_msg = "No frames extracted from video"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False

    # --- Write final binary to disk ---
    try:
        with open(data_file, "wb") as f:
            f.write(border_data.getbuffer())

        # Mark extraction as completed
        _mark_extraction_completed(jellyfin_item_id)
        print(f"✅ Extraction complete: {data_file} ({extracted_frames} frames, {led_count} LEDs)")
        return True
    except Exception as e:
        error_msg = f"Failed to write binary file: {str(e)}"
        print(f"❌ {error_msg}")
        _mark_extraction_failed(jellyfin_item_id, error_msg)
        return False
