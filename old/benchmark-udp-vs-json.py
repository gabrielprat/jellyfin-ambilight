#!/usr/bin/env python3
"""
Benchmark UDP vs JSON API performance for WLED
"""

import time
import socket
import requests
import os

WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_PORT = int(os.getenv('WLED_PORT', '80'))
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))

def benchmark_json_api(num_updates=100):
    """Benchmark JSON API performance"""
    print(f"🔥 Benchmarking JSON API ({num_updates} updates)")

    session = requests.Session()
    session.timeout = 5

    # Test colors (rainbow pattern)
    colors = []
    for i in range(276):  # Our LED count
        hue = (i * 360 // 276) % 360
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
        colors.extend([r, g, b, 0])  # RGBW

    url = f"http://{WLED_HOST}:{WLED_PORT}/json/state"
    success_count = 0

    start_time = time.time()

    for i in range(num_updates):
        try:
            # Shift colors for animation effect
            shifted_colors = colors[i*12:] + colors[:i*12]

            payload = {
                "on": True,
                "bri": 255,
                "seg": [{
                    "start": 0,
                    "stop": 300,
                    "i": shifted_colors
                }]
            }

            response = session.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                success_count += 1

            print(f"\r   JSON: {i+1}/{num_updates} ({success_count} success)", end='')

        except Exception as e:
            print(f"\r   JSON Error: {e}", end='')

    end_time = time.time()
    total_time = end_time - start_time

    print(f"\n📊 JSON API Results:")
    print(f"   Total time: {total_time:.2f}s")
    print(f"   Success rate: {success_count}/{num_updates} ({success_count/num_updates*100:.1f}%)")
    print(f"   Average time per update: {total_time/num_updates*1000:.1f}ms")
    print(f"   Updates per second: {success_count/total_time:.1f}")

    return total_time, success_count

def benchmark_udp(num_updates=100):
    """Benchmark UDP performance"""
    print(f"\n⚡ Benchmarking UDP ({num_updates} updates)")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Test colors (rainbow pattern)
    base_colors = []
    for i in range(276):  # Our LED count
        hue = (i * 360 // 276) % 360
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
        base_colors.append([r, g, b])

    success_count = 0

    start_time = time.time()

    for i in range(num_updates):
        try:
            # DRGB protocol: [DRGB][timeout][rgb_data...]
            packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])

            # Shift colors for animation effect
            shift = i % len(base_colors)
            shifted_colors = base_colors[shift:] + base_colors[:shift]

            for color in shifted_colors:
                packet.extend(color)

            sock.sendto(packet, (WLED_HOST, WLED_UDP_PORT))
            success_count += 1

            print(f"\r   UDP: {i+1}/{num_updates} ({success_count} success)", end='')

        except Exception as e:
            print(f"\r   UDP Error: {e}", end='')

    end_time = time.time()
    total_time = end_time - start_time

    sock.close()

    print(f"\n📊 UDP Results:")
    print(f"   Total time: {total_time:.2f}s")
    print(f"   Success rate: {success_count}/{num_updates} ({success_count/num_updates*100:.1f}%)")
    print(f"   Average time per update: {total_time/num_updates*1000:.1f}ms")
    print(f"   Updates per second: {success_count/total_time:.1f}")

    return total_time, success_count

def main():
    print("⚡ WLED Protocol Performance Benchmark")
    print(f"🔗 Target: {WLED_HOST}")
    print("=" * 50)

    num_updates = 50  # Reasonable number for testing

    # Benchmark JSON API
    json_time, json_success = benchmark_json_api(num_updates)

    # Benchmark UDP
    udp_time, udp_success = benchmark_udp(num_updates)

    # Summary comparison
    print(f"\n🏁 Performance Comparison:")
    print("=" * 50)

    if json_success > 0 and udp_success > 0:
        speedup = json_time / udp_time
        print(f"📈 UDP is {speedup:.1f}x faster than JSON API")

        json_fps = json_success / json_time
        udp_fps = udp_success / udp_time
        print(f"🎬 JSON API: {json_fps:.1f} updates/sec")
        print(f"⚡ UDP: {udp_fps:.1f} updates/sec")

        print(f"\n💡 For real-time ambilight:")
        print(f"   JSON API: suitable for ~{int(json_fps)} FPS")
        print(f"   UDP: suitable for ~{int(udp_fps)} FPS")

        if udp_fps >= 20:
            print("   ✅ UDP can handle smooth ambilight at 20+ FPS")
        else:
            print("   ⚠️  Network latency may limit UDP performance")

        if json_fps >= 10:
            print("   ✅ JSON API can handle basic ambilight at 10+ FPS")
        else:
            print("   ❌ JSON API too slow for smooth ambilight")

    print(f"\n🎯 Recommendation: Use UDP for real-time ambilight!")

if __name__ == "__main__":
    main()
