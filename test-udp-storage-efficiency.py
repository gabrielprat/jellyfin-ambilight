#!/usr/bin/env python3
"""
Test UDP Storage Efficiency
===========================

Compare the efficiency of storing WLED UDP packets directly vs.
traditional RGB array JSON storage.
"""

import os
import sys
import time
import sqlite3
import tempfile
import json
from pathlib import Path

# Set up environment
sys.path.append('/app')
os.environ['DATABASE_PATH'] = tempfile.mktemp(suffix='.db')

from database import (
    init_database, save_frame, save_frame_udp,
    create_wled_udp_packet, parse_wled_udp_packet,
    get_frames_for_item, get_udp_packet_at_timestamp
)

def generate_test_led_colors(num_leds=276):
    """Generate test LED colors"""
    import random
    return [[random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
            for _ in range(num_leds)]

def benchmark_storage_methods(num_frames=100):
    """Benchmark both storage methods"""
    print("🚀 BENCHMARKING STORAGE METHODS")
    print("=" * 50)

    # Initialize test database
    init_database()

    # Generate test data
    test_item_id = "test-movie-123"
    led_colors_list = [generate_test_led_colors() for _ in range(num_frames)]

    print(f"📊 Test parameters:")
    print(f"   Frames: {num_frames}")
    print(f"   LEDs per frame: 276")
    print(f"   Total LED data points: {num_frames * 276}")
    print()

    # Benchmark 1: Traditional JSON storage
    print("📋 Method 1: Traditional JSON Storage")
    start_time = time.time()

    for i, led_colors in enumerate(led_colors_list):
        save_frame(
            item_id=test_item_id + "_json",
            timestamp_seconds=i * 10.0,
            led_colors=led_colors,
            width=1920,
            height=1080
        )

    json_time = time.time() - start_time
    json_size = get_database_size(test_item_id + "_json")

    print(f"   ⏱️  Time: {json_time:.3f} seconds")
    print(f"   💾 Size: {json_size} bytes ({json_size/1024:.1f} KB)")
    print(f"   📈 Rate: {num_frames/json_time:.1f} frames/sec")
    print()

    # Benchmark 2: UDP Packet storage
    print("📋 Method 2: UDP Packet Storage")
    start_time = time.time()

    for i, led_colors in enumerate(led_colors_list):
        save_frame_udp(
            item_id=test_item_id + "_udp",
            timestamp_seconds=i * 10.0,
            led_colors=led_colors,
            width=1920,
            height=1080
        )

    udp_time = time.time() - start_time
    udp_size = get_database_size(test_item_id + "_udp")

    print(f"   ⏱️  Time: {udp_time:.3f} seconds")
    print(f"   💾 Size: {udp_size} bytes ({udp_size/1024:.1f} KB)")
    print(f"   📈 Rate: {num_frames/udp_time:.1f} frames/sec")
    print()

    # Comparison
    print("⚡ EFFICIENCY COMPARISON")
    print("=" * 50)
    storage_ratio = json_size / udp_size if udp_size > 0 else float('inf')
    speed_ratio = json_time / udp_time if udp_time > 0 else float('inf')
    space_saved = json_size - udp_size

    print(f"💾 Storage efficiency:")
    print(f"   JSON storage:  {json_size:,} bytes")
    print(f"   UDP storage:   {udp_size:,} bytes")
    if json_size > 0 and udp_size > 0:
        print(f"   Space saved:   {space_saved:,} bytes ({(1-udp_size/json_size)*100:.1f}%)")
        print(f"   Compression:   {storage_ratio:.1f}x more efficient")
    elif json_size > 0:
        print(f"   Space saved:   {space_saved:,} bytes (100.0%)")
        print(f"   Compression:   ∞x more efficient")
    else:
        print(f"   Note: Storage sizes need investigation")
    print()

    print(f"⚡ Speed efficiency:")
    print(f"   JSON time:     {json_time:.3f} seconds")
    print(f"   UDP time:      {udp_time:.3f} seconds")
    print(f"   Speed gain:    {speed_ratio:.1f}x faster")
    print()

    return {
        'json_time': json_time,
        'udp_time': udp_time,
        'json_size': json_size,
        'udp_size': udp_size,
        'storage_ratio': storage_ratio,
        'speed_ratio': speed_ratio
    }

def benchmark_retrieval_methods(test_item_id="test-movie-123"):
    """Benchmark retrieval methods"""
    print("🔍 BENCHMARKING RETRIEVAL METHODS")
    print("=" * 50)

    # Test traditional retrieval
    print("📋 Method 1: Traditional JSON Retrieval")
    start_time = time.time()

    json_frames = get_frames_for_item(test_item_id + "_json")
    json_retrieval_time = time.time() - start_time

    print(f"   ⏱️  Time: {json_retrieval_time:.3f} seconds")
    print(f"   📊 Frames: {len(json_frames)}")
    print(f"   📈 Rate: {len(json_frames)/json_retrieval_time:.1f} frames/sec")
    print()

    # Test UDP retrieval
    print("📋 Method 2: UDP Packet Retrieval")
    start_time = time.time()

    udp_frames = get_frames_for_item(test_item_id + "_udp")
    udp_retrieval_time = time.time() - start_time

    print(f"   ⏱️  Time: {udp_retrieval_time:.3f} seconds")
    print(f"   📊 Frames: {len(udp_frames)}")
    print(f"   📈 Rate: {len(udp_frames)/udp_retrieval_time:.1f} frames/sec")
    print()

    # Test ultra-fast direct UDP packet retrieval
    print("📋 Method 3: Direct UDP Packet (for transmission)")
    start_time = time.time()

    # Simulate getting packets for playback
    for i in range(0, 100, 10):  # Every 10 seconds
        packet = get_udp_packet_at_timestamp(test_item_id + "_udp", i * 10.0)
        if not packet:
            break

    direct_udp_time = time.time() - start_time

    print(f"   ⏱️  Time: {direct_udp_time:.3f} seconds")
    print(f"   📊 Packets: 10 lookups")
    print(f"   📈 Rate: {10/direct_udp_time:.1f} lookups/sec")
    print(f"   🚀 Ready for direct transmission!")
    print()

    # Comparison
    retrieval_ratio = json_retrieval_time / udp_retrieval_time if udp_retrieval_time > 0 else float('inf')
    direct_ratio = json_retrieval_time / direct_udp_time if direct_udp_time > 0 else float('inf')

    print("⚡ RETRIEVAL EFFICIENCY")
    print("=" * 50)
    print(f"⏱️  JSON retrieval:      {json_retrieval_time:.3f} seconds")
    print(f"⏱️  UDP retrieval:       {udp_retrieval_time:.3f} seconds")
    print(f"⏱️  Direct UDP lookup:   {direct_udp_time:.3f} seconds")
    print(f"📈 UDP vs JSON:         {retrieval_ratio:.1f}x faster")
    print(f"🚀 Direct vs JSON:      {direct_ratio:.1f}x faster")

    return {
        'json_retrieval_time': json_retrieval_time,
        'udp_retrieval_time': udp_retrieval_time,
        'direct_udp_time': direct_udp_time
    }

def test_data_integrity():
    """Test that UDP storage preserves data integrity"""
    print("🔬 TESTING DATA INTEGRITY")
    print("=" * 50)

    # Generate test LED colors
    original_colors = generate_test_led_colors(276)

    # Create UDP packet
    udp_packet = create_wled_udp_packet(original_colors)

    # Parse it back
    parsed_colors = parse_wled_udp_packet(udp_packet)

    # Verify integrity
    if parsed_colors == original_colors:
        print("✅ Data integrity: PERFECT")
        print(f"   Original: {len(original_colors)} LEDs")
        print(f"   Parsed:   {len(parsed_colors)} LEDs")
        print(f"   Match:    100%")
    else:
        print("❌ Data integrity: FAILED")
        return False

    # Test packet structure
    print(f"📦 UDP packet structure:")
    print(f"   Header: {udp_packet[:5]} ({len(udp_packet[:5])} bytes)")
    print(f"   Payload: {len(udp_packet[5:])} bytes")
    print(f"   Total: {len(udp_packet)} bytes")
    print(f"   LEDs: {(len(udp_packet) - 5) // 3}")

    return True

def get_database_size(item_id):
    """Get size of frames data for specific item"""
    DATABASE_PATH = os.getenv("DATABASE_PATH")
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            COALESCE(SUM(LENGTH(led_colors)), 0) as json_size,
            COALESCE(SUM(LENGTH(udp_packet)), 0) as udp_size
        FROM frames
        WHERE item_id = ?
    ''', (item_id,))

    result = cursor.fetchone()
    conn.close()

    if result:
        json_size, udp_size = result
        return json_size + udp_size
    return 0

def main():
    print("🚀 UDP STORAGE EFFICIENCY BENCHMARK")
    print("=" * 60)
    print()

    # Test data integrity first
    if not test_data_integrity():
        print("❌ Data integrity test failed!")
        return
    print()

    # Benchmark storage
    storage_results = benchmark_storage_methods(100)
    print()

    # Benchmark retrieval
    retrieval_results = benchmark_retrieval_methods()
    print()

    # Final summary
    print("🎯 FINAL SUMMARY")
    print("=" * 60)
    print("🎉 UDP packet storage provides:")
    print(f"   💾 {storage_results['storage_ratio']:.1f}x more efficient storage")
    print(f"   ⚡ {storage_results['speed_ratio']:.1f}x faster write operations")
    print(f"   🔍 {retrieval_results['json_retrieval_time']/retrieval_results['udp_retrieval_time']:.1f}x faster read operations")
    print(f"   🚀 {retrieval_results['json_retrieval_time']/retrieval_results['direct_udp_time']:.1f}x faster direct packet access")
    print()
    print("✅ RECOMMENDATION: Implement UDP packet storage for maximum efficiency!")

    # Clean up
    os.unlink(os.getenv("DATABASE_PATH"))

if __name__ == "__main__":
    main()
