#!/usr/bin/env python3
"""
jellyfin_wled_player.py

- Connects to a Jellyfin WebSocket and listens for playback events.
- When playback starts, it opens a precomputed .bin ambilight file (one file per ItemId expected).
- Synchronizes playback by seeking into the binary and sending DDP packets (UDP) to WLED.
"""

import os
import time
import socket
import struct
import json
import threading
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse
import ssl

import requests
import websocket  # from websocket-client

ws = None

# ---------------- CONFIG (env-friendly) ----------------
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "https://jellyfin.galagaon.com")  # no trailing /socket
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")  # prefer an API token
BIN_DIR = os.getenv("AMBILIGHT_BIN_DIR", "./ambilight_bins")  # files named by ItemId.bin
WLED_IP = os.getenv("WLED_IP", "wled-ambilight-lgc1.lan")
WLED_PORT = int(os.getenv("WLED_DDP_PORT", "4048"))
FPS = float(os.getenv("AMBILIGHT_FPS", "10"))
NUM_LEDS = int(os.getenv("NUM_LEDS", "274"))
FRAME_PAYLOAD_SIZE = NUM_LEDS * 3
RECORD_HEADER_SIZE = 8 + 2  # <double> + <uint16>
RECORD_SIZE = RECORD_HEADER_SIZE + FRAME_PAYLOAD_SIZE
# ------------------------------------------------------

# UDP socket to WLED
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Playback control state (shared between websocket thread and playback thread)
_playback_lock = threading.Lock()
_current_file = None            # file object
_current_filename = None
_playback_thread = None
_playback_stop_event = threading.Event()
_playback_pause_event = threading.Event()
_playback_seek_request = None   # (seconds) if non-None playback thread will seek to it
_playback_start_frame = 0

# Utility: recursive find a key in nested JSON
def find_key(obj: Any, key_name: str):
    if isinstance(obj, dict):
        if key_name in obj:
            return obj[key_name]
        for v in obj.values():
            r = find_key(v, key_name)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for el in obj:
            r = find_key(el, key_name)
            if r is not None:
                return r
    return None

# Build DDP packet (6-byte header as Hyperion-style)
def make_ddp_packet(led_data: bytes, offset_led: int = 0) -> bytes:
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

# Playback worker: continuously reads frames from the open file and sends DDP packets
def playback_worker(fobj, start_frame: int, fps: float):
    global _playback_stop_event, _playback_pause_event, _playback_seek_request
    frame_index = start_frame
    frame_time = 1.0 / fps

    # We will compute a base clock at first send to align timing
    start_clock = None

    # seek to frame
    fobj.seek(frame_index * RECORD_SIZE, os.SEEK_SET)

    while not _playback_stop_event.is_set():
        # handle external seek requests
        if _playback_seek_request is not None:
            req = _playback_seek_request
            _playback_seek_request = None
            # compute frame
            new_frame = int(req * fps)
            frame_index = new_frame
            fobj.seek(frame_index * RECORD_SIZE, os.SEEK_SET)
            start_clock = None  # rebase clock
            print(f"[playback] seek -> {req:.3f}s (frame {frame_index})")

        if _playback_pause_event.is_set():
            # paused: wait until unpaused or stopped or seek
            time.sleep(0.05)
            continue

        header = fobj.read(RECORD_HEADER_SIZE)
        if not header or len(header) < RECORD_HEADER_SIZE:
            print("[playback] EOF reached or incomplete header -> stopping playback")
            break

        # unpack timestamp (double) and payload length (uint16)
        try:
            timestamp, payload_len = struct.unpack("<dH", header)
        except struct.error:
            print("[playback] malformed header; stopping")
            break

        payload = fobj.read(payload_len)
        if not payload or len(payload) < payload_len:
            print("[playback] incomplete payload -> stopping")
            break

        # if payload length differs from expected, try to adapt:
        if payload_len != FRAME_PAYLOAD_SIZE:
            # If different, try to pad/truncate to fit NUM_LEDS*3
            if payload_len < FRAME_PAYLOAD_SIZE:
                payload = payload.ljust(FRAME_PAYLOAD_SIZE, b"\x00")
            else:
                payload = payload[:FRAME_PAYLOAD_SIZE]

        # prepare DDP packet(s). If many leds > 480, need to split; here assume NUM_LEDS small enough.
        packet = make_ddp_packet(payload, offset_led=0)
        try:
            udp_sock.sendto(packet, (WLED_IP, WLED_PORT))
        except Exception as e:
            print(f"[playback] UDP send error: {e}")

        # start base clock when first frame sent
        if start_clock is None:
            start_clock = time.perf_counter()

        frame_index += 1

        # Precise scheduling: compute next desired send time and sleep accordingly
        next_time = start_clock + (frame_index - start_frame) * frame_time
        delay = next_time - time.perf_counter()
        if delay > 0:
            # sleep but wake early if stop/seek/pause
            # we use small sleeps to be responsive to control events
            # but if delay is large, use single sleep
            if delay > 0.02:
                time.sleep(delay - 0.01)
            # busy wait remainder
            while True:
                if _playback_stop_event.is_set() or _playback_pause_event.is_set() or _playback_seek_request is not None:
                    break
                rem = next_time - time.perf_counter()
                if rem <= 0:
                    break
                if rem > 0.001:
                    time.sleep(min(rem, 0.001))
        # loop continues

    print("[playback] worker exiting")
    # close file handled by caller


