#!/usr/bin/env python3
"""
Debug WLED configuration and settings
"""

import requests
import json
import os

WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))

def get_wled_config():
    """Get WLED configuration details"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        print("🔧 WLED Complete Configuration:")
        print(json.dumps(data, indent=2))

        return data
    except Exception as e:
        print(f"❌ Error getting WLED config: {e}")
        return None

def check_led_settings(config):
    """Check LED-specific settings"""
    if not config:
        return

    info = config.get('info', {})
    leds = info.get('leds', {})

    print("\n🔍 LED Configuration Analysis:")
    print(f"   Total LEDs: {leds.get('count', 'Unknown')}")
    print(f"   Max Power: {leds.get('maxpwr', 'Unknown')}mA")
    print(f"   Power Estimation: {leds.get('pwr', 'Unknown')}mA")
    print(f"   LED Types: {leds.get('lc', 'Unknown')}")

    # Check segments
    state = config.get('state', {})
    segments = state.get('seg', [])

    print(f"\n📐 Segment Configuration:")
    for i, seg in enumerate(segments):
        print(f"   Segment {i}:")
        print(f"     Start: {seg.get('start', 0)}")
        print(f"     Stop: {seg.get('stop', 0)}")
        print(f"     Length: {seg.get('len', seg.get('stop', 0) - seg.get('start', 0))}")
        print(f"     On: {seg.get('on', True)}")
        print(f"     Brightness: {seg.get('bri', 'inherit')}")
        print(f"     Colors: {seg.get('col', [])}")
        print(f"     Effect: {seg.get('fx', 0)}")
        print(f"     Speed: {seg.get('sx', 128)}")
        print(f"     Intensity: {seg.get('ix', 128)}")

def force_simple_setup():
    """Force a simple LED setup for testing"""
    try:
        print("\n🔨 Forcing simple LED setup...")

        # Clear any effects and set simple solid color
        payload = {
            "on": True,
            "bri": 255,  # Full brightness
            "seg": [{
                "start": 0,
                "stop": 50,  # Just first 50 LEDs
                "on": True,
                "bri": 255,
                "col": [[255, 0, 0]],  # Solid red
                "fx": 0,  # Solid effect
                "sx": 128,
                "ix": 128
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print("✅ Applied simple red setup to first 50 LEDs")
        print("   If you don't see red LEDs now, the issue is hardware/config")

        return True

    except Exception as e:
        print(f"❌ Error applying simple setup: {e}")
        return False

def main():
    print("🔍 WLED Debug Tool")
    print(f"🔗 Target: {WLED_HOST}:{WLED_PORT}")
    print("=" * 50)

    # Get full configuration
    config = get_wled_config()

    # Analyze LED settings
    check_led_settings(config)

    print("\n" + "=" * 50)

    # Force simple setup
    force_simple_setup()

    print(f"\n💡 Next steps:")
    print(f"   1. Check WLED web interface: http://{WLED_HOST}")
    print(f"   2. Verify LED strip is connected to correct GPIO pin")
    print(f"   3. Check power supply (needs sufficient amperage)")
    print(f"   4. Verify LED type in WLED settings (WS2812B, etc.)")
    print(f"   5. Check if GPIO pin is configured correctly in WLED")

if __name__ == "__main__":
    main()
