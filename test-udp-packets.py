#!/usr/bin/env python3
"""
WLED UDP Packet Tester
======================

Analyze and test UDP packets being sent to WLED to identify issues with:
1. Packet format correctness
2. LED color data validity
3. WLED realtime mode activation
"""

import os
import socket
import time
from typing import List

WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))

def create_test_packet(led_count: int, pattern: str = "rainbow") -> bytes:
    """Create test UDP packets with different patterns"""

    # WLED UDP Protocol: DRGB + timeout + RGB data
    packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B')])

    # Timeout byte (1 = 1 second, 255 = permanent until next packet)
    packet.append(1)

    # Generate different test patterns
    if pattern == "rainbow":
        # Rainbow pattern - each LED different color
        for i in range(led_count):
            hue = (i * 360 // led_count) % 360
            r, g, b = hsv_to_rgb(hue, 255, 255)
            packet.extend([r, g, b])

    elif pattern == "red_all":
        # All LEDs red - should see uniform red
        for i in range(led_count):
            packet.extend([255, 0, 0])

    elif pattern == "alternating":
        # Alternating red/blue pattern
        for i in range(led_count):
            if i % 2 == 0:
                packet.extend([255, 0, 0])  # Red
            else:
                packet.extend([0, 0, 255])  # Blue

    elif pattern == "gradient":
        # Red to blue gradient
        for i in range(led_count):
            progress = i / max(1, led_count - 1)
            r = int(255 * (1 - progress))
            b = int(255 * progress)
            packet.extend([r, 0, b])

    elif pattern == "corners":
        # Different color for each corner/side
        quarter = led_count // 4
        for i in range(led_count):
            if i < quarter:
                packet.extend([255, 0, 0])      # Top: Red
            elif i < quarter * 2:
                packet.extend([0, 255, 0])      # Right: Green
            elif i < quarter * 3:
                packet.extend([0, 0, 255])      # Bottom: Blue
            else:
                packet.extend([255, 255, 0])    # Left: Yellow

    return bytes(packet)

def hsv_to_rgb(h: int, s: int, v: int) -> tuple:
    """Convert HSV to RGB (simplified)"""
    h = h % 360
    c = v * s // 255
    x = c * (1 - abs((h // 60) % 2 - 1))
    m = v - c

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return r + m, g + m, b + m

def analyze_packet(packet: bytes) -> None:
    """Analyze UDP packet structure"""
    print(f"\n📦 Packet Analysis:")
    print(f"   Total size: {len(packet)} bytes")

    if len(packet) < 5:
        print(f"   ❌ Packet too short! Expected at least 5 bytes")
        return

    # Check header
    header = packet[:4]
    if header == b'DRGB':
        print(f"   ✅ Header: DRGB (correct)")
    else:
        print(f"   ❌ Header: {header} (expected DRGB)")
        return

    # Check timeout
    timeout = packet[4]
    print(f"   ⏰ Timeout: {timeout} seconds")

    # Check LED data
    rgb_data = packet[5:]
    led_count = len(rgb_data) // 3
    print(f"   💡 LED count: {led_count}")
    print(f"   📊 RGB data size: {len(rgb_data)} bytes")

    if len(rgb_data) % 3 != 0:
        print(f"   ⚠️  Warning: RGB data not divisible by 3!")

    # Show first few LEDs
    print(f"   🎨 First 5 LEDs:")
    for i in range(min(5, led_count)):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]
        print(f"      LED {i}: R={r:3d} G={g:3d} B={b:3d}")

    # Check for all same color
    unique_colors = set()
    for i in range(led_count):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]
        unique_colors.add((r, g, b))

    print(f"   🌈 Unique colors: {len(unique_colors)}")
    if len(unique_colors) == 1:
        print(f"   ⚠️  All LEDs have the same color!")
    elif len(unique_colors) < led_count // 10:
        print(f"   ⚠️  Very few unique colors for {led_count} LEDs")

def send_test_packet(packet: bytes, description: str) -> bool:
    """Send test packet to WLED"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bytes_sent = sock.sendto(packet, (WLED_HOST, WLED_UDP_PORT))
        sock.close()

        print(f"✅ Sent {description}: {bytes_sent} bytes to {WLED_HOST}:{WLED_UDP_PORT}")
        return True

    except Exception as e:
        print(f"❌ Failed to send {description}: {e}")
        return False

def test_wled_protocol():
    """Test WLED UDP protocol with different patterns"""
    print(f"🧪 WLED UDP Protocol Tester")
    print(f"Target: {WLED_HOST}:{WLED_UDP_PORT}")
    print("=" * 50)

    # Test different LED counts
    led_counts = [276, 100, 50]  # Your setup, and smaller tests
    patterns = ["red_all", "rainbow", "alternating", "gradient", "corners"]

    for led_count in led_counts:
        print(f"\n🔢 Testing with {led_count} LEDs:")

        for pattern in patterns:
            packet = create_test_packet(led_count, pattern)
            analyze_packet(packet)

            if send_test_packet(packet, f"{pattern} ({led_count} LEDs)"):
                print(f"   💡 Check WLED: Should show {pattern} pattern")
                time.sleep(2)  # Wait to see the effect

        print("\n" + "-" * 30)

def test_realtime_mode():
    """Test what activates WLED realtime mode"""
    print(f"\n🔴 Testing WLED Realtime Mode Activation")
    print("=" * 50)

    led_count = 276

    # Test 1: Single packet with timeout=1
    print(f"\n1️⃣ Single packet (timeout=1):")
    packet = create_test_packet(led_count, "red_all")
    packet = packet[:4] + bytes([1]) + packet[5:]  # Set timeout to 1 second
    analyze_packet(packet)
    send_test_packet(packet, "Single red packet")
    print("   💡 WLED should show red for ~1 second, then return to normal")
    time.sleep(3)

    # Test 2: Continuous packets (like Hyperion)
    print(f"\n2️⃣ Continuous packets (10 packets/second for 5 seconds):")
    for i in range(50):  # 5 seconds at 10 FPS
        # Rotate colors
        hue = (i * 10) % 360
        r, g, b = hsv_to_rgb(hue, 255, 255)

        packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])
        packet.extend([r, g, b] * led_count)

        send_test_packet(bytes(packet), f"Continuous packet {i+1}/50")
        time.sleep(0.1)  # 10 FPS

    print("   💡 WLED should have entered realtime mode and shown rotating colors")

    # Test 3: High frequency packets
    print(f"\n3️⃣ High frequency packets (30 FPS for 3 seconds):")
    for i in range(90):  # 3 seconds at 30 FPS
        packet = create_test_packet(led_count, "alternating")
        send_test_packet(bytes(packet), f"Fast packet {i+1}/90")
        time.sleep(1/30)  # 30 FPS

    print("   💡 This should definitely activate realtime mode")

if __name__ == "__main__":
    print("🔬 WLED UDP Packet Analysis and Testing")
    print("=" * 60)

    # Basic protocol test
    test_wled_protocol()

    # Realtime mode test
    test_realtime_mode()

    print("\n" + "=" * 60)
    print("💡 Check your WLED device:")
    print("   - Did you see the different patterns?")
    print("   - Did WLED enter 'Live' or realtime mode?")
    print("   - Were individual LEDs showing different colors?")