# Start playback thread for a given filename and start_time (seconds)
def start_playback_for_file(filename: str, start_time: float):
    global _playback_thread, _playback_stop_event, _playback_pause_event, _current_file, _current_filename, _playback_seek_request

    # stop previous playback if any
    stop_playback()

    if not os.path.exists(filename):
        print(f"[error] file not found: {filename}")
        return False

    fobj = open(filename, "rb")
    start_frame = int(start_time * FPS)
    # check file size to ensure start_frame valid
    filesize = os.path.getsize(filename)
    total_frames = filesize // RECORD_SIZE
    if start_frame >= total_frames:
        print(f"[error] start frame {start_frame} >= total frames {total_frames}")
        fobj.close()
        return False

    # reset events
    _playback_stop_event.clear()
    _playback_pause_event.clear()
    _playback_seek_request = None

    # launch thread
    t = threading.Thread(target=playback_worker, args=(fobj, start_frame, FPS), daemon=True)
    _playback_thread = t
    _current_file = fobj
    _current_filename = filename
    t.start()
    print(f"[player] started playback thread for {os.path.basename(filename)} at {start_time:.3f}s (frame {start_frame})")
    return True

def stop_playback():
    global _playback_thread, _playback_stop_event, _current_file, _current_filename
    if _playback_thread is None:
        return
    _playback_stop_event.set()
    # wait a short bit for thread to exit
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
    print("[player] stopped playback")

def pause_playback():
    _playback_pause_event.set()
    print("[player] paused")

def resume_playback():
    _playback_pause_event.clear()
    print("[player] resumed")

def seek_playback_to(seconds: float):
    global _playback_seek_request
    _playback_seek_request = seconds

# Map Jellyfin ItemId -> .bin file path
def find_bin_for_item(item_id: str) -> Optional[str]:
    # 1) direct ItemId.bin inside BIN_DIR
    p1 = os.path.join(BIN_DIR, f"{item_id}.bin")
    if os.path.exists(p1):
        return p1
    # 2) filename fallback: look for any .bin that contains the item_id in name
    for fn in os.listdir(BIN_DIR):
        if fn.lower().endswith(".bin") and item_id.lower() in fn.lower():
            return os.path.join(BIN_DIR, fn)
    # 3) not found
    return None

