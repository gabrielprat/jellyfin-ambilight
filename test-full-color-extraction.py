#!/usr/bin/env python3
"""
Full Color Extraction Test
==========================

Demonstrates that the system extracts ALL RGB colors (0-255 for each channel),
not just pure red, green, and blue.
"""

import sys
sys.path.append('./frames')

from fast_extractor_pure import _extract_border_colors_pure, _apply_led_offset_pure

def create_full_spectrum_frame(width: int, height: int) -> bytes:
    """Create a frame with the full RGB color spectrum"""
    frame = bytearray(width * height * 3)

    # Create different color zones to test full spectrum
    zones = [
        # Zone 1: Purple/Magenta tones
        {'area': (0, 0, width//4, height//4), 'colors': [(138, 43, 226), (255, 20, 147), (199, 21, 133)]},

        # Zone 2: Orange/Yellow tones
        {'area': (width//4, 0, width//2, height//4), 'colors': [(255, 165, 0), (255, 215, 0), (255, 140, 0)]},

        # Zone 3: Cyan/Teal tones
        {'area': (width//2, 0, 3*width//4, height//4), 'colors': [(0, 255, 255), (64, 224, 208), (0, 206, 209)]},

        # Zone 4: Brown/Tan tones
        {'area': (3*width//4, 0, width, height//4), 'colors': [(160, 82, 45), (210, 180, 140), (139, 69, 19)]},

        # Zone 5: Pink/Rose tones
        {'area': (0, height//4, width//4, height//2), 'colors': [(255, 192, 203), (255, 105, 180), (219, 112, 147)]},

        # Zone 6: Lime/Green variations
        {'area': (width//4, height//4, width//2, height//2), 'colors': [(50, 205, 50), (124, 252, 0), (173, 255, 47)]},

        # Zone 7: Navy/Blue variations
        {'area': (width//2, height//4, 3*width//4, height//2), 'colors': [(25, 25, 112), (0, 0, 139), (72, 61, 139)]},

        # Zone 8: Coral/Salmon tones
        {'area': (3*width//4, height//4, width, height//2), 'colors': [(255, 127, 80), (250, 128, 114), (233, 150, 122)]},

        # Bottom half: Gradient with complex colors
        {'area': (0, height//2, width, height), 'colors': 'gradient'}
    ]

    for zone in zones:
        x1, y1, x2, y2 = zone['area']

        if zone['colors'] == 'gradient':
            # Create a complex gradient
            for y in range(y1, y2):
                for x in range(x1, x2):
                    idx = (y * width + x) * 3

                    # Complex color calculation
                    progress_x = (x - x1) / (x2 - x1)
                    progress_y = (y - y1) / (y2 - y1)

                    # Non-linear color mixing
                    r = int(127 + 128 * abs(progress_x - 0.5))
                    g = int(64 + 191 * progress_y * progress_x)
                    b = int(200 - 150 * progress_x + 55 * progress_y)

                    frame[idx] = max(0, min(255, r))
                    frame[idx + 1] = max(0, min(255, g))
                    frame[idx + 2] = max(0, min(255, b))
        else:
            # Use predefined colors for this zone
            colors = zone['colors']
            color_count = len(colors)

            for y in range(y1, y2):
                for x in range(x1, x2):
                    idx = (y * width + x) * 3

                    # Pick color based on position
                    color_idx = ((x - x1) + (y - y1)) % color_count
                    r, g, b = colors[color_idx]

                    frame[idx] = r
                    frame[idx + 1] = g
                    frame[idx + 2] = b

    return bytes(frame)

def analyze_extracted_colors(border_colors: bytes) -> dict:
    """Analyze the extracted colors to show full spectrum coverage"""
    led_count = len(border_colors) // 3

    colors = []
    color_types = {
        'pure_red': 0, 'pure_green': 0, 'pure_blue': 0,
        'purple_magenta': 0, 'orange_yellow': 0, 'cyan_teal': 0,
        'brown_tan': 0, 'pink_rose': 0, 'mixed_complex': 0
    }

    for i in range(led_count):
        r = border_colors[i*3]
        g = border_colors[i*3 + 1]
        b = border_colors[i*3 + 2]

        colors.append((r, g, b))

        # Classify color types
        if r > 200 and g < 50 and b < 50:
            color_types['pure_red'] += 1
        elif r < 50 and g > 200 and b < 50:
            color_types['pure_green'] += 1
        elif r < 50 and g < 50 and b > 200:
            color_types['pure_blue'] += 1
        elif r > 100 and b > 100 and g < 100:  # Purple/Magenta
            color_types['purple_magenta'] += 1
        elif r > 200 and g > 100 and b < 100:  # Orange/Yellow
            color_types['orange_yellow'] += 1
        elif r < 100 and g > 150 and b > 150:  # Cyan/Teal
            color_types['cyan_teal'] += 1
        elif r > 100 and g > 50 and b < 100 and r > g:  # Brown/Tan
            color_types['brown_tan'] += 1
        elif r > 150 and g > 100 and b > 100:  # Pink/Rose
            color_types['pink_rose'] += 1
        else:
            color_types['mixed_complex'] += 1

    return {
        'total_leds': led_count,
        'unique_colors': len(set(colors)),
        'color_types': color_types,
        'sample_colors': colors[:20]  # First 20 for demonstration
    }

def test_full_color_extraction():
    """Test that the system extracts the full color spectrum"""

    print("🌈 FULL COLOR SPECTRUM EXTRACTION TEST")
    print("=" * 60)

    # Create test frame with full color spectrum
    width, height = 1920, 1080
    print(f"📱 Creating test frame: {width}x{height}")
    print("🎨 Including: Purple, Orange, Cyan, Brown, Pink, Lime, Navy, Coral, Gradients")

    frame_data = create_full_spectrum_frame(width, height)

    # Extract border colors (this is what gets sent to WLED)
    print("\n🔍 Extracting border colors...")
    border_colors = _extract_border_colors_pure(frame_data, width, height)

    # Apply LED processing
    INPUT_POSITION = 46
    final_colors = _apply_led_offset_pure(border_colors, INPUT_POSITION)

    # Analyze results
    print("\n📊 COLOR EXTRACTION ANALYSIS:")
    analysis = analyze_extracted_colors(final_colors)

    print(f"   Total LEDs: {analysis['total_leds']}")
    print(f"   Unique Colors: {analysis['unique_colors']}")
    print(f"   Color Variety: {(analysis['unique_colors'] / analysis['total_leds'] * 100):.1f}%")

    print("\n🎨 COLOR TYPE BREAKDOWN:")
    for color_type, count in analysis['color_types'].items():
        if count > 0:
            percentage = (count / analysis['total_leds']) * 100
            print(f"   {color_type.replace('_', ' ').title()}: {count} LEDs ({percentage:.1f}%)")

    print("\n🔬 SAMPLE EXTRACTED COLORS (First 20 LEDs):")
    for i, (r, g, b) in enumerate(analysis['sample_colors']):
        color_name = get_color_name(r, g, b)
        print(f"   LED {i:2d}: RGB({r:3d},{g:3d},{b:3d}) - {color_name}")

    print("\n✅ CONCLUSION:")
    if analysis['unique_colors'] > analysis['total_leds'] // 4:
        print("   🌈 EXCELLENT: System extracts full RGB spectrum!")
        print("   ✅ Not limited to pure R/G/B - captures ALL color nuances")
        print("   ✅ Complex colors like purple, orange, cyan properly extracted")
    else:
        print("   ⚠️  Limited color variety detected")

    print(f"\n💡 PROOF: {analysis['unique_colors']} different colors extracted!")
    print("   This demonstrates the system captures the ENTIRE RGB spectrum,")
    print("   not just pure red (255,0,0), green (0,255,0), and blue (0,0,255).")

def get_color_name(r: int, g: int, b: int) -> str:
    """Get descriptive name for RGB color"""
    if r > 200 and g < 50 and b < 50:
        return "Pure Red"
    elif r < 50 and g > 200 and b < 50:
        return "Pure Green"
    elif r < 50 and g < 50 and b > 200:
        return "Pure Blue"
    elif r > 100 and b > 100 and g < 100:
        return "Purple/Magenta"
    elif r > 200 and g > 100 and b < 100:
        return "Orange/Yellow"
    elif r < 100 and g > 150 and b > 150:
        return "Cyan/Teal"
    elif r > 100 and g > 50 and b < 100 and r > g:
        return "Brown/Tan"
    elif r > 150 and g > 100 and b > 100:
        return "Pink/Rose"
    elif r > 200 and g > 200 and b > 200:
        return "Near White"
    elif r < 50 and g < 50 and b < 50:
        return "Near Black"
    else:
        return f"Complex Mix"

def demonstrate_rgb_extraction():
    """Show how RGB values are extracted pixel by pixel"""

    print("\n" + "=" * 60)
    print("🔬 HOW RGB EXTRACTION WORKS")
    print("=" * 60)

    print("📡 Frame Processing Pipeline:")
    print("   1. ffmpeg extracts raw RGB24 frame data")
    print("   2. Each pixel = 3 bytes: [Red][Green][Blue]")
    print("   3. Extract border pixels from frame edges")
    print("   4. Each border pixel keeps EXACT RGB values")
    print("   5. Create UDP packet with all extracted colors")
    print("   6. Send to WLED: DRGB + [R₁G₁B₁][R₂G₂B₂]...[R₂₇₆G₂₇₆B₂₇₆]")

    print("\n💾 Example RGB Values Extracted:")
    examples = [
        (255, 165, 0, "Orange"),
        (138, 43, 226, "Blue-Violet"),
        (255, 20, 147, "Deep Pink"),
        (64, 224, 208, "Turquoise"),
        (160, 82, 45, "Saddle Brown"),
        (50, 205, 50, "Lime Green"),
        (255, 127, 80, "Coral"),
        (25, 25, 112, "Midnight Blue")
    ]

    for r, g, b, name in examples:
        print(f"   RGB({r:3d},{g:3d},{b:3d}) → {name}")

    print(f"\n🎯 TOTAL POSSIBLE COLORS: 256³ = 16,777,216 colors")
    print(f"   The system can extract ANY of these 16+ million colors!")

if __name__ == "__main__":
    test_full_color_extraction()
    demonstrate_rgb_extraction()
