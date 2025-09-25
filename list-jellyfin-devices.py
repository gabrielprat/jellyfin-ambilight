#!/usr/bin/env python3
"""
Jellyfin Device Lister
======================

Lists all devices that have connected to Jellyfin server, including:
- Current sessions (active devices)
- Device history (all devices that have ever connected)
- Device capabilities and information

Useful for configuring device-WLED pairing in the ambilight system.
"""

import os
import requests
import json
from datetime import datetime
from typing import List, Dict

# Load from environment
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL", "https://jellyfin.galagaon.com")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")

def get_jellyfin_headers():
    """Get authorization headers for Jellyfin API"""
    return {
        "Authorization": f'MediaBrowser Client="device-lister", Device="Python", DeviceId="device-lister-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    }

def get_current_sessions() -> List[Dict]:
    """Get currently active sessions"""
    try:
        response = requests.get(
            f"{JELLYFIN_BASE_URL}/Sessions",
            headers=get_jellyfin_headers(),
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error getting current sessions: {e}")
        return []

def get_all_devices() -> List[Dict]:
    """Get all devices that have ever connected"""
    try:
        response = requests.get(
            f"{JELLYFIN_BASE_URL}/Devices",
            headers=get_jellyfin_headers(),
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("Items", [])
    except Exception as e:
        print(f"❌ Error getting device list: {e}")
        return []

def format_datetime(iso_string: str) -> str:
    """Format ISO datetime string for display"""
    if not iso_string:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return iso_string

def display_current_sessions():
    """Display currently active sessions"""
    print("🔴 CURRENT ACTIVE SESSIONS")
    print("=" * 50)

    sessions = get_current_sessions()

    if not sessions:
        print("No active sessions found.")
        return

    for i, session in enumerate(sessions, 1):
        print(f"\n📱 Session {i}:")
        print(f"   ID: {session.get('Id', 'Unknown')}")
        print(f"   User: {session.get('UserName', 'Unknown')}")
        print(f"   Client: {session.get('Client', 'Unknown')}")
        print(f"   Device Name: {session.get('DeviceName', 'Unknown')}")
        print(f"   Device ID: {session.get('DeviceId', 'Unknown')}")
        print(f"   App Version: {session.get('ApplicationVersion', 'Unknown')}")
        print(f"   Remote Endpoint: {session.get('RemoteEndPoint', 'Unknown')}")

        # Show what's playing
        now_playing = session.get('NowPlayingItem')
        if now_playing:
            print(f"   ▶️  Playing: {now_playing.get('Name', 'Unknown')}")
            print(f"   Type: {now_playing.get('Type', 'Unknown')}")

            play_state = session.get('PlayState', {})
            if play_state:
                is_paused = play_state.get('IsPaused', False)
                position_ticks = play_state.get('PositionTicks', 0)
                position_seconds = position_ticks / 10_000_000 if position_ticks else 0
                status = "⏸️ Paused" if is_paused else "▶️ Playing"
                print(f"   Status: {status} @ {position_seconds:.1f}s")
        else:
            print(f"   Status: 💤 Idle")

def display_device_history():
    """Display all devices that have ever connected"""
    print("\n\n📚 ALL DEVICES (HISTORY)")
    print("=" * 50)

    devices = get_all_devices()

    if not devices:
        print("No devices found.")
        return

    print(f"Found {len(devices)} devices in history:\n")

    # Group devices by user
    devices_by_user = {}
    for device in devices:
        user_name = device.get('LastUserName', 'Unknown User')
        if user_name not in devices_by_user:
            devices_by_user[user_name] = []
        devices_by_user[user_name].append(device)

    for user_name, user_devices in devices_by_user.items():
        print(f"👤 {user_name} ({len(user_devices)} devices):")

        for device in user_devices:
            print(f"   📱 {device.get('Name', 'Unnamed Device')}")
            print(f"      ID: {device.get('Id', 'Unknown')}")
            print(f"      App Name: {device.get('AppName', 'Unknown')}")
            print(f"      App Version: {device.get('AppVersion', 'Unknown')}")
            print(f"      Last Activity: {format_datetime(device.get('DateLastActivity'))}")

            # Show capabilities if available
            caps = device.get('Capabilities', {})
            if caps:
                playable_types = caps.get('PlayableMediaTypes', [])
                if playable_types:
                    print(f"      Media Types: {', '.join(playable_types)}")

            print()
        print()

def generate_device_mapping_config():
    """Generate example device-WLED mapping configuration"""
    print("\n\n⚙️ DEVICE-WLED MAPPING SUGGESTIONS")
    print("=" * 50)

    # Get unique device names from both sessions and device history
    device_names = set()
    client_names = set()

    # From current sessions
    sessions = get_current_sessions()
    for session in sessions:
        if session.get('DeviceName'):
            device_names.add(session.get('DeviceName'))
        if session.get('Client'):
            client_names.add(session.get('Client'))

    # From device history
    devices = get_all_devices()
    for device in devices:
        if device.get('Name'):
            device_names.add(device.get('Name'))
        if device.get('AppName'):
            client_names.add(device.get('AppName'))

    print("Based on your devices, here are suggested environment variables:\n")

    print("# Option 1: Match by Device Name")
    print("DEVICE_MATCH_FIELD=DeviceName")
    for device_name in sorted(device_names):
        # Convert device name to env var format
        env_var = device_name.upper().replace(' ', '_').replace('-', '_')
        env_var = ''.join(c for c in env_var if c.isalnum() or c == '_')
        print(f"WLED_DEVICE_{env_var}=wled-{device_name.lower().replace(' ', '-')}.lan:21324")

    print("\n# Option 2: Match by Client")
    print("DEVICE_MATCH_FIELD=Client")
    for client_name in sorted(client_names):
        # Convert client name to env var format
        env_var = client_name.upper().replace(' ', '_').replace('-', '_')
        env_var = ''.join(c for c in env_var if c.isalnum() or c == '_')
        print(f"WLED_DEVICE_{env_var}=wled-{client_name.lower().replace(' ', '-')}.lan:21324")

def main():
    """Main function"""
    print("🔍 JELLYFIN DEVICE INFORMATION")
    print(f"Server: {JELLYFIN_BASE_URL}")
    print("=" * 70)

    # Show current sessions
    display_current_sessions()

    # Show device history
    display_device_history()

    # Generate configuration suggestions
    generate_device_mapping_config()

    print("\n" + "=" * 70)
    print("💡 TIP: Use this information to configure device-WLED pairing")
    print("   Copy the suggested environment variables to your .env file")

if __name__ == "__main__":
    main()
