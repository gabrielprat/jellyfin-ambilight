#!/usr/bin/env python3
"""
Detailed UDP Packet Analysis
============================

Analyze specific packets to understand LED color distribution and identify issues
"""

import os
import struct
from pathlib import Path
import socket

def analyze_single_udp_packet(packet: bytes, timestamp: float):
    """Detailed analysis of a single UDP packet"""
    print(f"\n📦 Packet at {timestamp:.2f}s:")
    print(f"   Size: {len(packet)} bytes")

    if len(packet) < 5:
        print("   ❌ Packet too short!")
        return

    # Header check
    header = packet[:4]
    if header != b'DRGB':
        print(f"   ❌ Invalid header: {header}")
        return

    timeout = packet[4]
    rgb_data = packet[5:]
    led_count = len(rgb_data) // 3

    print(f"   Header: {header.decode()}")
    print(f"   Timeout: {timeout}")
    print(f"   LEDs: {led_count}")

    # Color distribution analysis
    colors = {}
    brightness_levels = []

    for i in range(led_count):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]

        color = (r, g, b)
        colors[color] = colors.get(color, 0) + 1

        # Calculate brightness
        brightness = (r + g + b) / 3
        brightness_levels.append(brightness)

    print(f"   Unique colors: {len(colors)}")
    print(f"   Avg brightness: {sum(brightness_levels) / len(brightness_levels):.1f}")

    # Show color distribution
    sorted_colors = sorted(colors.items(), key=lambda x: x[1], reverse=True)
    print(f"   Top 5 colors:")
    for i, ((r, g, b), count) in enumerate(sorted_colors[:5]):
        percentage = (count / led_count) * 100
        print(f"      {i+1}. RGB({r:3d},{g:3d},{b:3d}): {count:3d} LEDs ({percentage:4.1f}%)")

    # Check for black/very dark pixels
    dark_count = sum(1 for (r, g, b) in colors.keys() if r < 10 and g < 10 and b < 10)
    if dark_count > led_count * 0.8:
        print(f"   ⚠️  {dark_count}/{led_count} LEDs are very dark!")

    # LED position analysis (corners)
    print(f"   Corner LEDs:")
    top_led = (rgb_data[0], rgb_data[1], rgb_data[2])
    quarter = led_count // 4
    right_led = (rgb_data[quarter*3], rgb_data[quarter*3+1], rgb_data[quarter*3+2])
    bottom_led = (rgb_data[quarter*2*3], rgb_data[quarter*2*3+1], rgb_data[quarter*2*3+2])
    left_led = (rgb_data[quarter*3*3], rgb_data[quarter*3*3+1], rgb_data[quarter*3*3+2])

    print(f"      Top: RGB{top_led}")
    print(f"      Right: RGB{right_led}")
    print(f"      Bottom: RGB{bottom_led}")
    print(f"      Left: RGB{left_led}")

    return packet

def send_packet_to_wled(packet: bytes, description: str = "test"):
    """Send packet to WLED for testing"""
    try:
        wled_host = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
        wled_port = int(os.getenv('WLED_UDP_PORT', '21324'))

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bytes_sent = sock.sendto(packet, (wled_host, wled_port))
        sock.close()

        print(f"   📡 Sent to WLED: {bytes_sent} bytes")
        return True

    except Exception as e:
        print(f"   ❌ WLED send failed: {e}")
        return False

def analyze_udp_file_detailed(file_path: str):
    """Analyze UDP file in detail"""
    print(f"🔬 Detailed Analysis: {Path(file_path).name}")
    print("=" * 60)

    with open(file_path, 'rb') as f:
        file_size = Path(file_path).stat().st_size
        packets_found = 0

        # Read a few packets for detailed analysis
        while f.tell() < file_size and packets_found < 5:
            # Read timestamp
            timestamp_bytes = f.read(4)
            if len(timestamp_bytes) < 4:
                break

            timestamp = struct.unpack('<f', timestamp_bytes)[0]

            # Read packet size
            size_bytes = f.read(4)
            if len(size_bytes) < 4:
                break

            packet_size = struct.unpack('<I', size_bytes)[0]

            # Read packet
            packet = f.read(packet_size)
            if len(packet) < packet_size:
                break

            # Analyze this packet
            test_packet = analyze_single_udp_packet(packet, timestamp)

            # Optionally send to WLED for testing
            if packets_found == 0:  # Send first packet to WLED
                print(f"   🧪 Testing this packet on WLED...")
                send_packet_to_wled(packet, f"packet_{packets_found}")

            packets_found += 1

            # Skip ahead a bit for variety
            if packets_found < 5:
                f.seek(f.tell() + 50000, 0)  # Skip ~50KB ahead

        print(f"\n📊 Analyzed {packets_found} packets from {Path(file_path).name}")

def main():
    """Main analysis"""
    # Analyze the good file with color variety
    good_file = "test-data/ambilight/udp/ff01be6472e67a3eaf95b693c0d8e417.udpdata"
    if Path(good_file).exists():
        analyze_udp_file_detailed(good_file)

    print("\n" + "=" * 60)

    # Analyze one of the problematic files
    bad_file = "test-data/ambilight/udp/faa7ead34becc3a2e32a6290da98c365.udpdata"
    if Path(bad_file).exists():
        analyze_udp_file_detailed(bad_file)

if __name__ == "__main__":
    main()
