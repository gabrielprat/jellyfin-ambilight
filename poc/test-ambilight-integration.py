#!/usr/bin/env python3
"""
Test script for Jellyfin HTTP + Ambilight integration
"""

import os
import time
import requests
from pathlib import Path

# Configuration
JELLYFIN_URL = "https://jellyfin.galagaon.com"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"
BIN_DIR = "./ambilight_bins"

def get_jellyfin_headers():
    return {
        "Authorization": f'MediaBrowser Client="test-script", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    }

def test_jellyfin_connection():
    """Test basic Jellyfin connectivity"""
    print("🧪 Testing Jellyfin connection...")

    try:
        response = requests.get(f"{JELLYFIN_URL}/System/Info", headers=get_jellyfin_headers(), timeout=5)
        if response.status_code == 200:
            info = response.json()
            print(f"✅ Connected: {info.get('ServerName')} v{info.get('Version')}")
            return True
        else:
            print(f"❌ HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

def test_sessions_api():
    """Test sessions API"""
    print("\n🧪 Testing Sessions API...")

    try:
        response = requests.get(f"{JELLYFIN_URL}/Sessions", headers=get_jellyfin_headers(), timeout=5)
        if response.status_code == 200:
            sessions = response.json()
            print(f"✅ Found {len(sessions)} active sessions")

            for i, session in enumerate(sessions):
                client = session.get("Client", "Unknown")
                user = session.get("UserName", "Unknown")
                now_playing = session.get("NowPlayingItem")

                print(f"   Session {i+1}: {client} ({user})")

                if now_playing:
                    item_name = now_playing.get("Name", "Unknown")
                    item_type = now_playing.get("Type", "Unknown")
                    item_id = now_playing.get("Id", "Unknown")
                    playstate = session.get("PlayState", {})

                    is_paused = playstate.get("IsPaused", True)
                    position_ticks = playstate.get("PositionTicks", 0)
                    position_seconds = position_ticks / 10_000_000 if position_ticks else 0

                    print(f"     Playing: {item_name} ({item_type})")
                    print(f"     Item ID: {item_id}")
                    print(f"     Position: {position_seconds:.1f}s {'(PAUSED)' if is_paused else '(PLAYING)'}")

                    # Check for binary file
                    bin_file = os.path.join(BIN_DIR, f"{item_id}.bin")
                    if os.path.exists(bin_file):
                        size_mb = os.path.getsize(bin_file) / (1024 * 1024)
                        print(f"     ✅ Binary file: {bin_file} ({size_mb:.1f} MB)")
                    else:
                        print(f"     ❌ No binary file: {bin_file}")
                else:
                    print("     No media playing")

            return True
        else:
            print(f"❌ Sessions API failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Sessions API error: {e}")
        return False

def check_binary_files():
    """Check available binary files"""
    print(f"\n🧪 Checking binary files in {BIN_DIR}...")

    if not os.path.exists(BIN_DIR):
        print(f"❌ Binary directory not found: {BIN_DIR}")
        return False

    bin_files = list(Path(BIN_DIR).glob("*.bin"))

    if not bin_files:
        print(f"❌ No binary files found in {BIN_DIR}")
        return False

    print(f"✅ Found {len(bin_files)} binary files:")

    total_size = 0
    for bin_file in bin_files[:10]:  # Show first 10
        size_mb = bin_file.stat().st_size / (1024 * 1024)
        total_size += size_mb
        item_id = bin_file.stem
        print(f"   {item_id}.bin ({size_mb:.1f} MB)")

    if len(bin_files) > 10:
        remaining = len(bin_files) - 10
        for bin_file in bin_files[10:]:
            total_size += bin_file.stat().st_size / (1024 * 1024)
        print(f"   ... and {remaining} more files")

    print(f"   Total size: {total_size:.1f} MB")
    return True

def test_integration_requirements():
    """Test if all requirements for integration are met"""
    print("\n🧪 Testing Integration Requirements...")

    requirements = {
        "Jellyfin Connection": test_jellyfin_connection(),
        "Sessions API": test_sessions_api(),
        "Binary Files": check_binary_files()
    }

    print("\n📊 Results Summary:")
    print("=" * 50)

    all_passed = True
    for requirement, passed in requirements.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{requirement:<20} | {status}")
        if not passed:
            all_passed = False

    print("=" * 50)

    if all_passed:
        print("🎉 All requirements met! Integration should work.")
        print("\nNext steps:")
        print("1. Run: python poc/jellyfin-ambilight-http-integration.py")
        print("2. Start playing a video in Jellyfin")
        print("3. Watch your ambilight sync to the video!")
    else:
        print("⚠️  Some requirements failed. Fix these issues first.")

    return all_passed

def main():
    print("🧪 Jellyfin + Ambilight Integration Test")
    print("=" * 60)

    test_integration_requirements()

if __name__ == "__main__":
    main()
