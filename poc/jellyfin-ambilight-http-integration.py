#!/usr/bin/env python3
"""
Jellyfin HTTP Polling + Ambilight Integration
==============================================

Production-ready integration using HTTP polling (NOT WebSocket due to server issues).
Combines the reliability of HTTP polling with your existing ambilight binary playback system.

This replaces the broken WebSocket approach with a robust HTTP-based solution.
"""

import os
import time
import socket
import struct
import json
import threading
import signal
import logging
from typing import Optional, Dict, Any
from pathlib import Path

import requests

# Configuration from environment
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "https://jellyfin.galagaon.com")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")
BIN_DIR = os.getenv("AMBILIGHT_BIN_DIR", "./ambilight_bins")  # Binary files by ItemId
WLED_IP = os.getenv("WLED_IP", "wled-ambilight-lgc1.lan")
WLED_PORT = int(os.getenv("WLED_DDP_PORT", "4048"))
FPS = float(os.getenv("AMBILIGHT_FPS", "10"))
NUM_LEDS = int(os.getenv("NUM_LEDS", "274"))

# Polling configuration
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))  # seconds
POSITION_UPDATE_THRESHOLD = float(os.getenv("POSITION_UPDATE_THRESHOLD", "0.5"))  # seconds

# Binary file format constants
FRAME_PAYLOAD_SIZE = NUM_LEDS * 3
RECORD_HEADER_SIZE = 8 + 2  # <double> + <uint16>
RECORD_SIZE = RECORD_HEADER_SIZE + FRAME_PAYLOAD_SIZE

# Global state
shutdown_event = threading.Event()
logger = logging.getLogger(__name__)

# Playback control state (shared between threads)
_playback_lock = threading.Lock()
_current_file = None
_current_filename = None
_playback_thread = None
_playback_stop_event = threading.Event()
_playback_pause_event = threading.Event()
_playback_seek_request = None
_playback_start_frame = 0

# UDP socket to WLED
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Session tracking
last_session_state = {}


