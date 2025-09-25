import os
import cv2
import numpy as np
import requests
import time
import argparse
import socket
from database import (
    init_database, get_frames_for_item, get_item_by_id
)

# LED Configuration from environment variables
TOP_LED_COUNT = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", "89"))
BOTTOM_LED_COUNT = int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", "89"))
LEFT_LED_COUNT = int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", "49"))
RIGHT_LED_COUNT = int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", "49"))
INPUT_POSITION = int(os.getenv("AMBILIGHT_INPUT_POSITION", "46"))

# WLED Configuration
WLED_HOST = os.getenv("WLED_HOST", "wled-ambilight-lgc1.lan")
WLED_PORT = int(os.getenv("WLED_PORT", "80"))
WLED_UDP_PORT = int(os.getenv("WLED_UDP_PORT", "21324"))
WLED_USE_UDP = os.getenv("WLED_USE_UDP", "true").lower() == "true"
WLED_TIMEOUT = int(os.getenv("WLED_TIMEOUT", "5"))

class LEDMapper:
    """Maps screen regions to LED positions following Hyperion.ng convention"""

    def __init__(self):
        self.total_leds = TOP_LED_COUNT + RIGHT_LED_COUNT + BOTTOM_LED_COUNT + LEFT_LED_COUNT
        self.led_positions = self._calculate_led_positions()

        print(f"🔧 LED Configuration:")
        print(f"   Top: {TOP_LED_COUNT}, Right: {RIGHT_LED_COUNT}")
        print(f"   Bottom: {BOTTOM_LED_COUNT}, Left: {LEFT_LED_COUNT}")
        print(f"   Total LEDs: {self.total_leds}")
        print(f"   Input Position: {INPUT_POSITION}")

    def _calculate_led_positions(self):
        """Calculate normalized positions for each LED around the screen perimeter"""
        positions = []

        # Start from input position and go clockwise
        # Hyperion.ng convention: Top -> Right -> Bottom -> Left

        # Top edge (left to right)
        for i in range(TOP_LED_COUNT):
            x = i / (TOP_LED_COUNT - 1) if TOP_LED_COUNT > 1 else 0.5
            positions.append({'edge': 'top', 'x': x, 'y': 0.0, 'region': 'top'})

        # Right edge (top to bottom)
        for i in range(RIGHT_LED_COUNT):
            y = i / (RIGHT_LED_COUNT - 1) if RIGHT_LED_COUNT > 1 else 0.5
            positions.append({'edge': 'right', 'x': 1.0, 'y': y, 'region': 'right'})

        # Bottom edge (right to left)
        for i in range(BOTTOM_LED_COUNT):
            x = 1.0 - (i / (BOTTOM_LED_COUNT - 1)) if BOTTOM_LED_COUNT > 1 else 0.5
            positions.append({'edge': 'bottom', 'x': x, 'y': 1.0, 'region': 'bottom'})

        # Left edge (bottom to top)
        for i in range(LEFT_LED_COUNT):
            y = 1.0 - (i / (LEFT_LED_COUNT - 1)) if LEFT_LED_COUNT > 1 else 0.5
            positions.append({'edge': 'left', 'x': 0.0, 'y': y, 'region': 'left'})

        # Adjust for input position offset
        if INPUT_POSITION > 0:
            positions = positions[INPUT_POSITION:] + positions[:INPUT_POSITION]

        return positions

    def get_led_colors_from_frame(self, frame_path, border_size=0.1):
        """Extract colors for each LED from a frame"""
        try:
            # Load frame
            img = cv2.imread(frame_path)
            if img is None:
                print(f"⚠️  Could not load frame: {frame_path}")
                return None

            # Convert BGR to RGB
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            height, width = img.shape[:2]

            led_colors = []

            for i, pos in enumerate(self.led_positions):
                color = self._extract_color_for_led(img, pos, border_size)
                led_colors.append(color)

            return led_colors

        except Exception as e:
            print(f"⚠️  Error extracting LED colors: {e}")
            return None

    def _extract_color_for_led(self, img, led_pos, border_size):
        """Extract average color for a single LED position"""
        height, width = img.shape[:2]

        # Define sampling region based on LED position
        if led_pos['edge'] == 'top':
            # Sample from top border
            x_center = int(led_pos['x'] * width)
            region_size = max(10, width // TOP_LED_COUNT)
            x1 = max(0, x_center - region_size // 2)
            x2 = min(width, x_center + region_size // 2)
            y1 = 0
            y2 = max(1, int(height * border_size))

        elif led_pos['edge'] == 'bottom':
            # Sample from bottom border
            x_center = int(led_pos['x'] * width)
            region_size = max(10, width // BOTTOM_LED_COUNT)
            x1 = max(0, x_center - region_size // 2)
            x2 = min(width, x_center + region_size // 2)
            y1 = min(height - 1, int(height * (1 - border_size)))
            y2 = height

        elif led_pos['edge'] == 'left':
            # Sample from left border
            y_center = int(led_pos['y'] * height)
            region_size = max(10, height // LEFT_LED_COUNT)
            y1 = max(0, y_center - region_size // 2)
            y2 = min(height, y_center + region_size // 2)
            x1 = 0
            x2 = max(1, int(width * border_size))

        elif led_pos['edge'] == 'right':
            # Sample from right border
            y_center = int(led_pos['y'] * height)
            region_size = max(10, height // RIGHT_LED_COUNT)
            y1 = max(0, y_center - region_size // 2)
            y2 = min(height, y_center + region_size // 2)
            x1 = min(width - 1, int(width * (1 - border_size)))
            x2 = width

        # Extract region and calculate average color
        region = img[y1:y2, x1:x2]
        if region.size > 0:
            avg_color = np.mean(region, axis=(0, 1))
            return [int(avg_color[0]), int(avg_color[1]), int(avg_color[2])]  # RGB
        else:
            return [0, 0, 0]  # Fallback to black

class WLEDController:
    """Controls WLED device via UDP or HTTP API"""

    def __init__(self):
        self.base_url = f"http://{WLED_HOST}:{WLED_PORT}"
        self.session = requests.Session()
        self.session.timeout = WLED_TIMEOUT
        self.udp_socket = None

        # Initialize UDP socket if enabled
        if WLED_USE_UDP:
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                print(f"✅ UDP socket ready for {WLED_HOST}:{WLED_UDP_PORT}")
            except Exception as e:
                print(f"⚠️  UDP socket creation failed: {e}")
                print("   Falling back to JSON API")

        # Test connection
        if self.test_connection():
            protocol = "UDP" if WLED_USE_UDP and self.udp_socket else "JSON API"
            print(f"✅ Connected to WLED at {self.base_url} ({protocol})")
        else:
            print(f"⚠️  Could not connect to WLED at {self.base_url}")

    def test_connection(self):
        """Test connection to WLED device"""
        try:
            response = self.session.get(f"{self.base_url}/json/info")
            return response.status_code == 200
        except Exception:
            return False

    def set_led_colors_udp(self, colors):
        """Send LED colors via UDP (faster)"""
        try:
            if not self.udp_socket:
                return False

            # DRGB protocol: [DRGB][timeout][rgb_data...]
            packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])  # 1 second timeout

            for color in colors:
                if len(color) >= 3:
                    packet.extend([int(color[0]), int(color[1]), int(color[2])])
                else:
                    packet.extend([0, 0, 0])

            self.udp_socket.sendto(packet, (WLED_HOST, WLED_UDP_PORT))
            return True

        except Exception as e:
            print(f"⚠️  UDP Error: {e}")
            return False

    def set_led_colors_json(self, colors):
        """Send LED colors via JSON API (slower but reliable)"""
        try:
            # Prepare WLED JSON payload
            led_data = []
            for i, color in enumerate(colors):
                # WLED expects RGB values
                led_data.extend(color)  # [R, G, B, R, G, B, ...]

            payload = {
                "on": True,
                "seg": [{
                    "id": 0,
                    "i": led_data
                }]
            }

            response = self.session.post(
                f"{self.base_url}/json/state",
                json=payload,
                timeout=WLED_TIMEOUT
            )

            return response.status_code == 200

        except Exception as e:
            print(f"⚠️  JSON API Error: {e}")
            return False

    def set_led_colors(self, colors):
        """Send LED colors to WLED device (UDP or JSON based on config)"""
        if WLED_USE_UDP and self.udp_socket:
            return self.set_led_colors_udp(colors)
        else:
            return self.set_led_colors_json(colors)

    def turn_off(self):
        """Turn off WLED"""
        try:
            payload = {"on": False}
            response = self.session.post(f"{self.base_url}/json/state", json=payload)
            return response.status_code == 200
        except Exception:
            return False

def get_frame_at_timestamp(item_id, timestamp_seconds):
    """Get the frame closest to the given timestamp"""
    frames = get_frames_for_item(item_id)
    if not frames:
        return None

    # Find closest frame by timestamp
    closest_frame = min(frames, key=lambda f: abs(f['timestamp_seconds'] - timestamp_seconds))

    return closest_frame

def get_led_colors_at_timestamp(item_id, timestamp_seconds):
    """Get precomputed LED colors for the closest timestamp (FAST!)"""
    frame = get_frame_at_timestamp(item_id, timestamp_seconds)

    if frame and frame.get('led_colors'):
        return frame['led_colors']

    # Fallback: if no precomputed colors, extract from frame file
    if frame and frame.get('frame_path') and os.path.exists(frame['frame_path']):
        print(f"⚠️  No precomputed colors found, extracting from frame (slower)")
        led_mapper = LEDMapper()
        return led_mapper.get_led_colors_from_frame(frame['frame_path'])

    return None

def simulate_playback(item_id, duration=30):
    """Simulate playback for testing - cycles through frames"""
    print(f"🎬 Simulating playback for item: {item_id}")

    # Get item info
    item = get_item_by_id(item_id)
    if not item:
        print(f"❌ Item not found: {item_id}")
        return

    print(f"📽️  Item: {item['name']}")

    # Get available frames
    frames = get_frames_for_item(item_id)
    if not frames:
        print(f"❌ No frames found for item. Run frame extraction first.")
        return

    print(f"📸 Found {len(frames)} frames")

    # Initialize components
    led_mapper = LEDMapper()
    wled = WLEDController()

    start_time = time.time()
    frame_index = 0

    print(f"🚀 Starting {duration}s simulation...")

    while time.time() - start_time < duration and frame_index < len(frames):
        frame = frames[frame_index]

        # Use precomputed LED colors (FAST!) or fallback to extraction
        led_colors = frame.get('led_colors')
        if not led_colors:
            # Fallback to frame extraction if no precomputed colors
            led_colors = led_mapper.get_led_colors_from_frame(frame['frame_path'])

        if led_colors:
            # Send to WLED
            success = wled.set_led_colors(led_colors)

            elapsed = time.time() - start_time
            precomputed = "🚀" if frame.get('led_colors') else "🐌"
            print(f"⏱️  {elapsed:.1f}s - Frame {frame_index + 1}/{len(frames)} "
                  f"(timestamp: {frame['timestamp_seconds']:.1f}s) "
                  f"{precomputed} {'✅' if success else '❌'}")

        frame_index += 1
        time.sleep(0.1)  # 10 FPS simulation

    # Turn off LEDs when done
    wled.turn_off()
    print("🏁 Simulation complete - LEDs turned off")

def set_ambilight_for_timestamp(item_id, timestamp_seconds):
    """Set ambilight colors for a specific timestamp (REAL-TIME OPTIMIZED)"""
    # Get precomputed LED colors - this is VERY fast!
    led_colors = get_led_colors_at_timestamp(item_id, timestamp_seconds)

    if led_colors:
        wled = WLEDController()
        success = wled.set_led_colors(led_colors)
        return success

    return False

def test_single_frame(frame_path):
    """Test ambilight with a single frame"""
    print(f"🧪 Testing single frame: {frame_path}")

    if not os.path.exists(frame_path):
        print(f"❌ Frame not found: {frame_path}")
        return

    # Initialize components
    led_mapper = LEDMapper()
    wled = WLEDController()

    # Extract colors
    led_colors = led_mapper.get_led_colors_from_frame(frame_path)

    if led_colors:
        print(f"🎨 Extracted {len(led_colors)} LED colors")

        # Show some sample colors
        print("Sample colors:")
        for i in range(0, min(10, len(led_colors))):
            color = led_colors[i]
            print(f"  LED {i}: RGB({color[0]}, {color[1]}, {color[2]})")

        # Send to WLED
        success = wled.set_led_colors(led_colors)
        print(f"🚀 Sent to WLED: {'✅ Success' if success else '❌ Failed'}")

        # Keep lit for 5 seconds
        print("💡 LEDs will stay lit for 5 seconds...")
        time.sleep(5)

        # Turn off
        wled.turn_off()
        print("🔌 LEDs turned off")
    else:
        print("❌ Failed to extract LED colors")

def benchmark_performance(item_id, test_frames=10):
    """Benchmark precomputed vs real-time color extraction"""
    print(f"🏁 Benchmarking performance for item: {item_id}")

    # Get frames
    frames = get_frames_for_item(item_id)
    if not frames:
        print("❌ No frames found for benchmarking")
        return

    test_frames = min(test_frames, len(frames))
    test_set = frames[:test_frames]

    print(f"📊 Testing with {test_frames} frames")

    # Benchmark precomputed colors
    print("\n🚀 Testing precomputed colors (FAST):")
    start_time = time.time()
    precomputed_success = 0

    for frame in test_set:
        if frame.get('led_colors'):
            precomputed_success += 1

    precomputed_time = time.time() - start_time

    # Benchmark real-time extraction
    print("\n🐌 Testing real-time extraction (SLOW):")
    start_time = time.time()
    extraction_success = 0
    led_mapper = LEDMapper()

    for frame in test_set:
        if os.path.exists(frame['frame_path']):
            colors = led_mapper.get_led_colors_from_frame(frame['frame_path'])
            if colors:
                extraction_success += 1

    extraction_time = time.time() - start_time

    # Results
    print(f"\n📈 Performance Results:")
    print(f"   Precomputed: {precomputed_success}/{test_frames} frames in {precomputed_time:.4f}s")
    print(f"   Real-time:   {extraction_success}/{test_frames} frames in {extraction_time:.4f}s")

    if precomputed_time > 0:
        speedup = extraction_time / precomputed_time
        print(f"   🚀 Speedup: {speedup:.1f}x faster with precomputed colors!")

    coverage = (precomputed_success / test_frames) * 100
    print(f"   📊 Precomputed coverage: {coverage:.1f}%")

    if coverage < 100:
        print(f"   💡 Tip: Run frame extraction with newer version to precompute colors")

def main():
    parser = argparse.ArgumentParser(description='Jellyfin Ambilight Service')
    parser.add_argument('--simulate', type=str,
                        help='Simulate playback for item ID')
    parser.add_argument('--duration', type=int, default=30,
                        help='Simulation duration in seconds (default: 30)')
    parser.add_argument('--test-frame', type=str,
                        help='Test with a single frame file')
    parser.add_argument('--show-config', action='store_true',
                        help='Show LED configuration')
    parser.add_argument('--benchmark', type=str,
                        help='Benchmark performance with item ID')

    args = parser.parse_args()

    print("🌈 Jellyfin Ambilight Service")

    # Initialize database
    init_database()

    if args.show_config:
        led_mapper = LEDMapper()
        print(f"\n📐 LED Mapping Details:")
        for i, pos in enumerate(led_mapper.led_positions[:10]):  # Show first 10
            print(f"  LED {i}: {pos['edge']} edge at ({pos['x']:.2f}, {pos['y']:.2f})")
        if len(led_mapper.led_positions) > 10:
            print(f"  ... and {len(led_mapper.led_positions) - 10} more")

    elif args.test_frame:
        test_single_frame(args.test_frame)

    elif args.simulate:
        simulate_playback(args.simulate, args.duration)

    elif args.benchmark:
        benchmark_performance(args.benchmark)

    else:
        print("ℹ️  No action specified. Use --help for options.")
        print("   Common usage:")
        print("   --show-config              : Show LED configuration")
        print("   --test-frame <path>        : Test with single frame")
        print("   --simulate <item_id>       : Simulate playback")
        print("   --benchmark <item_id>      : Performance benchmark")

if __name__ == "__main__":
    main()
