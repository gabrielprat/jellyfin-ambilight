#!/usr/bin/env python3
"""
Fix WLED frozen segment issue
"""

import requests
import json
import time
import os

WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_TIMEOUT = int(os.getenv('WLED_TIMEOUT', '5'))

def unfreeze_wled_segment():
    """Unfreeze WLED segment to allow color updates"""
    try:
        print("🔓 Unfreezing WLED segment...")

        payload = {
            "seg": [{
                "id": 0,
                "frz": False,  # Unfreeze the segment
                "on": True,
                "start": 0,
                "stop": 300
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print("✅ Segment unfrozen successfully")
        print(f"   Response: {response.json()}")
        return True

    except Exception as e:
        print(f"❌ Error unfreezing segment: {e}")
        return False

def test_after_unfreeze():
    """Test colors after unfreezing"""
    try:
        print("\n🧪 Testing colors after unfreeze...")

        # Test 1: Solid red
        payload = {
            "on": True,
            "bri": 255,
            "seg": [{
                "start": 0,
                "stop": 300,
                "col": [[255, 0, 0, 0]]  # Red RGBW
            }]
        }

        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print("🔴 Set to solid red - should see red LEDs now!")
        time.sleep(3)

        # Test 2: Solid blue
        payload["seg"][0]["col"] = [[0, 0, 255, 0]]  # Blue RGBW
        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print("🔵 Set to solid blue - should see blue LEDs now!")
        time.sleep(3)

        # Test 3: Rainbow using individual LED control
        print("🌈 Setting rainbow pattern...")

        wled_colors = []
        for i in range(300):
            hue = (i * 360 // 300) % 360
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

            wled_colors.extend([r, g, b, 0])  # RGBW

        payload = {
            "on": True,
            "bri": 255,
            "seg": [{
                "start": 0,
                "stop": 300,
                "i": wled_colors
            }]
        }

        response = requests.post(url, json=payload, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        print("🌈 Rainbow pattern set - should see full rainbow!")

        return True

    except Exception as e:
        print(f"❌ Error testing colors: {e}")
        return False

def get_segment_status():
    """Check current segment status"""
    try:
        url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
        response = requests.get(url, timeout=WLED_TIMEOUT)
        response.raise_for_status()

        state = response.json()
        seg = state.get('seg', [{}])[0]

        print("📊 Current Segment Status:")
        print(f"   Frozen: {seg.get('frz', False)}")
        print(f"   On: {seg.get('on', False)}")
        print(f"   Brightness: {seg.get('bri', 0)}")
        print(f"   Start-Stop: {seg.get('start', 0)}-{seg.get('stop', 0)}")
        print(f"   Effect: {seg.get('fx', 0)}")

        return seg.get('frz', False)

    except Exception as e:
        print(f"❌ Error getting status: {e}")
        return None

def main():
    print("🔧 WLED Frozen Segment Fix")
    print(f"🔗 Target: {WLED_HOST}:{WLED_PORT}")
    print("=" * 40)

    # Check current status
    is_frozen = get_segment_status()

    if is_frozen:
        print("\n⚠️  Segment IS FROZEN - this prevents color updates!")

        # Unfreeze segment
        if unfreeze_wled_segment():
            print("\n✅ Segment unfrozen successfully")

            # Test colors
            test_after_unfreeze()
        else:
            print("\n❌ Failed to unfreeze segment")
    else:
        print("\n✅ Segment is not frozen")
        test_after_unfreeze()

    print("\n🎯 If you see colors changing now, the issue was the frozen segment!")
    print("   Your ambilight system should work properly now.")

if __name__ == "__main__":
    main()
