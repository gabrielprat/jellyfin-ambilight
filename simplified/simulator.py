import struct
import time
import sys
import numpy as np

def read_header(f):
    magic = f.read(4)
    if magic != b"AMBI":
        raise ValueError("Invalid file format")

    fps = struct.unpack("<H", f.read(2))[0]
    led_count = struct.unpack("<H", f.read(2))[0]
    fmt = struct.unpack("<B", f.read(1))[0]
    offset = struct.unpack("<H", f.read(2))[0]
    rgbw = (fmt == 1)

    return fps, led_count, rgbw, offset

def rgb_to_ansi(r, g, b):
    """Return ANSI escape code for RGB color"""
    return f"\033[48;2;{r};{g};{b}m \033[0m"

def draw_frame(border_pixels, w, h):
    """Draw an ASCII simulation of the screen border"""
    # Segment lengths
    right_len = h
    bottom_len = w - 1
    left_len = h - 1
    top_len = w - 2

    # Decode border in the same order the extractor writes: right → bottom → left → top
    idx = 0
    right = border_pixels[idx : idx + right_len]; idx += right_len
    bottom = border_pixels[idx : idx + bottom_len][::-1]; idx += bottom_len
    left = border_pixels[idx : idx + left_len][::-1]; idx += left_len
    top = border_pixels[idx : idx + top_len]; idx += top_len

    # Print top row (y=0)
    print("".join(rgb_to_ansi(r,g,b) for r,g,b in top))

    # Print sides
    for i in range(h - 2):
        left_color = rgb_to_ansi(*left[i])
        right_color = rgb_to_ansi(*right[i])
        print(f"{left_color}{' ' * (w-2)}{right_color}")

    # Print bottom row (y=h-1)
    print("".join(rgb_to_ansi(r,g,b) for r,g,b in bottom))


def play_ambilight(filename, w, h, loop=False):
    with open(filename, "rb") as f:
        fps, led_count, rgbw, offset = read_header(f)
        bytes_per_led = 4 if rgbw else 3
        print(f"🎬 Loaded {filename}")
        print(f"FPS: {fps}, LEDs: {led_count}, RGBW: {rgbw}, Offset: {offset}")
        print()

        # Frame read loop
        while True:
            header = f.read(10)  # timestamp (8 bytes) + payload_len (2 bytes)
            if not header:
                break
            timestamp, payload_len = struct.unpack("<dH", header)
            payload = f.read(payload_len)

            if rgbw:
                pixels = np.frombuffer(payload, np.uint8).reshape(-1, 4)[:, :3]
            else:
                pixels = np.frombuffer(payload, np.uint8).reshape(-1, 3)

            # Clear screen and print
            print("\033[H\033[J", end="")  # clear terminal
            draw_frame(pixels, w, h)
            sys.stdout.flush()

            time.sleep(1 / fps)
    if loop:
        play_ambilight(filename, w, h, loop=True)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Terminal Ambilight Player")
    parser.add_argument("file", help="Path to ambilight.bin file")
    parser.add_argument("--width", type=int, default=89)
    parser.add_argument("--height", type=int, default=49)
    args = parser.parse_args()

    try:
        play_ambilight(args.file, args.width, args.height)
    except KeyboardInterrupt:
        print("\nExiting...")
