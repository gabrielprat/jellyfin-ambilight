#!/usr/bin/env python3
"""
Test different frame extraction rates and their impact
"""

def analyze_frame_rate(fps, description):
    """Analyze storage and performance for a given frame rate"""
    interval = 1.0 / fps

    print(f"\n🎬 {fps} FPS ({description})")
    print(f"   Interval: {interval} seconds")

    # Test video lengths
    durations = [
        ("Short scene", 30),
        ("TV episode", 25 * 60),
        ("Movie", 120 * 60),
        ("Sonic movie", 6617)
    ]

    print("   Storage requirements:")
    for name, seconds in durations:
        frames = int(seconds * fps)
        db_size_mb = (frames * 276 * 20) / (1024 * 1024)  # Rough estimate
        print(f"     {name.ljust(12)}: {frames:,} frames (~{db_size_mb:.1f} MB)")

def main():
    print("📊 FRAME RATE COMPARISON FOR AMBILIGHT")
    print("=" * 60)

    # Different frame rates to consider
    rates = [
        (1, "Current - Too slow"),
        (5, "Minimum acceptable"),
        (10, "Hyperion minimum - Good"),
        (15, "Better quality"),
        (20, "Hyperion default - Excellent"),
        (30, "Very smooth - High storage")
    ]

    for fps, desc in rates:
        analyze_frame_rate(fps, desc)

    print(f"\n🎯 RECOMMENDATIONS:")
    print(f"   📚 TV Shows/Episodes: 10-15 FPS (good quality, manageable storage)")
    print(f"   🎬 Movies: 15-20 FPS (smooth ambilight, worth the storage)")
    print(f"   🚀 Action/Fast content: 20 FPS (Hyperion default)")
    print(f"   💾 Storage conscious: 10 FPS (minimum for good quality)")

    print(f"\n💡 YOUR LED-OPTIMIZED BENEFITS:")
    print(f"   ✅ 17.6x fewer pixels than 320x240")
    print(f"   ✅ Even 20 FPS is manageable with this optimization")
    print(f"   ✅ Can afford higher frame rates for better quality")

    print(f"\n🔧 CONFIGURATION OPTIONS:")
    print(f"   FRAME_EXTRACT_INTERVAL=0.1   # 10 FPS (current)")
    print(f"   FRAME_EXTRACT_INTERVAL=0.067 # 15 FPS (recommended)")
    print(f"   FRAME_EXTRACT_INTERVAL=0.05  # 20 FPS (hyperion default)")

if __name__ == "__main__":
    main()
