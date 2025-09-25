import requests
import time
import os
from database import init_database, get_item_by_filepath, save_session_event

API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")
BASE_URL = os.getenv("JELLYFIN_BASE_URL", "https://jellyfin.galagaon.com")

def get_sessions():
    r = requests.get(
        f"{BASE_URL}/Sessions",
        headers={"X-Emby-Token": API_KEY},
        verify=True
    )
    return r.json()

prev_states: dict[str, bool] = {}
prev_positions: dict[str, float] = {}

def ticks_to_seconds(ticks):
    """Convert 100-nanosecond ticks to seconds"""
    return ticks / 10_000_000

def main():
    # Initialize database
    init_database()
    print("Database initialized - monitoring playback events...")

    while True:
        sessions = get_sessions()
        current_ids = set()

        for s in sessions:
            sid = s["Id"]
            current_ids.add(sid)
            now_playing = s.get("NowPlayingItem")
            play_state = s.get("PlayState")
            client = s.get("Client") or "Unknown"

            if not now_playing or not play_state:
                continue

            is_paused = play_state["IsPaused"]
            position_ticks = play_state.get("PositionTicks", 0)
            position_sec = ticks_to_seconds(position_ticks)

            # Try to get filename/path
            if "Path" in now_playing:
                filename = now_playing["Path"]
            elif "MediaSources" in now_playing and now_playing["MediaSources"]:
                filename = now_playing["MediaSources"][0].get("Path", "Unknown")
            else:
                filename = "Unknown"

            # Detect play/pause changes
            if sid not in prev_states or prev_states[sid] != is_paused:
                prev_states[sid] = is_paused
                state_str = "PAUSED" if is_paused else "PLAYING"
                print(f"{state_str}: {now_playing['Name']}")
                print(f"  Current time: {position_sec:.2f}s")
                print(f"  Filename: {filename}")
                print(f"  Client: {client}")

                # Try to find item in database by filepath
                db_item = get_item_by_filepath(filename)
                if db_item:
                    print(f"  Database item: {db_item['name']} (ID: {db_item['id']})")
                    # Save session event to database
                    save_session_event(sid, db_item['id'], client, state_str, position_sec)
                else:
                    print(f"  Item not found in database for filepath: {filename}")
                    # Save session event without item_id
                    save_session_event(sid, None, client, state_str, position_sec)

                print("-" * 40)

            # Detect seek events
            if sid in prev_positions:
                prev_pos = prev_positions[sid]
                # If jump is bigger than 2 seconds, consider it a seek
                if abs(position_sec - prev_pos) > 2:
                    print(f"SEEK detected: {now_playing['Name']}")
                    print(f"  From: {prev_pos:.2f}s To: {position_sec:.2f}s")
                    print(f"  Filename: {filename}")
                    print(f"  Client: {client}")

                    # Try to find item in database by filepath
                    db_item = get_item_by_filepath(filename)
                    if db_item:
                        print(f"  Database item: {db_item['name']} (ID: {db_item['id']})")
                        # Save seek event to database
                        save_session_event(sid, db_item['id'], client, "SEEK", position_sec)
                    else:
                        print(f"  Item not found in database for filepath: {filename}")
                        # Save seek event without item_id
                        save_session_event(sid, None, client, "SEEK", position_sec)

                    print("-" * 40)

            prev_positions[sid] = position_sec

        # Detect STOP events: sessions that disappeared
        stopped_ids = set(prev_states.keys()) - current_ids
        for sid in stopped_ids:
            print(f"STOPPED session: {sid}")
            # Save stop event to database
            save_session_event(sid, None, "Unknown", "STOPPED", 0)
            prev_states.pop(sid)
            prev_positions.pop(sid, None)

        time.sleep(1)

if __name__ == "__main__":
    main()
