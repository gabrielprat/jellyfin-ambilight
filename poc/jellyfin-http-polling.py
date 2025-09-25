#!/usr/bin/env python3
"""
Alternative: Use HTTP polling instead of WebSocket for Jellyfin events
This avoids the WebSocket message handling bug.
"""

import requests
import time
import json
from typing import Optional, Dict, Any

# Configuration
JELLYFIN_URL = "https://jellyfin.galagaon.com"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"
POLL_INTERVAL = 1.0  # seconds

# Global state tracking
last_session_state = {}

def get_auth_headers():
    """Get authorization headers for Jellyfin API"""
    return {
        "Authorization": f'MediaBrowser Client="ambilight-script", Device="Python", DeviceId="ambilight-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    }

def get_active_sessions():
    """Get current active sessions from Jellyfin"""
    try:
        url = f"{JELLYFIN_URL}/Sessions"
        response = requests.get(url, headers=get_auth_headers(), timeout=5)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"[http] Error getting sessions: {response.status_code}")
            return []

    except Exception as e:
        print(f"[http] Error: {e}")
        return []

def detect_playback_changes(current_sessions):
    """Compare current sessions with last known state to detect changes"""
    global last_session_state

    events = []

    for session in current_sessions:
        session_id = session.get("Id")
        now_playing = session.get("NowPlayingItem")
        playstate = session.get("PlayState", {})

        if not session_id:
            continue

        # Current state
        current_state = {
            "item_id": now_playing.get("Id") if now_playing else None,
            "position_ticks": playstate.get("PositionTicks", 0),
            "is_paused": playstate.get("IsPaused", False),
            "is_playing": now_playing is not None
        }

        # Previous state
        previous_state = last_session_state.get(session_id, {})

        # Detect events
        if current_state["is_playing"] and not previous_state.get("is_playing", False):
            # Playback started
            events.append({
                "type": "PlaybackStart",
                "session_id": session_id,
                "item_id": current_state["item_id"],
                "position_seconds": current_state["position_ticks"] / 10_000_000,
                "session": session
            })

        elif not current_state["is_playing"] and previous_state.get("is_playing", False):
            # Playback stopped
            events.append({
                "type": "PlaybackStop",
                "session_id": session_id,
                "item_id": previous_state.get("item_id"),
                "session": session
            })

        elif (current_state["is_playing"] and previous_state.get("is_playing", False) and
              current_state["item_id"] == previous_state.get("item_id")):
            # Progress update (same item)
            events.append({
                "type": "PlaybackProgress",
                "session_id": session_id,
                "item_id": current_state["item_id"],
                "position_seconds": current_state["position_ticks"] / 10_000_000,
                "is_paused": current_state["is_paused"],
                "session": session
            })

        # Update last known state
        last_session_state[session_id] = current_state

    # Clean up sessions that no longer exist
    current_session_ids = {s.get("Id") for s in current_sessions if s.get("Id")}
    for session_id in list(last_session_state.keys()):
        if session_id not in current_session_ids:
            del last_session_state[session_id]

    return events

def handle_playback_event(event):
    """Handle detected playback events - replace this with your ambilight logic"""
    event_type = event["type"]
    item_id = event["item_id"]

    if event_type == "PlaybackStart":
        print(f"[event] 🎬 Playback started: {item_id} at {event['position_seconds']:.1f}s")
        # TODO: Start ambilight for this item

    elif event_type == "PlaybackStop":
        print(f"[event] ⏹️  Playback stopped: {item_id}")
        # TODO: Stop ambilight

    elif event_type == "PlaybackProgress":
        print(f"[event] ⏯️  Progress: {item_id} at {event['position_seconds']:.1f}s (paused: {event['is_paused']})")
        # TODO: Update ambilight position, handle pause/resume

def main():
    print("🎬 Jellyfin HTTP Polling Monitor")
    print(f"Polling {JELLYFIN_URL} every {POLL_INTERVAL}s")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        while True:
            sessions = get_active_sessions()
            events = detect_playback_changes(sessions)

            for event in events:
                handle_playback_event(event)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[polling] Stopped by user")
    except Exception as e:
        print(f"\n[polling] Error: {e}")

if __name__ == "__main__":
    main()