# WebSocket callbacks
def on_message(ws, message):
    # message may be text (JSON) or other
    print("message", message)
    try:
        payload = json.loads(message)
    except Exception:
        # not json => ignore
        return

    # Handle WebSocket protocol messages
    msg_type = payload.get("MessageType")
    if msg_type == "ForceKeepAlive":
        print("[ws] 💓 Keep-alive received, responding...")
        ws.send(json.dumps({"MessageType": "KeepAlive"}))
        return
    elif msg_type == "ConnectResponse":
        print("[ws] ✅ Connection acknowledged by server")
        return
    elif msg_type == "SubscribeResponse":
        print("[ws] ✅ Subscription confirmed")
        return

    # Debug: uncomment to see raw websocket messages
    # print("[ws message]", json.dumps(payload)[:200])

    # Try to detect playback events: PlaybackStart, PlaybackProgress, PlaybackStopped, Pause
    # We search for keys in payload
    # Jellyfin messages vary; we try a few heuristics
    # Extract itemId and positionTicks and paused flag
    item_id = find_key(payload, "ItemId")
    position_ticks = find_key(payload, "PositionTicks")  # ticks (100ns units)
    is_paused = find_key(payload, "IsPaused")
    event_name = find_key(payload, "EventName") or find_key(payload, "Message") or find_key(payload, "Type")

    # convert ticks -> seconds (Jellyfin uses 100-ns ticks)
    position_seconds = None
    if position_ticks is not None:
        try:
            position_seconds = int(position_ticks) / 10_000_000
        except Exception:
            position_seconds = None

    # Decide what to do depending on event name / content
    # Common payloads use EventName: PlaybackStart, PlaybackProgress, PlaybackStopped
    if isinstance(event_name, str) and "Playback" in event_name:
        en = event_name.lower()
        if "start" in en:
            print(f"[ws] PlaybackStart detected for item {item_id}")
            # find the bin file and start playback at 0 or the provided timestamp
            sec = position_seconds or 0.0
            binfile = find_bin_for_item(item_id) if item_id else None
            if binfile:
                start_playback_for_file(binfile, sec)
            else:
                print(f"[ws] No precomputed .bin found for item {item_id} (expected at {BIN_DIR}/{item_id}.bin)")
        elif "progress" in en:
            # Seek/update playback position
            if item_id is None:
                return
            binfile = find_bin_for_item(item_id)
            if not binfile:
                print(f"[ws] no bin for {item_id}")
                return
            # if not playing or different file, start playback
            if _current_filename != binfile:
                start_playback_for_file(binfile, position_seconds or 0.0)
            else:
                # if paused flag present, pause/resume
                if is_paused is True:
                    pause_playback()
                elif is_paused is False:
                    resume_playback()
                # always correct seek if drift > 0.25s
                if position_seconds is not None:
                    # compute current sending timestamp ~ (frame_index / fps) if we had an index;
                    # easiest: request seek to the exact position
                    seek_playback_to(position_seconds)
        elif "stop" in en or "end" in en:
            print(f"[ws] PlaybackStopped for {item_id}")
            stop_playback()
    else:
        # Some servers may send different shaped messages; try to detect progress-like payloads
        # If there's PositionTicks and ItemId, treat it as progress
        if item_id and position_seconds is not None:
            # treat as progress event
            binfile = find_bin_for_item(item_id)
            if not binfile:
                return
            if _current_filename != binfile:
                start_playback_for_file(binfile, position_seconds)
            else:
                # adjust seek
                seek_playback_to(position_seconds)
                if is_paused is True:
                    pause_playback()
                elif is_paused is False:
                    resume_playback()

def on_error(ws, error):
    print("[ws error]", error)

def on_close(ws, close_status_code, close_msg):
    print("[ws] closed", close_status_code, close_msg)
    # stop playback on websocket close
    stop_playback()

def on_open(ws):
    print("[ws] Connected to Jellyfin")

    # Connect / register
    ws.send(json.dumps({
        "MessageType": "Connect",
        "Data": {
            "Client": "ambilight-script",
            "Device": "Python",
            "DeviceId": "ambilight-001",
            "Version": "1.0"
        }
    }))

    # Subscribe to specific events we care about
    ws.send(json.dumps({
        "MessageType": "Subscribe",
        "Data": {
            "EventNames": [
                "PlaybackStart",
                "PlaybackProgress",
                "PlaybackStopped",
                "SessionsStart",
                "SessionsEnd"
            ]
        }
    }))



