#!/usr/bin/env python3
"""
Analyze Stored UDP Packets
==========================

Examines UDP packets stored in the ambilight data files to identify issues
with color variety and packet structure.
"""

import os
import struct
from pathlib import Path
from collections import Counter

AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")

def analyze_udp_file(udp_file_path: Path):
    """Analyze a single .udpdata file"""
    print(f"\n📁 Analyzing: {udp_file_path.name}")

    try:
        with open(udp_file_path, 'rb') as f:
            file_size = udp_file_path.stat().st_size
            packets_analyzed = 0
            color_stats = Counter()
            unique_packets = set()
            packet_sizes = []

            while f.tell() < file_size:
                # Read timestamp (4 bytes)
                timestamp_bytes = f.read(4)
                if len(timestamp_bytes) < 4:
                    break

                timestamp = struct.unpack('<f', timestamp_bytes)[0]

                # Read packet size (4 bytes)
                size_bytes = f.read(4)
                if len(size_bytes) < 4:
                    break

                packet_size = struct.unpack('<I', size_bytes)[0]
                packet_sizes.append(packet_size)

                # Read UDP packet
                udp_packet = f.read(packet_size)
                if len(udp_packet) < packet_size:
                    break

                # Analyze packet
                analyze_single_packet(udp_packet, timestamp, color_stats, unique_packets)
                packets_analyzed += 1

                # Limit analysis for very large files
                if packets_analyzed >= 100:
                    break

            # Summary
            print(f"   📊 Packets analyzed: {packets_analyzed}")
            print(f"   📏 Packet sizes: {min(packet_sizes)} - {max(packet_sizes)} bytes")
            print(f"   🌈 Unique color patterns: {len(unique_packets)}")

            if len(unique_packets) < packets_analyzed // 10:
                print(f"   ⚠️  Very few unique patterns! ({len(unique_packets)}/{packets_analyzed})")

            # Most common colors
            print(f"   🎨 Most common colors:")
            for color, count in color_stats.most_common(5):
                r, g, b = color
                print(f"      RGB({r:3d},{g:3d},{b:3d}): {count} LEDs")

    except Exception as e:
        print(f"   ❌ Error analyzing file: {e}")

def analyze_single_packet(packet: bytes, timestamp: float, color_stats: Counter, unique_packets: set):
    """Analyze a single UDP packet"""
    if len(packet) < 5:
        return

    # Check header
    if packet[:4] != b'DRGB':
        return

    # Extract RGB data
    rgb_data = packet[5:]
    led_count = len(rgb_data) // 3

    if led_count == 0:
        return

    # Count colors and create pattern signature
    colors_in_packet = []
    for i in range(led_count):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]
        color = (r, g, b)
        colors_in_packet.append(color)
        color_stats[color] += 1

    # Create a pattern signature (first 10 colors)
    pattern = tuple(colors_in_packet[:min(10, len(colors_in_packet))])
    unique_packets.add(pattern)

def find_udp_files() -> list:
    """Find all UDP data files"""
    data_dir = Path(AMBILIGHT_DATA_DIR)
    udp_dir = data_dir / "udp"

    if not udp_dir.exists():
        print(f"❌ UDP directory not found: {udp_dir}")
        return []

    udp_files = list(udp_dir.glob("*.udpdata"))
    print(f"📂 Found {len(udp_files)} UDP data files")

    return udp_files

def main():
    """Main analysis function"""
    print("🔍 Analyzing Stored UDP Packets")
    print("=" * 50)

    udp_files = find_udp_files()

    if not udp_files:
        print("❌ No UDP data files found!")
        print(f"   Expected location: {AMBILIGHT_DATA_DIR}/udp/")
        print("   Run frame extraction first to generate data.")
        return

    # Analyze each file
    for udp_file in udp_files[:5]:  # Limit to first 5 files
        analyze_udp_file(udp_file)

    if len(udp_files) > 5:
        print(f"\n... and {len(udp_files) - 5} more files")

    print("\n" + "=" * 50)
    print("💡 What to look for:")
    print("   - Unique color patterns should be high")
    print("   - Packet sizes should be consistent")
    print("   - Colors should vary across the spectrum")
    print("   - Few repeated RGB values indicates good extraction")

if __name__ == "__main__":
    main()
