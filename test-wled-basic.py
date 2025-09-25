#!/usr/bin/env python3
"""
Basic WLED test to verify LED control functionality
"""

import requests
import json
import time
import os

# Environment variables
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))

def test_wled_info():
    """Get WLED device info"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/info"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        info = response.json()

        print("📊 WLED Device Info:")
        print(f"   Name: {info.get('name', 'Unknown')}")
        print(f"   Version: {info.get('ver', 'Unknown')}")
        print(f"   LED Count: {info.get('leds', {}).get('count', 'Unknown')}")
        print(f"   Max Power: {info.get('leds', {}).get('maxpwr', 'Unknown')}mA")
        print(f"   Current Effect: {info.get('effect', 'Unknown')}")

        return info
    except Exception as e:
        print(f"❌ Error getting WLED info: {e}")
        return None

def test_wled_state():
    """Get current WLED state"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        state = response.json()

        print("🔍 WLED Current State:")
        print(f"   Power: {'ON' if state.get('on', False) else 'OFF'}")
        print(f"   Brightness: {state.get('bri', 0)}/255")
        print(f"   Segments: {len(state.get('seg', []))}")

        for i, seg in enumerate(state.get('seg', [])):
            print(f"   Segment {i}: Start={seg.get('start', 0)}, Stop={seg.get('stop', 0)}, "
                  f"Color={seg.get('col', [[0,0,0]])}")

        return state
    except Exception as e:
        print(f"❌ Error getting WLED state: {e}")
        return None

def set_solid_color(r, g, b, brightness=128):
    """Set all LEDs to a solid color"""
    try:
        payload = {
            "on": True,
            "bri": brightness,
            "seg": [{
                "col": [[r, g, b]]
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print(f"✅ Set LEDs to RGB({r}, {g}, {b}) at brightness {brightness}")
        return True

    except Exception as e:
        print(f"❌ Error setting solid color: {e}")
        return False

def set_individual_leds(led_colors):
    """Set individual LED colors using the 'i' parameter"""
    try:
        # Convert RGB list to flat array for WLED
        wled_colors = []
        for color in led_colors:
            if len(color) >= 3:
                wled_colors.extend([int(color[0]), int(color[1]), int(color[2])])
            else:
                wled_colors.extend([0, 0, 0])

        # Limit to reasonable number of LEDs for testing
        max_leds = 50
        if len(wled_colors) > max_leds * 3:
            wled_colors = wled_colors[:max_leds * 3]

        payload = {
            "on": True,
            "bri": 128,
            "seg": [{
                "i": wled_colors
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print(f"✅ Set {len(led_colors)} individual LED colors")
        return True

    except Exception as e:
        print(f"❌ Error setting individual LEDs: {e}")
        print(f"   Payload size: {len(wled_colors)} values")
        return False

def turn_off():
    """Turn off WLED"""
    try:
        payload = {"on": False}
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        print("✅ Turned off LEDs")
        return True
    except Exception as e:
        print(f"❌ Error turning off: {e}")
        return False

def main():
    print("🧪 WLED Basic Test")
    print(f"🔗 Target: {WLED_HOST}:{WLED_PORT}")
    print("=" * 40)

    # Get device info
    info = test_wled_info()
    if not info:
        print("❌ Cannot connect to WLED device")
        return

    print()

    # Get current state
    test_wled_state()
    print()

    # Test 1: Solid Red
    print("🔴 Test 1: Solid Red (3 seconds)")
    if set_solid_color(255, 0, 0, 128):
        time.sleep(3)

    # Test 2: Solid Green
    print("🟢 Test 2: Solid Green (3 seconds)")
    if set_solid_color(0, 255, 0, 128):
        time.sleep(3)

    # Test 3: Solid Blue
    print("🔵 Test 3: Solid Blue (3 seconds)")
    if set_solid_color(0, 0, 255, 128):
        time.sleep(3)

    # Test 4: Individual LED colors (rainbow pattern)
    print("🌈 Test 4: Rainbow pattern (first 50 LEDs, 5 seconds)")
    rainbow_colors = []
    for i in range(50):
        # Create rainbow pattern
        hue = (i * 360 // 50) % 360
        # Simple HSV to RGB conversion for rainbow
        if hue < 60:
            r, g, b = 255, int(hue * 255 / 60), 0
        elif hue < 120:
            r, g, b = int((120 - hue) * 255 / 60), 255, 0
        elif hue < 180:
            r, g, b = 0, 255, int((hue - 120) * 255 / 60)
        elif hue < 240:
            r, g, b = 0, int((240 - hue) * 255 / 60), 255
        elif hue < 300:
            r, g, b = int((hue - 240) * 255 / 60), 0, 255
        else:
            r, g, b = 255, 0, int((360 - hue) * 255 / 60)

        rainbow_colors.append([r, g, b])

    if set_individual_leds(rainbow_colors):
        time.sleep(5)

    # Test 5: Full brightness white
    print("⚪ Test 5: Full brightness white (3 seconds)")
    if set_solid_color(255, 255, 255, 255):
        time.sleep(3)

    # Turn off
    print("⚫ Turning off LEDs")
    turn_off()

    print("\n✅ Basic WLED test completed!")
    print("💡 If you didn't see the LEDs change, check:")
    print("   - WLED power supply")
    print("   - LED strip connections")
    print("   - WLED segment configuration")
    print("   - LED type settings in WLED")

if __name__ == "__main__":
    main()