def make_ws_url(base_url: str) -> str:
    """
    Convert a Jellyfin base URL (http(s) or ws(s)) into the websocket URL for /socket.
    Examples:
      https://jellyfin.example -> wss://jellyfin.example/socket
      http://jellyfin:8096      -> ws://jellyfin:8096/socket
      ws://jellyfin:8096/socket -> ws://jellyfin:8096/socket (unchanged)
    """
    if not base_url:
        raise ValueError("base_url empty")

    p = urlparse(base_url)

    # If user already passed ws/wss, keep scheme and ensure path ends with /socket
    if p.scheme in ("ws", "wss"):
        path = p.path.rstrip("/")
        if path.endswith("/socket"):
            return base_url
        return urlunparse((p.scheme, p.netloc, path + "/socket", "", "", ""))

    # If user passed http/https, map to ws/wss
    if p.scheme in ("http", "https"):
        ws_scheme = "wss" if p.scheme == "https" else "ws"
        netloc = p.netloc or p.path  # handle accidental missing scheme
        return urlunparse((ws_scheme, netloc, "/socket", "", "", ""))

    # If no scheme provided, assume ws
    if p.scheme == "":
        return "ws://" + base_url.rstrip("/") + "/socket"

    raise ValueError(f"Unsupported URL scheme: {p.scheme}")


def run_ws():
    ws_url = make_ws_url(JELLYFIN_URL)
    print(f"[ws] connecting to {ws_url} ...")

    # Build Authorization header (MediaBrowser token style)
    auth_token = JELLYFIN_API_KEY
    auth_header_val = f'MediaBrowser Client="ambilight", Device="script", DeviceId="ambilight-player", Version="1.0", Token="{auth_token}"'
    headers = [f"Authorization: {auth_header_val}"]

    # websocket-client settings
    wsapp = websocket.WebSocketApp(
        ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # If connecting wss to a server with a self-signed cert, you can disable cert check:
    # (WARNING: disabling cert verification reduces security)
    sslopt = None
    if ws_url.startswith("wss://"):
        # Uncomment next line to skip TLS cert verification (for local/self-signed servers)
        # sslopt = {"cert_reqs": ssl.CERT_NONE}
        sslopt = None  # keep secure by default

    # run with simple reconnect loop
    while True:
        try:
          global ws
          ws = websocket.WebSocketApp(
              ws_url,
              header=headers,
              on_message=on_message,
              on_open=on_open,
              on_close=on_close,
              on_error=on_error
          )
          ws.run_forever(ping_interval=30, ping_timeout=10, sslopt=sslopt)
        except KeyboardInterrupt:
            print("[ws] keyboard interrupt -> exiting")
            break
        except Exception as e:
            print("[ws] connection error:", e)
            print("[ws] reconnecting in 3s...")
            time.sleep(3)
    print("[ws] exit")

def stop_ws():
    global ws
    if ws:
        ws.close()

if __name__ == "__main__":
    print("Jellyfin -> WLED ambilight player")
    print(f"Jellyfin URL: {JELLYFIN_URL}")
    print(f"Bins dir: {BIN_DIR}")
    print(f"WLED: {WLED_IP}:{WLED_PORT} FPS={FPS} LEDS={NUM_LEDS}")
    # ensure bin dir exists
    if not os.path.isdir(BIN_DIR):
        print(f"[error] BIN_DIR not found: {BIN_DIR}")
        raise SystemExit(1)

    try:
        t = threading.Thread(target=run_ws)
        t.start()
        while t.is_alive():
            t.join(1)
    except KeyboardInterrupt:
        print("\n[ws] KeyboardInterrupt -> closing websocket...")
        stop_ws()
        t.join()
        print("[ws] exited cleanly")
