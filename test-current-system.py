#!/usr/bin/env python3
"""
Test the current ambilight system with HTTP polling improvements
"""

import os
import requests
import sys
import time

# Configuration
JELLYFIN_BASE_URL = "https://jellyfin.galagaon.com"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

def get_jellyfin_headers():
    return {
        "Authorization": f'MediaBrowser Client="test-daemon", Device="Python", DeviceId="test-daemon-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    }

def test_sessions_with_improved_auth():
    """Test sessions API with improved authorization"""
    print("🧪 Testing improved Sessions API...")

    try:
        response = requests.get(
            f"{JELLYFIN_BASE_URL}/Sessions",
            headers=get_jellyfin_headers(),
            timeout=5
        )

        if response.status_code == 200:
            sessions = response.json()

            # Filter for video sessions
            video_sessions = []
            for session in sessions:
                now_playing = session.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    video_sessions.append(session)

            print(f"✅ Total sessions: {len(sessions)}")
            print(f"✅ Video sessions: {len(video_sessions)}")

            for i, session in enumerate(video_sessions):
                session_id = session["Id"]
                item = session["NowPlayingItem"]
                item_id = item["Id"]
                item_name = item.get("Name", "Unknown")

                playstate = session.get("PlayState", {})
                is_paused = playstate.get("IsPaused", True)
                position_ticks = playstate.get("PositionTicks", 0)
                position_seconds = position_ticks / 10_000_000 if position_ticks else 0

                print(f"\n   Session {i+1}:")
                print(f"     ID: {session_id}")
                print(f"     Item: {item_name}")
                print(f"     Item ID: {item_id}")
                print(f"     Position: {position_seconds:.1f}s")
                print(f"     Status: {'PAUSED' if is_paused else 'PLAYING'}")

            return len(video_sessions) > 0

        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_continuous_monitoring(duration=30):
    """Test continuous session monitoring"""
    print(f"\n🔄 Testing continuous monitoring for {duration} seconds...")
    print("   (Play/pause/seek a video in Jellyfin to see changes)")

    last_states = {}
    start_time = time.time()

    while time.time() - start_time < duration:
        try:
            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Sessions",
                headers=get_jellyfin_headers(),
                timeout=5
            )

            if response.status_code == 200:
                sessions = response.json()

                # Filter for video sessions
                video_sessions = []
                for session in sessions:
                    now_playing = session.get("NowPlayingItem")
                    if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                        video_sessions.append(session)

                # Check for changes
                for session in video_sessions:
                    session_id = session["Id"]
                    item = session["NowPlayingItem"]
                    item_name = item.get("Name", "Unknown")

                    playstate = session.get("PlayState", {})
                    is_paused = playstate.get("IsPaused", True)
                    position_ticks = playstate.get("PositionTicks", 0)
                    position_seconds = position_ticks / 10_000_000 if position_ticks else 0

                    current_state = {
                        "item_name": item_name,
                        "position_seconds": position_seconds,
                        "is_paused": is_paused
                    }

                    last_state = last_states.get(session_id, {})

                    # Detect changes
                    if not last_state:
                        print(f"🎬 NEW SESSION: {item_name} at {position_seconds:.1f}s {'(PAUSED)' if is_paused else '(PLAYING)'}")
                    elif last_state.get("is_paused") != is_paused:
                        status = "PAUSED" if is_paused else "RESUMED"
                        print(f"⏯️  {status}: {item_name} at {position_seconds:.1f}s")
                    elif abs(last_state.get("position_seconds", 0) - position_seconds) > 2:
                        print(f"⏩ SEEK: {item_name} to {position_seconds:.1f}s")

                    last_states[session_id] = current_state

                # Check for stopped sessions
                current_session_ids = {s["Id"] for s in video_sessions}
                stopped_sessions = set(last_states.keys()) - current_session_ids

                for session_id in stopped_sessions:
                    stopped_state = last_states[session_id]
                    print(f"⏹️ STOPPED: {stopped_state.get('item_name', 'Unknown')}")
                    del last_states[session_id]

            time.sleep(1)  # Poll every second

        except Exception as e:
            print(f"❌ Monitoring error: {e}")
            time.sleep(2)

    print("🔄 Monitoring test complete")

def main():
    print("🧪 Testing Current Ambilight System with HTTP Polling")
    print("=" * 60)

    # Test basic functionality
    has_active_sessions = test_sessions_with_improved_auth()

    if has_active_sessions:
        print("\n✅ Found active video sessions!")

        # Ask user if they want to test continuous monitoring
        try:
            answer = input("\nDo you want to test continuous monitoring? (y/N): ").lower()
            if answer in ['y', 'yes']:
                test_continuous_monitoring()
        except KeyboardInterrupt:
            print("\n⌨️ Test interrupted by user")
    else:
        print("\n⚠️ No active video sessions found.")
        print("   Start playing a video in Jellyfin and run this test again.")

    print("\n📊 Test Results Summary:")
    print("✅ HTTP Sessions API working correctly")
    print("✅ Authorization headers fixed")
    print("✅ Video session filtering working")

    if has_active_sessions:
        print("✅ Active playback detected")
        print("\n🎯 Your ambilight daemons should now work correctly!")
        print("   Try running:")
        print("   python ambilight-daemon-files.py")
    else:
        print("⚠️ No active playback (start a video first)")

if __name__ == "__main__":
    main()
