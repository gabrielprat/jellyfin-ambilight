#!/usr/bin/env python3
"""
Test WLED with proper RGBW format
"""

import requests
import json
import time
import os

WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))

def turn_on_wled():
    """Ensure WLED is turned on"""
    try:
        payload = {
            "on": True,
            "bri": 255
        }
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()
        print("✅ WLED turned ON")
        return True
    except Exception as e:
        print(f"❌ Error turning on WLED: {e}")
        return False

def set_rgbw_color(r, g, b, w=0, brightness=255):
    """Set RGBW color properly"""
    try:
        payload = {
            "on": True,
            "bri": brightness,
            "seg": [{
                "start": 0,
                "stop": 50,  # First 50 LEDs for testing
                "col": [[r, g, b, w]],  # RGBW format
                "fx": 0  # Solid effect
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print(f"✅ Set RGBW color: R={r}, G={g}, B={b}, W={w}")
        return True

    except Exception as e:
        print(f"❌ Error setting RGBW color: {e}")
        return False

def set_individual_rgbw_leds(led_colors):
    """Set individual LED colors in RGBW format"""
    try:
        # Convert RGB to RGBW format
        wled_colors = []
        for color in led_colors[:50]:  # First 50 LEDs
            if len(color) >= 3:
                r, g, b = int(color[0]), int(color[1]), int(color[2])
                w = 0  # No white channel for now
                wled_colors.extend([r, g, b, w])
            else:
                wled_colors.extend([0, 0, 0, 0])

        payload = {
            "on": True,
            "bri": 255,
            "seg": [{
                "start": 0,
                "stop": len(led_colors),
                "i": wled_colors
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print(f"✅ Set {len(led_colors)} individual RGBW LEDs")
        return True

    except Exception as e:
        print(f"❌ Error setting individual RGBW LEDs: {e}")
        print(f"   Payload size: {len(wled_colors)} values")
        return False

def test_web_interface():
    """Test if we can control via web interface API"""
    try:
        # Try the web interface control endpoint
        url = f"http://{WLED_HOST}:{WLED_PORT}/win&T=1&A=255&R=255&G=0&B=0"
        response = requests.get(url, timeout=WLED_TIMEOUT)

        print(f"✅ Web interface control sent (status: {response.status_code})")
        return True

    except Exception as e:
        print(f"❌ Error with web interface control: {e}")
        return False

def main():
    print("🧪 RGBW WLED Test")
    print(f"🔗 Target: {WLED_HOST}:{WLED_PORT}")
    print("=" * 40)

    # Turn on WLED first
    if not turn_on_wled():
        return

    time.sleep(1)

    # Test 1: Solid Red RGBW
    print("🔴 Test 1: Solid Red RGBW (5 seconds)")
    if set_rgbw_color(255, 0, 0, 0, 255):
        time.sleep(5)

    # Test 2: Solid Green RGBW
    print("🟢 Test 2: Solid Green RGBW (5 seconds)")
    if set_rgbw_color(0, 255, 0, 0, 255):
        time.sleep(5)

    # Test 3: Solid Blue RGBW
    print("🔵 Test 3: Solid Blue RGBW (5 seconds)")
    if set_rgbw_color(0, 0, 255, 0, 255):
        time.sleep(5)

    # Test 4: White channel only
    print("⚪ Test 4: White channel only (5 seconds)")
    if set_rgbw_color(0, 0, 0, 255, 255):
        time.sleep(5)

    # Test 5: Web interface control
    print("🌐 Test 5: Web interface control - Red (5 seconds)")
    if test_web_interface():
        time.sleep(5)

    # Test 6: Individual LEDs with rainbow
    print("🌈 Test 6: Rainbow pattern RGBW (5 seconds)")
    rainbow_colors = []
    for i in range(50):
        hue = (i * 360 // 50) % 360
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

    if set_individual_rgbw_leds(rainbow_colors):
        time.sleep(5)

    print("\n✅ RGBW test completed!")
    print("\n💡 If LEDs still don't work, the issue is likely:")
    print("   1. Hardware: LED strip not connected to correct GPIO pin")
    print("   2. Power: Insufficient power supply")
    print("   3. LED Type: Wrong LED type configured in WLED")
    print("   4. GPIO: Wrong GPIO pin configured")
    print(f"\n🌐 Check WLED web interface: http://{WLED_HOST}")

if __name__ == "__main__":
    main()
