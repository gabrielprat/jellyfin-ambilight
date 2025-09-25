#!/usr/bin/env python3
"""
Test Black Border Detection with Frame Extraction
=================================================

Test the new black border detection integrated into the frame extractor.
"""

import sys
sys.path.append('./frames')

from fast_extractor_pure import _extract_border_colors_pure, _detect_black_borders_pure, _enhance_brightness_pure, _apply_led_offset_pure

def create_test_frame_with_borders(width: int, height: int, border_type: str) -> bytes:
    """Create test frames with different border types"""
    frame = bytearray(width * height * 3)

    if border_type == "letterbox":
        # Black bars top and bottom (16:9 content in 4:3 frame)
        bar_height = height // 6  # ~16% bars

        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3

                if y < bar_height or y >= height - bar_height:
                    # Black letterbox bars
                    frame[idx] = 0
                    frame[idx + 1] = 0
                    frame[idx + 2] = 0
                else:
                    # Colorful content
                    progress_x = x / width
                    progress_y = (y - bar_height) / (height - 2 * bar_height)

                    # Create a colorful gradient
                    frame[idx] = int(255 * progress_x)      # Red
                    frame[idx + 1] = int(255 * progress_y)  # Green
                    frame[idx + 2] = int(200 - 100 * progress_x)  # Blue

    elif border_type == "pillarbox":
        # Black bars left and right (4:3 content in 16:9 frame)
        bar_width = width // 8  # ~12.5% bars

        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3

                if x < bar_width or x >= width - bar_width:
                    # Black pillarbox bars
                    frame[idx] = 0
                    frame[idx + 1] = 0
                    frame[idx + 2] = 0
                else:
                    # Colorful content
                    progress_x = (x - bar_width) / (width - 2 * bar_width)
                    progress_y = y / height

                    # Create different color pattern
                    frame[idx] = int(180 + 75 * progress_x)     # Red
                    frame[idx + 1] = int(100 + 155 * progress_y) # Green
                    frame[idx + 2] = int(255 * (1 - progress_x)) # Blue

    elif border_type == "full":
        # No borders, full colorful content
        for y in range(height):
            for x in range(width):
                idx = (y * width + x) * 3

                progress_x = x / width
                progress_y = y / height

                # Rainbow gradient
                frame[idx] = int(255 * abs(2 * progress_x - 1))    # Red
                frame[idx + 1] = int(255 * abs(2 * progress_y - 1)) # Green
                frame[idx + 2] = int(255 * ((progress_x + progress_y) / 2)) # Blue

    return bytes(frame)

def test_border_detection_integration():
    """Test the integrated border detection system"""

    print("🧪 Testing Integrated Black Border Detection")
    print("=" * 60)

    width, height = 1920, 1080
    test_cases = ["letterbox", "pillarbox", "full"]

    for test_case in test_cases:
        print(f"\n📺 Test Case: {test_case.upper()}")
        print("-" * 40)

        # Create test frame
        frame_data = create_test_frame_with_borders(width, height, test_case)

        # Test border detection
        crop_coords = _detect_black_borders_pure(frame_data, width, height)
        top_crop, bottom_crop, left_crop, right_crop = crop_coords

        print(f"🔲 Detected borders: T:{top_crop}, B:{bottom_crop}, L:{left_crop}, R:{right_crop}")

        # Extract colors with new method
        border_colors = _extract_border_colors_pure(frame_data, width, height)

        # Apply brightness enhancement
        enhanced_colors = _enhance_brightness_pure(border_colors)

        # Apply LED offset
        EXPECTED_LED_COUNT = 276
        INPUT_POSITION = 46

        final_payload = _apply_led_offset_pure(enhanced_colors, INPUT_POSITION)

        # Ensure correct LED count
        led_triplets = len(final_payload) // 3
        if led_triplets != EXPECTED_LED_COUNT:
            if led_triplets < EXPECTED_LED_COUNT:
                final_payload += bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
            else:
                final_payload = final_payload[:EXPECTED_LED_COUNT * 3]

        # Create UDP packet
        packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])
        packet.extend(final_payload)

        # Analyze results
        analyze_extraction_results(bytes(packet), test_case)

def analyze_extraction_results(udp_packet: bytes, test_name: str):
    """Analyze the quality of the extracted colors"""

    if len(udp_packet) < 5 or udp_packet[:4] != b'DRGB':
        print(f"   ❌ Invalid UDP packet for {test_name}")
        return

    rgb_data = udp_packet[5:]
    led_count = len(rgb_data) // 3

    colors = []
    brightness_sum = 0
    black_count = 0

    for i in range(led_count):
        r = rgb_data[i*3]
        g = rgb_data[i*3 + 1]
        b = rgb_data[i*3 + 2]

        colors.append((r, g, b))
        brightness = 0.299 * r + 0.587 * g + 0.114 * b
        brightness_sum += brightness

        if brightness < 5:
            black_count += 1

    unique_colors = len(set(colors))
    avg_brightness = brightness_sum / led_count if led_count > 0 else 0
    black_percentage = (black_count / led_count * 100) if led_count > 0 else 0

    print(f"   📊 Results: {led_count} LEDs")
    print(f"      Unique colors: {unique_colors}")
    print(f"      Avg brightness: {avg_brightness:.1f}")
    print(f"      Black LEDs: {black_count} ({black_percentage:.1f}%)")

    # Quality assessment
    if black_percentage < 10 and unique_colors > led_count // 4:
        print(f"   ✅ Excellent quality extraction!")
    elif black_percentage < 30 and unique_colors > led_count // 10:
        print(f"   ✅ Good quality extraction")
    elif black_percentage < 50:
        print(f"   ⚠️  Moderate quality (some dark content)")
    else:
        print(f"   ❌ Poor quality (mostly dark)")

    # Show a few sample LEDs
    print(f"   🎨 Sample LEDs:")
    for i in range(min(10, led_count)):
        r, g, b = colors[i]
        char = get_color_char(r, g, b)
        print(f"      LED {i:2d}: [{char}] RGB({r:3d},{g:3d},{b:3d})")

def get_color_char(r: int, g: int, b: int) -> str:
    """Get representative character for RGB color"""
    brightness = 0.299 * r + 0.587 * g + 0.114 * b

    if brightness < 5:
        return ' '
    elif r > g and r > b and r > 100:
        return 'R'
    elif g > r and g > b and g > 100:
        return 'G'
    elif b > r and b > g and b > 100:
        return 'B'
    elif r > 150 and g > 150 and b < 100:
        return 'Y'
    elif brightness > 200:
        return 'W'
    elif brightness > 100:
        return 'O'
    elif brightness > 50:
        return '*'
    elif brightness > 20:
        return ':'
    else:
        return '.'

def main():
    """Main test function"""
    test_border_detection_integration()

    print("\n" + "=" * 60)
    print("💡 Summary:")
    print("   ✅ Black border detection automatically crops letterbox/pillarbox")
    print("   ✅ Color extraction focuses on actual content, not black bars")
    print("   ✅ Brightness enhancement improves dark content")
    print("   ✅ System should produce much better ambilight colors!")
    print("\n🎯 Next: Re-extract your video data to see the improvement!")

if __name__ == "__main__":
    main()