def setup_logging():
    """Configure logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )


def get_jellyfin_headers():
    """Get authorization headers for Jellyfin API"""
    return {
        "Authorization": f'MediaBrowser Client="ambilight-http", Device="Python", DeviceId="ambilight-http-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    }


def get_jellyfin_sessions():
    """Get current Jellyfin playback sessions via HTTP API"""
    try:
        response = requests.get(
            f"{JELLYFIN_URL}/Sessions",
            headers=get_jellyfin_headers(),
            timeout=5
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Sessions API returned {response.status_code}")
            return []

    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return []


def ticks_to_seconds(ticks):
    """Convert Jellyfin ticks to seconds"""
    return ticks / 10_000_000 if ticks else 0


def make_ddp_packet(led_data: bytes, offset_led: int = 0) -> bytes:
    """Build DDP packet for WLED"""
    data_len = len(led_data)
    if data_len % 3 != 0:
        raise ValueError("led_data length must be multiple of 3")

    header = bytearray(6)
    header[0] = 0x41  # flags: push + version
    header[1] = 0x01  # datatype RGB
    header[2] = (offset_led >> 8) & 0xFF
    header[3] = offset_led & 0xFF
    header[4] = (data_len >> 8) & 0xFF
    header[5] = data_len & 0xFF

    return bytes(header) + led_data


def find_bin_for_item(item_id: str) -> Optional[str]:
    """Find binary ambilight file for Jellyfin item ID"""
    if not os.path.exists(BIN_DIR):
        logger.warning(f"Binary directory not found: {BIN_DIR}")
        return None

    # Direct match: ItemId.bin
    direct_path = os.path.join(BIN_DIR, f"{item_id}.bin")
    if os.path.exists(direct_path):
        return direct_path

    # Fallback: search for any .bin containing the item_id
    try:
        for filename in os.listdir(BIN_DIR):
            if filename.lower().endswith(".bin") and item_id.lower() in filename.lower():
                return os.path.join(BIN_DIR, filename)
    except Exception as e:
        logger.error(f"Error searching binary directory: {e}")

    return None


def playback_worker(fobj, start_frame: int, fps: float):
    """Background worker for binary playback"""
    global _playback_stop_event, _playback_pause_event, _playback_seek_request

    frame_index = start_frame
    frame_time = 1.0 / fps
    start_clock = None

    # Seek to starting frame
    fobj.seek(frame_index * RECORD_SIZE, os.SEEK_SET)

    logger.info(f"🎬 Starting playback worker at frame {start_frame}")

    while not _playback_stop_event.is_set():
        # Handle seek requests
        if _playback_seek_request is not None:
            req = _playback_seek_request
            _playback_seek_request = None
            new_frame = int(req * fps)
            frame_index = new_frame
            fobj.seek(frame_index * RECORD_SIZE, os.SEEK_SET)
            start_clock = None  # Reset timing
            logger.info(f"⏩ Seek to {req:.3f}s (frame {frame_index})")

        # Handle pause
        if _playback_pause_event.is_set():
            time.sleep(0.05)
            continue

        # Read frame from binary file
        header = fobj.read(RECORD_HEADER_SIZE)
        if not header or len(header) < RECORD_HEADER_SIZE:
            logger.info("📁 End of binary file reached")
            break

        try:
            timestamp, payload_len = struct.unpack("<dH", header)
        except struct.error:
            logger.error("📁 Corrupted binary file header")
            break

        payload = fobj.read(payload_len)
        if not payload or len(payload) < payload_len:
            logger.error("📁 Incomplete binary payload")
            break

        # Adjust payload size if needed
        if payload_len != FRAME_PAYLOAD_SIZE:
            if payload_len < FRAME_PAYLOAD_SIZE:
                payload = payload.ljust(FRAME_PAYLOAD_SIZE, b"\x00")
            else:
                payload = payload[:FRAME_PAYLOAD_SIZE]

        # Send DDP packet to WLED
        try:
            packet = make_ddp_packet(payload, offset_led=0)
            udp_sock.sendto(packet, (WLED_IP, WLED_PORT))
        except Exception as e:
            logger.error(f"🌈 UDP send error: {e}")

        # Timing control
        if start_clock is None:
            start_clock = time.perf_counter()

        frame_index += 1

        # Precise frame timing
        next_time = start_clock + (frame_index - start_frame) * frame_time
        delay = next_time - time.perf_counter()

        if delay > 0:
            # Responsive sleep with early wake for control events
            if delay > 0.02:
                time.sleep(delay - 0.01)

            # Busy wait for precision
            while True:
                if (_playback_stop_event.is_set() or
                    _playback_pause_event.is_set() or
                    _playback_seek_request is not None):
                    break

                remaining = next_time - time.perf_counter()
                if remaining <= 0:
                    break
                if remaining > 0.001:
                    time.sleep(min(remaining, 0.001))

    logger.info("🎬 Playback worker stopped")


def start_playback_for_file(filename: str, start_time: float):
    """Start binary playback thread"""
    global (_playback_thread, _playback_stop_event, _playback_pause_event,
            _current_file, _current_filename, _playback_seek_request)

    # Stop existing playback
    stop_playback()

    if not os.path.exists(filename):
        logger.error(f"📁 Binary file not found: {filename}")
        return False

    try:
        fobj = open(filename, "rb")
        start_frame = int(start_time * FPS)

        # Validate file size
        filesize = os.path.getsize(filename)
        total_frames = filesize // RECORD_SIZE

        if start_frame >= total_frames:
            logger.error(f"📁 Start frame {start_frame} exceeds file ({total_frames} frames)")
            fobj.close()
            return False

        # Reset control events
        _playback_stop_event.clear()
        _playback_pause_event.clear()
        _playback_seek_request = None

        # Start playback thread
        thread = threading.Thread(
            target=playback_worker,
            args=(fobj, start_frame, FPS),
            daemon=True,
            name="AmbilightPlayback"
        )

        _playback_thread = thread
        _current_file = fobj
        _current_filename = filename

        thread.start()

        logger.info(f"🎬 Started playback: {os.path.basename(filename)} at {start_time:.1f}s")
        return True

    except Exception as e:
        logger.error(f"📁 Failed to start playback: {e}")
        return False


def stop_playback():
    """Stop current playback"""
    global _playback_thread, _playback_stop_event, _current_file, _current_filename

    if _playback_thread is None:
        return

    _playback_stop_event.set()
    _playback_thread.join(timeout=1.0)

    if _current_file:
        try:
            _current_file.close()
        except:
            pass

    _playback_thread = None
    _current_file = None
    _current_filename = None
    _playback_stop_event.clear()

    logger.info("⏹️ Playback stopped")


def pause_playback():
    """Pause current playback"""
    _playback_pause_event.set()
    logger.info("⏸️ Playback paused")


def resume_playback():
    """Resume current playback"""
    _playback_pause_event.clear()
    logger.info("▶️ Playback resumed")


def seek_playback_to(seconds: float):
    """Seek playback to specific timestamp"""
    global _playback_seek_request
    _playback_seek_request = seconds


def turn_off_wled():
    """Turn off WLED (send black frame)"""
    try:
        black_data = bytes([0, 0, 0] * NUM_LEDS)
        packet = make_ddp_packet(black_data)
        udp_sock.sendto(packet, (WLED_IP, WLED_PORT))
        logger.debug("💡 WLED turned off")
    except Exception as e:
        logger.error(f"💡 Failed to turn off WLED: {e}")


def detect_playback_changes(current_sessions):
    """Detect playback state changes from session polling"""
    global last_session_state

    events = []
    current_session_ids = set()

    for session in current_sessions:
        session_id = session.get("Id")
        if not session_id:
            continue

        current_session_ids.add(session_id)

        now_playing = session.get("NowPlayingItem")
        playstate = session.get("PlayState", {})

        if not now_playing or not playstate:
            continue

        # Current state
        current_state = {
            "item_id": now_playing.get("Id"),
            "item_name": now_playing.get("Name", "Unknown"),
            "position_ticks": playstate.get("PositionTicks", 0),
            "is_paused": playstate.get("IsPaused", False),
            "is_playing": True
        }

        position_seconds = ticks_to_seconds(current_state["position_ticks"])
        current_state["position_seconds"] = position_seconds

        # Previous state
        previous_state = last_session_state.get(session_id, {})

        # Detect events
        if not previous_state.get("is_playing", False):
            # Playback started
            events.append({
                "type": "PlaybackStart",
                "session_id": session_id,
                "item_id": current_state["item_id"],
                "item_name": current_state["item_name"],
                "position_seconds": position_seconds,
                "is_paused": current_state["is_paused"]
            })
        elif previous_state.get("item_id") != current_state["item_id"]:
            # Different item started
            events.append({
                "type": "PlaybackStart",
                "session_id": session_id,
                "item_id": current_state["item_id"],
                "item_name": current_state["item_name"],
                "position_seconds": position_seconds,
                "is_paused": current_state["is_paused"]
            })
        elif previous_state.get("is_paused") != current_state["is_paused"]:
            # Pause/resume
            event_type = "PlaybackPause" if current_state["is_paused"] else "PlaybackResume"
            events.append({
                "type": event_type,
                "session_id": session_id,
                "item_id": current_state["item_id"],
                "item_name": current_state["item_name"],
                "position_seconds": position_seconds,
                "is_paused": current_state["is_paused"]
            })
        else:
            # Position update (seek detection)
            prev_pos = previous_state.get("position_seconds", 0)
            time_diff = abs(position_seconds - prev_pos)

            # Detect seek (jump > 2 seconds)
            if time_diff > 2:
                events.append({
                    "type": "PlaybackSeek",
                    "session_id": session_id,
                    "item_id": current_state["item_id"],
                    "item_name": current_state["item_name"],
                    "position_seconds": position_seconds,
                    "previous_position": prev_pos,
                    "is_paused": current_state["is_paused"]
                })
            # Normal progress update
            elif time_diff >= POSITION_UPDATE_THRESHOLD:
                events.append({
                    "type": "PlaybackProgress",
                    "session_id": session_id,
                    "item_id": current_state["item_id"],
                    "item_name": current_state["item_name"],
                    "position_seconds": position_seconds,
                    "is_paused": current_state["is_paused"]
                })

        # Update last known state
        last_session_state[session_id] = current_state

    # Detect stopped sessions
    stopped_sessions = set(last_session_state.keys()) - current_session_ids
    for session_id in stopped_sessions:
        prev_state = last_session_state[session_id]
        events.append({
            "type": "PlaybackStop",
            "session_id": session_id,
            "item_id": prev_state.get("item_id"),
            "item_name": prev_state.get("item_name", "Unknown"),
            "position_seconds": prev_state.get("position_seconds", 0)
        })
        del last_session_state[session_id]

    return events


def handle_playback_event(event):
    """Handle detected playback events"""
    event_type = event["type"]
    item_id = event["item_id"]
    item_name = event["item_name"]
    position_seconds = event["position_seconds"]
    is_paused = event.get("is_paused", False)

    if event_type == "PlaybackStart":
        logger.info(f"🎬 Playback started: {item_name} at {position_seconds:.1f}s")

        # Find binary file for this item
        binfile = find_bin_for_item(item_id)
        if binfile:
            start_playback_for_file(binfile, position_seconds)
            if is_paused:
                pause_playback()
        else:
            logger.warning(f"📁 No binary file found for item {item_id} ({item_name})")
            logger.info(f"   Expected: {BIN_DIR}/{item_id}.bin")

    elif event_type == "PlaybackStop":
        logger.info(f"⏹️ Playback stopped: {item_name}")
        stop_playback()
        turn_off_wled()

    elif event_type == "PlaybackPause":
        logger.info(f"⏸️ Playback paused: {item_name} at {position_seconds:.1f}s")
        pause_playback()

    elif event_type == "PlaybackResume":
        logger.info(f"▶️ Playback resumed: {item_name} at {position_seconds:.1f}s")
        resume_playback()

    elif event_type == "PlaybackSeek":
        prev_pos = event.get("previous_position", 0)
        logger.info(f"⏩ Seek: {item_name} from {prev_pos:.1f}s to {position_seconds:.1f}s")
        seek_playback_to(position_seconds)

        if is_paused:
            pause_playback()
        else:
            resume_playback()

    elif event_type == "PlaybackProgress":
        # Continuous playback - sync if needed
        seek_playback_to(position_seconds)

        if is_paused:
            pause_playback()
        else:
            resume_playback()


def monitor_jellyfin_http():
    """Main monitoring loop using HTTP polling"""
    logger.info("🔄 Starting Jellyfin HTTP monitoring...")
    logger.info(f"   Polling interval: {POLL_INTERVAL}s")
    logger.info(f"   Position threshold: {POSITION_UPDATE_THRESHOLD}s")

    consecutive_errors = 0
    max_errors = 5

    while not shutdown_event.is_set():
        try:
            # Get current sessions
            sessions = get_jellyfin_sessions()

            # Filter for video playback sessions
            video_sessions = []
            for session in sessions:
                now_playing = session.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    video_sessions.append(session)

            # Detect changes
            events = detect_playback_changes(video_sessions)

            # Handle events
            for event in events:
                handle_playback_event(event)

            # Reset error counter on success
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"💥 Monitoring error ({consecutive_errors}/{max_errors}): {e}")

            if consecutive_errors >= max_errors:
                logger.error("💥 Too many consecutive errors, stopping monitoring")
                break

        # Wait before next poll
        time.sleep(POLL_INTERVAL)

    logger.info("🔄 HTTP monitoring stopped")


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"📡 Received signal {signum}, shutting down...")
    shutdown_event.set()


def main():
    """Main entry point"""
    setup_logging()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("🌈 Jellyfin HTTP Polling + Ambilight Integration")
    logger.info("=" * 60)
    logger.info(f"   Jellyfin URL: {JELLYFIN_URL}")
    logger.info(f"   Binary directory: {BIN_DIR}")
    logger.info(f"   WLED: {WLED_IP}:{WLED_PORT}")
    logger.info(f"   FPS: {FPS}, LEDs: {NUM_LEDS}")
    logger.info("=" * 60)

    # Validate configuration
    if not JELLYFIN_API_KEY:
        logger.error("❌ JELLYFIN_API_KEY must be set")
        return 1

    if not os.path.exists(BIN_DIR):
        logger.error(f"❌ Binary directory not found: {BIN_DIR}")
        logger.info("   Create binary files first using frame extraction")
        return 1

    # Test Jellyfin connection
    try:
        response = requests.get(f"{JELLYFIN_URL}/System/Info", headers=get_jellyfin_headers(), timeout=5)
        if response.status_code == 200:
            server_info = response.json()
            logger.info(f"✅ Connected to Jellyfin: {server_info.get('ServerName', 'Unknown')} v{server_info.get('Version', 'Unknown')}")
        else:
            logger.error(f"❌ Jellyfin connection failed: HTTP {response.status_code}")
            return 1
    except Exception as e:
        logger.error(f"❌ Cannot connect to Jellyfin: {e}")
        return 1

    try:
        # Start monitoring
        monitor_jellyfin_http()
    except KeyboardInterrupt:
        logger.info("⌨️ Keyboard interrupt received")
    finally:
        # Cleanup
        shutdown_event.set()
        stop_playback()
        turn_off_wled()
        udp_sock.close()
        logger.info("👋 Ambilight integration stopped")

    return 0


if __name__ == "__main__":
    exit(main())
