import subprocess
import threading
import time
import logging

logger = logging.getLogger(__name__)

class AmbilightBinaryPlayer:
    """
    Wrapper around the Rust ambilight-player binary.
    Provides play, stop, and pseudo-seek (resync) using subprocess restarts.
    """

    def __init__(self, binary_file: str, host: str, port: int):
        self.binary_file = binary_file
        self.host = host
        self.port = port
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def play(self, start_time: float = 0.0):
        """Start playing from the beginning or a given timestamp."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                logger.warning("Player is already running — stopping first for clean restart.")
                self.stop()

            # Capture a wall-clock reference for launch-delay compensation
            ref_epoch = time.time()
            cmd = [
                "/usr/local/bin/ambilight-player",
                "--file", str(self.binary_file),
                "--host", self.host,
                "--port", str(self.port),
                "--start", str(start_time),
                "--ref-epoch", str(ref_epoch),
            ]

            logger.info(f"🎬 Starting Rust player from {start_time:.2f}s: {' '.join(cmd)}")
            # Open with stdin pipe to support live SEEK commands
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def stop(self):
        """Stop playback gracefully."""
        with self._lock:
            if self._proc:
                logger.info("🛑 Stopping Rust player...")
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                    logger.info("✅ Player stopped cleanly.")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ Player did not stop in time — killing.")
                    self._proc.kill()
                self._proc = None
            else:
                logger.debug("Player is not running, nothing to stop.")

    def resync(self, position_seconds: float):
        """
        Simulate seek/resync by restarting the player from the new timestamp.
        Ideal when the video position changes (seek or resume).
        """
        logger.info(f"🔄 Resync requested to {position_seconds:.2f}s — sending SEEK to Rust player.")
        with self._lock:
            if self._proc and self._proc.poll() is None and self._proc.stdin:
                try:
                    cmd = f"SEEK {position_seconds}\n".encode("utf-8")
                    self._proc.stdin.write(cmd)
                    self._proc.stdin.flush()
                    logger.info("✅ SEEK command sent.")
                    return
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send SEEK: {e}; falling back to restart.")
            # Fallback: restart
            self.stop()
            time.sleep(0.2)
            self.play(start_time=position_seconds)
            logger.info(f"✅ Resync complete via restart from {position_seconds:.2f}s.")

    def pause(self):
        """Send PAUSE to Rust player."""
        logger.info("⏸️ Pause requested — sending to Rust player.")
        with self._lock:
            if self._proc and self._proc.poll() is None and self._proc.stdin:
                try:
                    self._proc.stdin.write(b"PAUSE\n")
                    self._proc.stdin.flush()
                    return
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send PAUSE: {e}")

    def resume(self):
        """Send RESUME to Rust player."""
        logger.info("▶️ Resume requested — sending to Rust player.")
        with self._lock:
            if self._proc and self._proc.poll() is None and self._proc.stdin:
                try:
                    self._proc.stdin.write(b"RESUME\n")
                    self._proc.stdin.flush()
                    return
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send RESUME: {e}")

    def beat(self, position_seconds: float, epoch_seconds: float | None = None):
        """
        Send a heartbeat to the Rust player with current video position and the
        wall-clock epoch when that position was measured. The Rust side will
        compensate transit/processing delay using the epoch.
        """
        if epoch_seconds is None:
            epoch_seconds = time.time()
        with self._lock:
            if self._proc and self._proc.poll() is None and self._proc.stdin:
                try:
                    cmd = f"BEAT {position_seconds} {epoch_seconds}\n".encode("utf-8")
                    self._proc.stdin.write(cmd)
                    self._proc.stdin.flush()
                except Exception:
                    # Heartbeats are best-effort; ignore failures
                    pass
