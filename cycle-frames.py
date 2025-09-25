#!/usr/bin/env python3
"""
Simple Frame Cycler
===================

Quickly cycle through frames using the existing visualizer scripts.
Press Enter to advance to next frame, 'q' to quit.
"""

import os
import sys
import subprocess
from pathlib import Path

def cycle_frames_interactive(file_path: str, start_frame: int = 0, step: int = 1):
    """Interactively cycle through frames"""

    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🎬 Interactive Frame Cycler: {Path(file_path).name}")
    print("=" * 60)
    print("Controls:")
    print("  Enter     - Next frame")
    print("  'n' + Enter - Next frame")
    print("  'p' + Enter - Previous frame")
    print("  'j' + Enter - Jump to frame number")
    print("  's' + Enter - Change step size")
    print("  'q' + Enter - Quit")
    print("=" * 60)

    current_frame = start_frame
    current_step = step

    while True:
        try:
            # Clear screen and show current frame
            os.system('cls' if os.name == 'nt' else 'clear')

            print(f"🎬 Frame {current_frame} (step: {current_step})")
            print("=" * 60)

            # Use the simple visualizer to show the frame
            result = subprocess.run([
                'python3', 'simple-udp-visualizer.py',
                file_path, str(current_frame)
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print(result.stdout)
            else:
                print(f"❌ Error showing frame {current_frame}")
                print(result.stderr)

            print("=" * 60)
            print(f"Frame {current_frame} | Step {current_step} | [Enter=next, p=prev, j=jump, s=step, q=quit]")

            # Get user input
            user_input = input("> ").strip().lower()

            if user_input in ['q', 'quit', 'exit']:
                break
            elif user_input in ['', 'n', 'next']:
                current_frame += current_step
            elif user_input in ['p', 'prev', 'previous']:
                current_frame = max(0, current_frame - current_step)
            elif user_input.startswith('j'):
                try:
                    # Parse jump command: 'j 100' or just 'j' then ask
                    parts = user_input.split()
                    if len(parts) > 1:
                        target_frame = int(parts[1])
                    else:
                        target_frame = int(input("Jump to frame: "))
                    current_frame = max(0, target_frame)
                except ValueError:
                    print("❌ Invalid frame number")
                    input("Press Enter to continue...")
            elif user_input.startswith('s'):
                try:
                    # Parse step command: 's 5' or just 's' then ask
                    parts = user_input.split()
                    if len(parts) > 1:
                        new_step = int(parts[1])
                    else:
                        new_step = int(input("New step size: "))
                    current_step = max(1, new_step)
                except ValueError:
                    print("❌ Invalid step size")
                    input("Press Enter to continue...")

            # Ensure frame is not negative
            current_frame = max(0, current_frame)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            input("Press Enter to continue...")

    print(f"\n👋 Exited at frame {current_frame}")

def auto_cycle_frames(file_path: str, delay: float = 1.0, start_frame: int = 0, max_frames: int = None):
    """Automatically cycle through frames with a delay"""

    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🎬 Auto Frame Cycler: {Path(file_path).name}")
    print(f"⚙️  Delay: {delay}s per frame, starting at frame {start_frame}")
    print("🎮 Press Ctrl+C to stop")
    print("=" * 60)

    current_frame = start_frame
    displayed_frames = 0

    try:
        while True:
            # Clear screen and show current frame
            os.system('cls' if os.name == 'nt' else 'clear')

            print(f"🎬 Auto Cycling - Frame {current_frame}")
            print("=" * 60)

            # Use the simple visualizer
            result = subprocess.run([
                'python3', 'simple-udp-visualizer.py',
                file_path, str(current_frame)
            ], capture_output=True, text=True)

            if result.returncode == 0:
                print(result.stdout)
            else:
                print(f"❌ Frame {current_frame} not found, stopping")
                break

            print("=" * 60)
            print(f"Auto cycling... (Ctrl+C to stop)")

            # Wait for delay
            import time
            time.sleep(delay)

            current_frame += 1
            displayed_frames += 1

            # Check max frames limit
            if max_frames and displayed_frames >= max_frames:
                break

    except KeyboardInterrupt:
        print(f"\n⏹️  Stopped at frame {current_frame}")

    print(f"✅ Displayed {displayed_frames} frames")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Simple Frame Cycler")
        print("==================")
        print()
        print("Usage:")
        print("  python3 cycle-frames.py <udp_file> [mode] [options]")
        print()
        print("Modes:")
        print("  interactive (default)    - Press Enter to advance frames")
        print("  auto [delay]            - Auto-advance with delay (default 1.0s)")
        print()
        print("Options for interactive mode:")
        print("  [start_frame] [step]    - Starting frame and step size")
        print()
        print("Examples:")
        print("  python3 cycle-frames.py data.udpdata")
        print("  python3 cycle-frames.py data.udpdata interactive 50 5")
        print("  python3 cycle-frames.py data.udpdata auto 0.5")
        return

    file_path = sys.argv[1]
    mode = "interactive"

    if len(sys.argv) > 2:
        mode = sys.argv[2]

    if mode == "interactive":
        start_frame = 0
        step = 1

        if len(sys.argv) > 3:
            try:
                start_frame = int(sys.argv[3])
            except ValueError:
                print(f"❌ Invalid start frame: {sys.argv[3]}")
                return

        if len(sys.argv) > 4:
            try:
                step = int(sys.argv[4])
            except ValueError:
                print(f"❌ Invalid step: {sys.argv[4]}")
                return

        cycle_frames_interactive(file_path, start_frame, step)

    elif mode == "auto":
        delay = 1.0

        if len(sys.argv) > 3:
            try:
                delay = float(sys.argv[3])
            except ValueError:
                print(f"❌ Invalid delay: {sys.argv[3]}")
                return

        auto_cycle_frames(file_path, delay)

    else:
        print(f"❌ Unknown mode: {mode}")
        print("Use 'interactive' or 'auto'")

if __name__ == "__main__":
    main()
