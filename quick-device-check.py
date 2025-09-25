#!/usr/bin/env python3
"""
Quick Jellyfin Device Check
===========================

Simple script to quickly check what devices are currently connected
and what device information is available for ambilight pairing.
"""

import os
import requests
import json

# Load from environment
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL", "https://jellyfin.galagaon.com")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")

def quick_device_check():
    """Quick check of current sessions and device info"""
    try:
        headers = {
            "Authorization": f'MediaBrowser Client="quick-check", Device="Python", DeviceId="quick-check-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
        }

        # Get current sessions
        response = requests.get(f"{JELLYFIN_BASE_URL}/Sessions", headers=headers, timeout=10)
        response.raise_for_status()
        sessions = response.json()

        print(f"🔍 Current Jellyfin Sessions: {len(sessions)}")
        print("-" * 40)

        for i, session in enumerate(sessions, 1):
            print(f"Session {i}:")
            print(f"  DeviceName: '{session.get('DeviceName', 'None')}'")
            print(f"  Client: '{session.get('Client', 'None')}'")
            print(f"  DeviceId: '{session.get('DeviceId', 'None')}'")
            print(f"  User: '{session.get('UserName', 'None')}'")

            now_playing = session.get('NowPlayingItem')
            if now_playing:
                print(f"  ▶️ Playing: {now_playing.get('Name', 'Unknown')}")
            else:
                print(f"  💤 Idle")
            print()

        if sessions:
            print("\n💡 For device-WLED pairing, you can use:")
            print("   - DeviceName (recommended)")
            print("   - Client (app name)")
            print("   - DeviceId (unique identifier)")
        else:
            print("🤔 No active sessions. Start playing something to see device info!")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    quick_device_check()
