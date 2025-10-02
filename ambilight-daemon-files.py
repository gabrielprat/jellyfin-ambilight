#!/usr/bin/env python3
"""
File-Based Ambilight Daemon
===========================

Simple, efficient ambilight daemon using file-based storage:
- No database dependency
- Direct UDP packet files for ultra-fast access
- 12x faster item operations
- Simpler architecture and easier maintenance
"""

import os
import sys
import time
import threading
import socket
import signal
import logging
import requests
import socket
from urllib.parse import urlparse
import struct
from datetime import datetime
from typing import Dict
from pathlib import Path
from storage.storage import FileBasedStorage
# Use simplified extractor and wled_player components
from simplified.extractor import extract_frames
from simplified.wled_player import (
    get_wled_state,
    restore_wled_state as restore_wled_state_fn,
    create_broadcaster,
    pause_broadcast,
    resume_broadcast,
    sync_broadcast_to,
)

# Import local modules
sys.path.append('/app')
sys.path.append('/app/storage')
sys.path.append('/app/frames')

# Configuration
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))
WLED_UDP_PROTOCOL = os.getenv('WLED_UDP_PROTOCOL', 'UDP_RAW').upper()  # DRGB, WARLS, DNRGB or UDP_RAW
WLED_UDP_TIMEOUT = int(os.getenv('WLED_UDP_TIMEOUT', '255'))  # 1..255; 255 = persistent
WLED_LED_COUNT = int(os.getenv('WLED_LED_COUNT', '300'))  # Physical LEDs configured in WLED
WLED_UDP_RAW_PORT = int(os.getenv('WLED_UDP_RAW_PORT', '19446'))  # Hyperion UDP raw default port
SMOOTHING_ENABLED = os.getenv('SMOOTHING_ENABLED', 'true').lower() == 'true'
SMOOTHING_ALPHA = float(os.getenv('SMOOTHING_ALPHA', '0.25'))  # 0..1, lower = smoother
STREAM_FPS = float(os.getenv('FRAMES_PER_SECOND', '10'))  # Use extraction FPS for streaming cadence
TARGET_STREAM_FPS = float(os.getenv('TARGET_STREAM_FPS', '0'))  # 0=disabled; if >0, upsample with interpolation
COLOR_FILTER_ENABLED = os.getenv('COLOR_FILTER_ENABLED', 'false').lower() == 'true'
DARK_BRIGHTNESS_THRESHOLD = int(os.getenv('DARK_BRIGHTNESS_THRESHOLD', '18'))  # 0..255
SATURATION_BOOST = float(os.getenv('SATURATION_BOOST', '1.25'))  # 1.0=no change
AMBILIGHT_DNS_TTL_SECONDS = int(os.getenv('AMBILIGHT_DNS_TTL_SECONDS', '3600'))
AMBILIGHT_DISABLE_DNS_RESOLVE = os.getenv('AMBILIGHT_DISABLE_DNS_RESOLVE', 'false').lower() == 'true'
AMBILIGHT_DISABLE_PERIODIC_RESYNC = os.getenv('AMBILIGHT_DISABLE_PERIODIC_RESYNC', 'false').lower() == 'true'

# Network resilience (sync-first approach)
UDP_SKIP_ON_BUSY = os.getenv('UDP_SKIP_ON_BUSY', 'true').lower() == 'true'  # Skip packets when network busy
AMBILIGHT_TOP_LED_COUNT = int(os.getenv('AMBILIGHT_TOP_LED_COUNT', '89'))
AMBILIGHT_BOTTOM_LED_COUNT = int(os.getenv('AMBILIGHT_BOTTOM_LED_COUNT', '89'))
AMBILIGHT_LEFT_LED_COUNT = int(os.getenv('AMBILIGHT_LEFT_LED_COUNT', '49'))
AMBILIGHT_RIGHT_LED_COUNT = int(os.getenv('AMBILIGHT_RIGHT_LED_COUNT', '49'))

EXPECTED_LED_COUNT = (
    AMBILIGHT_TOP_LED_COUNT + AMBILIGHT_BOTTOM_LED_COUNT +
    AMBILIGHT_LEFT_LED_COUNT + AMBILIGHT_RIGHT_LED_COUNT
)

# File storage configuration
AMBILIGHT_DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")

# Service intervals
LIBRARY_SCAN_INTERVAL = int(os.getenv('LIBRARY_SCAN_INTERVAL', '3600'))  # 1 hour - scan for new videos
PLAYBACK_MONITOR_INTERVAL = float(os.getenv('PLAYBACK_MONITOR_INTERVAL', '1.0'))  # 1 second - HTTP polling

# Frame extraction priority settings
EXTRACTION_PRIORITY = os.getenv('EXTRACTION_PRIORITY', 'newest_first')
EXTRACTION_BATCH_SIZE = int(os.getenv('EXTRACTION_BATCH_SIZE', '5'))

# Device-WLED Pairing Configuration
DEVICE_MATCH_FIELD = os.getenv('DEVICE_MATCH_FIELD', 'DeviceName')  # DeviceName, Client, or DeviceId
ENABLE_EXTRACTION = os.getenv('ENABLE_EXTRACTION', 'true').lower() == 'true'

# Global state
shutdown_event = threading.Event()
logger = logging.getLogger(__name__)


class FileBasedAmbilightDaemon:
    """File-based ambilight daemon - no database needed!"""

    def __init__(self):
        print("ambilight_daemon-files.py: FileBasedAmbilightDaemon __init__")
        self.udp_socket = None
        self.active_sessions: Dict[str, Dict] = {}
        self.storage = FileBasedStorage(AMBILIGHT_DATA_DIR)
        self.udp_cache: Dict[str, bytes] = {}  # Cache for frequently accessed packets
        self._last_state_by_device: Dict[str, bytearray] = {}  # For DNRGB sparse runs
        self._last_raw_by_device: Dict[str, bytearray] = {}  # For UDP_RAW smoothing
        self._session_stream_state: Dict[str, Dict] = {}  # session_id -> {last_index:int}
        self._wled_original_state = None  # Store original WLED state
        self._broadcasters: Dict[str, any] = {}  # session_id -> AmbilightBroadcaster
        self._last_sync_ts: Dict[str, float] = {}  # session_id -> last sync wall time
        self._no_match_logged_devices = set()  # Track devices already logged as having no mapping
        self._play_logged_item_by_session: Dict[str, str] = {}  # session_id -> item_id already logged as started
        self._mapping_logged_devices = set()  # Devices for which a positive mapping log was already emitted
        # Jellyfin DNS cache
        self._jellyfin_parsed = urlparse(JELLYFIN_BASE_URL) if JELLYFIN_BASE_URL else None
        self._jellyfin_resolved_ip = None
        self._jellyfin_last_resolve_ts = 0.0

        # Initialize UDP socket
        self.init_udp_socket()

        # Load device-WLED mappings
        self.device_wled_mappings = self.load_device_wled_mappings()

        logger.info("📁 File-Based Jellyfin Ambilight Daemon")
        logger.info(f"   JELLYFIN: {JELLYFIN_BASE_URL}")
        logger.info(f"   WLED: {WLED_HOST}:{WLED_UDP_PORT}")
        logger.info(f"   STORAGE: {AMBILIGHT_DATA_DIR}")
        logger.info(f"   DEVICE MATCHING: {DEVICE_MATCH_FIELD}")
        if self.device_wled_mappings:
            logger.info(f"   📱 Device-WLED Mappings: {len(self.device_wled_mappings)} configured")
        logger.info("   🎯 No database - just simple files!")

    def init_udp_socket(self):
        """Initialize UDP socket for WLED communication"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            logger.info("✅ UDP socket initialized for WLED")
        except Exception as e:
            logger.error(f"❌ UDP socket failed: {e}")

    def load_device_wled_mappings(self) -> Dict[str, Dict[str, str]]:
        """Load device-WLED mappings from environment variables

        Format: WLED_DEVICE_<IDENTIFIER>=host:port
        Example: WLED_DEVICE_LIVING_ROOM=wled-lr.lan:21324
        """
        mappings = {}

        for key, value in os.environ.items():
            if key.startswith('WLED_DEVICE_'):
                # Extract device identifier from env var name
                device_identifier = key[12:]  # Remove 'WLED_DEVICE_' prefix

                # Parse host:port
                if ':' in value:
                    host, port_str = value.split(':', 1)
                    try:
                        port = int(port_str)
                    except ValueError:
                        logger.warning(f"⚠️  Invalid port in {key}={value}, using default 21324")
                        port = 21324
                else:
                    host = value
                    port = 21324

                mappings[device_identifier] = {
                    'host': host,
                    'port': port
                }
                logger.info(f"📱 Device mapping: {device_identifier} → {host}:{port}")

        return mappings

    def ensure_wled_is_on(self, wled_host):
        """Ensure WLED is turned on (using wled_player.py approach)"""
        try:
            # Turn on WLED if off (like wled_player.py does)
            requests.post(f"http://{wled_host}/json/state", json={"on": True}, timeout=3)
        except Exception:
            pass  # Continue even if WLED control fails

    def _resolve_jellyfin_if_needed(self, force: bool = False):
        if not self._jellyfin_parsed:
            return
        # If DNS resolution is disabled, always use hostname
        if AMBILIGHT_DISABLE_DNS_RESOLVE:
            self._jellyfin_resolved_ip = None
            return

        now = time.time()
        # If TTL is 0, always resolve fresh
        if AMBILIGHT_DNS_TTL_SECONDS == 0:
            force = True
        if not force and self._jellyfin_resolved_ip and (now - self._jellyfin_last_resolve_ts) < AMBILIGHT_DNS_TTL_SECONDS:
            return
        try:
            # Use thread-safe timeout for DNS resolution
            import threading
            import queue

            result_queue = queue.Queue()
            exception_queue = queue.Queue()

            def dns_worker():
                try:
                    infos = socket.getaddrinfo(self._jellyfin_parsed.hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
                    if infos:
                        ip = infos[0][4][0]
                        result_queue.put(ip)
                except Exception as e:
                    exception_queue.put(e)

            # Start DNS resolution in a separate thread
            dns_thread = threading.Thread(target=dns_worker, daemon=True)
            dns_thread.start()

            # Wait for result with timeout
            dns_thread.join(timeout=5.0)

            if dns_thread.is_alive():
                # Timeout occurred
                logger.warning(f"DNS resolution timeout for Jellyfin host {self._jellyfin_parsed.hostname}")
                return

            # Check for results
            if not exception_queue.empty():
                raise exception_queue.get()

            if not result_queue.empty():
                ip = result_queue.get()
                self._jellyfin_resolved_ip = ip
                self._jellyfin_last_resolve_ts = now
                logger.info(f"DNS resolved Jellyfin {self._jellyfin_parsed.hostname} → {ip}")

        except Exception as e:
            logger.warning(f"DNS resolve failed for Jellyfin host {self._jellyfin_parsed.hostname}: {e}")

    def _jellyfin_base_resolved(self) -> tuple[str, dict]:
        """Return base URL using cached IP and required Host header."""
        if not self._jellyfin_parsed:
            return JELLYFIN_BASE_URL, {}
        self._resolve_jellyfin_if_needed()
        host = self._jellyfin_resolved_ip or self._jellyfin_parsed.hostname
        port = f":{self._jellyfin_parsed.port}" if self._jellyfin_parsed.port else ''
        base = f"{self._jellyfin_parsed.scheme}://{host}{port}"
        return base, {"Host": self._jellyfin_parsed.netloc}

    def save_wled_state(self, wled_host):
        """Save current WLED state (using wled_player.py approach)"""
        if self._wled_original_state is None:
            self._wled_original_state = get_wled_state()
            if self._wled_original_state:
                logger.info("💾 Saved current WLED state")

    def restore_wled_state(self, wled_host):
        """Restore original WLED state (using wled_player.py approach)"""
        if self._wled_original_state:
            restore_wled_state_fn(self._wled_original_state)
            logger.info("✅ Restored original WLED state")

    def get_wled_target_for_session(self, session: Dict) -> tuple[str, int] | tuple[None, None]:
        """Resolve WLED target for a session using WLED_DEVICE_* mapping.

        Returns (None, None) when there is no match so callers can no-op.
        """
        import re
        def _normalize(name: str) -> str:
            # Lowercase and strip all non-alphanumeric characters
            return re.sub(r'[^a-z0-9]+', '', (name or '').lower())
        if not self.device_wled_mappings:
            # No device mappings configured → do nothing
            logger.debug("No WLED_DEVICE_* mappings configured; skipping broadcast")
            return (None, None)

        # Get device identifier from session
        device_value = session.get(DEVICE_MATCH_FIELD, '').strip()
        device_norm = _normalize(device_value)
        if logger.isEnabledFor(logging.DEBUG):
            try:
                available = ", ".join([f"{k}({ _normalize(k) })" for k in self.device_wled_mappings.keys()])
            except Exception:
                available = str(list(self.device_wled_mappings.keys()))
            logger.debug(f"Device matching: field={DEVICE_MATCH_FIELD} value='{device_value}' norm='{device_norm}' | available=[{available}]")

        if not device_value:
            logger.debug(f"No {DEVICE_MATCH_FIELD} found in session; skipping broadcast (no mapping)")
            return (None, None)

        # Check for exact match first (raw and normalized)
        if device_value in self.device_wled_mappings:
            mapping = self.device_wled_mappings[device_value]
            if device_value not in self._mapping_logged_devices:
                self._mapping_logged_devices.add(device_value)
                logger.info(f"📱 Exact WLED mapping match for device '{device_value}' → {mapping.get('host')}")
            return mapping.get('host'), WLED_UDP_RAW_PORT

        # Normalized exact match across identifiers
        for identifier, mapping in self.device_wled_mappings.items():
            if _normalize(identifier) == device_norm:
                if device_value not in self._mapping_logged_devices:
                    self._mapping_logged_devices.add(device_value)
                    logger.info(f"📱 Normalized mapping match: '{device_value}' ≈ '{identifier}' → {mapping.get('host')}")
                return mapping.get('host'), WLED_UDP_RAW_PORT

        # Check for partial matches (case insensitive)
        device_lower = device_value.lower()
        for identifier, mapping in self.device_wled_mappings.items():
            ident_lower = identifier.lower()
            ident_norm = _normalize(identifier)
            if ident_lower in device_lower or device_lower in ident_lower or ident_norm in device_norm or device_norm in ident_norm:
                if device_value not in self._mapping_logged_devices:
                    self._mapping_logged_devices.add(device_value)
                    logger.info(f"📱 Partial/normalized match: '{device_value}' ↔ '{identifier}' → {mapping.get('host')}")
                return mapping.get('host'), WLED_UDP_RAW_PORT

        # No match found → only log once per device
        if device_value not in self._no_match_logged_devices:
            self._no_match_logged_devices.add(device_value)
            logger.info(f"🚫 No WLED_DEVICE_* match for device '{device_value}' (norm '{device_norm}') with field {DEVICE_MATCH_FIELD}; ambilight will not play")
        return (None, None)

    def send_udp_packet_direct(self, udp_packet):
        """Send pre-built UDP packet directly to WLED"""
        if not self.udp_socket or not udp_packet:
            return False

        try:
            # Fast path for UDP_RAW: treat content as RAW RGB and send to raw port
            if WLED_UDP_PROTOCOL == 'UDP_RAW':
                # Expect raw RGB frames (no header). Fit to physical strip length.
                raw = udp_packet
                need = WLED_LED_COUNT * 3
                if len(raw) < need:
                    raw = raw + bytes([0] * (need - len(raw)))
                elif len(raw) > need:
                    raw = raw[:need]
                # Optional smoothing (EMA) to reduce abrupt transitions
                # if SMOOTHING_ENABLED:
                #     device_key = f"{WLED_HOST}:{WLED_UDP_RAW_PORT}"
                #     prev = self._last_raw_by_device.get(device_key)
                #     if prev is None or len(prev) != need:
                #         prev = bytearray(raw)
                #     # Apply EMA: prev = prev + alpha*(raw - prev)
                #     alpha = SMOOTHING_ALPHA
                #     smoothed = bytearray(need)
                #     for i in range(need):
                #         p = prev[i]
                #         c = raw[i]
                #         smoothed[i] = int(p + (c - p) * alpha)
                #     raw = bytes(smoothed)
                #     self._last_raw_by_device[device_key] = bytearray(raw)
                # Safety: enforce Hyperion UDP raw default port 19446
                raw_port = WLED_UDP_RAW_PORT if WLED_UDP_RAW_PORT and WLED_UDP_RAW_PORT != 21324 else 19446
                if raw_port != WLED_UDP_RAW_PORT:
                    logger.info(f"🔁 Using UDP RAW port {raw_port} (overriding {WLED_UDP_RAW_PORT})")
                self.udp_socket.sendto(raw, (WLED_HOST, raw_port))
                return True

            # MPKT container: multiple UDP datagrams packed in one blob
            if len(udp_packet) >= 4 and udp_packet[:4] == b'MPKT':
                # Format: 'MPKT' + count(uint16 LE) + [len(uint16 LE) + packet] * count
                import struct as _struct
                offset = 4
                if len(udp_packet) < 6:
                    return False
                count = _struct.unpack('<H', udp_packet[offset:offset+2])[0]
                offset += 2
                for _ in range(count):
                    if offset + 2 > len(udp_packet):
                        break
                    plen = _struct.unpack('<H', udp_packet[offset:offset+2])[0]
                    offset += 2
                    pkt = udp_packet[offset:offset+plen]
                    offset += plen
                    if pkt:
                        self.udp_socket.sendto(pkt, (WLED_HOST, WLED_UDP_PORT))
                return True

            # Accept DRGB frames from storage and convert based on configured protocol
            if len(udp_packet) >= 5 and udp_packet[:4] == b'DRGB':
                timeout_byte = udp_packet[4]
                rgb_payload = udp_packet[5:]
            else:
                logger.warning("⚠️  Unexpected packet header; treating as raw RGB payload")
                timeout_byte = 1
                rgb_payload = udp_packet
            led_triplets = len(rgb_payload) // 3
            if led_triplets != EXPECTED_LED_COUNT:
                logger.warning(
                    f"⚠️  LED count mismatch: payload={led_triplets}, expected={EXPECTED_LED_COUNT}. "
                    "Auto-adjusting (pad/truncate)."
                )
                if led_triplets < EXPECTED_LED_COUNT:
                    # pad with zeros
                    pad = bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
                    rgb_payload = rgb_payload + pad
                else:
                    # truncate extra LEDs
                    rgb_payload = rgb_payload[: EXPECTED_LED_COUNT * 3]

            # Fit to WLED strip length
            if EXPECTED_LED_COUNT != WLED_LED_COUNT:
                if EXPECTED_LED_COUNT < WLED_LED_COUNT:
                    rgb_payload = rgb_payload + bytes([0, 0, 0] * (WLED_LED_COUNT - EXPECTED_LED_COUNT))
                else:
                    rgb_payload = rgb_payload[: WLED_LED_COUNT * 3]

            # Build final packet according to protocol
            if WLED_UDP_PROTOCOL == 'DRGB':
                packet_to_send = b'DRGB' + bytes([timeout_byte]) + rgb_payload
            elif WLED_UDP_PROTOCOL == 'WARLS':
                # WARLS: [0x01][timeout][index][R][G][B]...
                num_leds = len(rgb_payload) // 3
                max_leds = min(num_leds, 255)
                if num_leds > 255:
                    logger.warning("⚠️  WARLS supports max 255 LEDs per packet; truncating to 255")
                packet = bytearray([1, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1])
                for i in range(max_leds):
                    base = i * 3
                    r, g, b = rgb_payload[base], rgb_payload[base + 1], rgb_payload[base + 2]
                    packet.extend([i & 0xFF, r, g, b])
                packet_to_send = bytes(packet)
            elif WLED_UDP_PROTOCOL == 'DNRGB':
                # DNRGB sparse: send only changed contiguous runs; protocol byte 4
                device_key = f"{WLED_HOST}:{WLED_UDP_PORT}"
                last_state = self._last_state_by_device.get(device_key)
                if last_state is None or len(last_state) != WLED_LED_COUNT * 3:
                    last_state = bytearray([0] * (WLED_LED_COUNT * 3))

                i = 0
                max_run = 489  # per WLED docs
                sent_any = False
                while i < WLED_LED_COUNT:
                    base = i * 3
                    if rgb_payload[base:base+3] != last_state[base:base+3]:
                        run_start = i
                        run_len = 0
                        chunk = bytearray()
                        while i < WLED_LED_COUNT and run_len < max_run and rgb_payload[i*3:(i*3)+3] != last_state[i*3:(i*3)+3]:
                            chunk.extend(rgb_payload[i*3:(i*3)+3])
                            last_state[i*3:(i*3)+3] = rgb_payload[i*3:(i*3)+3]
                            i += 1
                            run_len += 1
                        start_hi = (run_start >> 8) & 0xFF
                        start_lo = run_start & 0xFF
                        pkt = bytearray([4, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1, start_hi, start_lo])
                        pkt.extend(chunk)
                        self.udp_socket.sendto(bytes(pkt), (WLED_HOST, WLED_UDP_PORT))
                        sent_any = True
                    else:
                        i += 1
                self._last_state_by_device[device_key] = last_state
                return True if sent_any else True

            else:  # UDP_RAW
                # Hyperion UDP raw: send pure RGB bytes (no header) to port 19446
                # Always full strip length
                try:
                    self.udp_socket.sendto(bytes(rgb_payload[: WLED_LED_COUNT * 3]), (WLED_HOST, WLED_UDP_RAW_PORT))
                    return True
                except Exception as e:
                    logger.error(f"UDP RAW transmission error: {e}")
                    return False

            self.udp_socket.sendto(packet_to_send, (WLED_HOST, WLED_UDP_PORT))
            return True
        except Exception as e:
            logger.error(f"UDP transmission error: {e}")
            return False

    def send_udp_packet_to_device(self, udp_packet, wled_host, wled_port):
        """Send pre-built UDP packet to specific WLED device"""
        if not self.udp_socket or not udp_packet:
            return False

        try:
            # Fast path for UDP_RAW
            if WLED_UDP_PROTOCOL == 'UDP_RAW':
                raw = udp_packet
                need = WLED_LED_COUNT * 3
                if len(raw) < need:
                    raw = raw + bytes([0] * (need - len(raw)))
                elif len(raw) > need:
                    raw = raw[:need]
                if COLOR_FILTER_ENABLED:
                    raw = self._apply_color_filter(raw)
                if SMOOTHING_ENABLED:
                    device_key = f"{wled_host}:{WLED_UDP_RAW_PORT}"
                    prev = self._last_raw_by_device.get(device_key)
                    if prev is None or len(prev) != need:
                        prev = bytearray(raw)
                    alpha = SMOOTHING_ALPHA
                    smoothed = bytearray(need)
                    for i in range(need):
                        p = prev[i]
                        c = raw[i]
                        smoothed[i] = int(p + (c - p) * alpha)
                    raw = bytes(smoothed)
                    self._last_raw_by_device[device_key] = bytearray(raw)
                raw_port = WLED_UDP_RAW_PORT if WLED_UDP_RAW_PORT and WLED_UDP_RAW_PORT != 21324 else 19446
                if raw_port != WLED_UDP_RAW_PORT:
                    logger.info(f"🔁 Using UDP RAW port {raw_port} (overriding {WLED_UDP_RAW_PORT}) for {wled_host}")

                # Send with retry logic for network resilience
                return self._send_udp_with_retry(raw, wled_host, raw_port)

            # MPKT container support
            if len(udp_packet) >= 4 and udp_packet[:4] == b'MPKT':
                import struct as _struct
                offset = 4
                if len(udp_packet) < 6:
                    return False
                count = _struct.unpack('<H', udp_packet[offset:offset+2])[0]
                offset += 2
                for _ in range(count):
                    if offset + 2 > len(udp_packet):
                        break
                    plen = _struct.unpack('<H', udp_packet[offset:offset+2])[0]
                    offset += 2
                    pkt = udp_packet[offset:offset+plen]
                    offset += plen
                    if pkt:
                        self._send_udp_with_retry(pkt, wled_host, wled_port)
                return True

            # Accept DRGB frames from storage and convert based on configured protocol
            if len(udp_packet) >= 5 and udp_packet[:4] == b'DRGB':
                timeout_byte = udp_packet[4]
                rgb_payload = udp_packet[5:]
            else:
                logger.warning("⚠️  Unexpected packet header; treating as raw RGB payload")
                timeout_byte = 1
                rgb_payload = udp_packet

            led_triplets = len(rgb_payload) // 3
            if led_triplets != EXPECTED_LED_COUNT:
                logger.warning(
                    f"⚠️  LED count mismatch: payload={led_triplets}, expected={EXPECTED_LED_COUNT}. "
                    "Auto-adjusting (pad/truncate)."
                )
                if led_triplets < EXPECTED_LED_COUNT:
                    # pad with zeros
                    pad = bytes([0, 0, 0] * (EXPECTED_LED_COUNT - led_triplets))
                    rgb_payload = rgb_payload + pad
                else:
                    # truncate extra LEDs
                    rgb_payload = rgb_payload[: EXPECTED_LED_COUNT * 3]

            # Fit to WLED strip length
            if EXPECTED_LED_COUNT != WLED_LED_COUNT:
                if EXPECTED_LED_COUNT < WLED_LED_COUNT:
                    rgb_payload = rgb_payload + bytes([0, 0, 0] * (WLED_LED_COUNT - EXPECTED_LED_COUNT))
                else:
                    rgb_payload = rgb_payload[: WLED_LED_COUNT * 3]

            if WLED_UDP_PROTOCOL == 'DRGB':
                packet_to_send = b'DRGB' + bytes([timeout_byte]) + rgb_payload
                self._send_udp_with_retry(packet_to_send, wled_host, wled_port)
            elif WLED_UDP_PROTOCOL == 'WARLS':
                num_leds = len(rgb_payload) // 3
                max_leds = min(num_leds, 255)
                if num_leds > 255:
                    logger.warning("⚠️  WARLS supports max 255 LEDs per packet; truncating to 255")
                packet = bytearray([1, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1])
                for i in range(max_leds):
                    base = i * 3
                    r, g, b = rgb_payload[base], rgb_payload[base + 1], rgb_payload[base + 2]
                    packet.extend([i & 0xFF, r, g, b])
                self._send_udp_with_retry(bytes(packet), wled_host, wled_port)
            elif WLED_UDP_PROTOCOL == 'DNRGB':
                # DNRGB sparse
                device_key = f"{wled_host}:{wled_port}"
                last_state = self._last_state_by_device.get(device_key)
                if last_state is None or len(last_state) != WLED_LED_COUNT * 3:
                    last_state = bytearray([0] * (WLED_LED_COUNT * 3))
                i = 0
                max_run = 489
                while i < WLED_LED_COUNT:
                    base = i * 3
                    if rgb_payload[base:base+3] != last_state[base:base+3]:
                        run_start = i
                        run_len = 0
                        chunk = bytearray()
                        while i < WLED_LED_COUNT and run_len < max_run and rgb_payload[i*3:(i*3)+3] != last_state[i*3:(i*3)+3]:
                            chunk.extend(rgb_payload[i*3:(i*3)+3])
                            last_state[i*3:(i*3)+3] = rgb_payload[i*3:(i*3)+3]
                            i += 1
                            run_len += 1
                        start_hi = (run_start >> 8) & 0xFF
                        start_lo = run_start & 0xFF
                        pkt = bytearray([4, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1, start_hi, start_lo])
                        pkt.extend(chunk)
                        self._send_udp_with_retry(bytes(pkt), wled_host, wled_port)
                    else:
                        i += 1
                self._last_state_by_device[device_key] = last_state
            else:
                # UDP_RAW
                return self._send_udp_with_retry(bytes(rgb_payload[: WLED_LED_COUNT * 3]), wled_host, WLED_UDP_RAW_PORT)
            return True
        except Exception as e:
            logger.error(f"UDP transmission error to {wled_host}:{wled_port}: {e}")
            return False

    def _send_udp_with_retry(self, data, host, port, max_retries=None):
        """Send UDP data with single attempt - skip on failure to maintain sync"""
        if not self.udp_socket or not data:
            return False

        try:
            # Single attempt - no retries to maintain sync
            self.udp_socket.sendto(data, (host, port))
            return True
        except OSError as e:
            if e.errno == -3:  # "Try again" error
                # Skip this packet silently to maintain sync
                if UDP_SKIP_ON_BUSY:
                    logger.debug(f"UDP send skipped (network busy) to {host}:{port}")
                    return False
                else:
                    # Log the skip for debugging
                    logger.warning(f"UDP send failed (network busy) to {host}:{port}")
                    return False
            else:
                # Other network errors - log once per session
                logger.error(f"UDP network error to {host}:{port}: {e}")
                return False
        except Exception as e:
            logger.error(f"UDP transmission error to {host}:{port}: {e}")
            return False

    def log_session_device_info(self, session: Dict):
        """Log detailed device information for a session (useful for setup/debugging)"""
        device_name = session.get('DeviceName', 'Unknown')
        client = session.get('Client', 'Unknown')
        device_id = session.get('DeviceId', 'Unknown')
        user = session.get('UserName', 'Unknown')

        logger.info("📱 Session Device Info:")
        logger.info(f"   DeviceName: '{device_name}'")
        logger.info(f"   Client: '{client}'")
        logger.info(f"   DeviceId: '{device_id}'")
        logger.info(f"   User: '{user}'")
        logger.info(f"   Current Match Field ({DEVICE_MATCH_FIELD}): '{session.get(DEVICE_MATCH_FIELD, 'None')}'")

    def get_binary_frame_for_playback(self, item_id, timestamp_seconds):
        """Get binary frame data for specific timestamp using wled_player.py approach"""
        cache_key = f"{item_id}_{timestamp_seconds:.1f}"

        # Check cache first
        if cache_key in self.udp_cache:
            return self.udp_cache[cache_key]

        # Get binary file path
        data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
        binary_file = data_dir / "binaries" / f"{item_id}.bin"

        if not binary_file.exists():
            return None

        try:
            with open(binary_file, "rb") as f:
                # Use wled_player.py header reading approach
                magic = f.read(4)
                if magic != b"AMBI":
                    return None

                # Read header values (needed for proper parsing)
                fps = struct.unpack("<H", f.read(2))[0]
                led_count = struct.unpack("<H", f.read(2))[0]
                fmt = struct.unpack("<B", f.read(1))[0]
                offset = struct.unpack("<H", f.read(2))[0]
                rgbw = (fmt == 1)

                # Log header info for debugging
                logger.debug(f"Binary file header: fps={fps}, leds={led_count}, rgbw={rgbw}, offset={offset}")

                # Find frame closest to timestamp (using wled_player.py logic)
                closest_frame = None
                min_diff = float('inf')

                while True:
                    header = f.read(10)
                    if not header:
                        break

                    timestamp, payload_len = struct.unpack("<dH", header)
                    payload = f.read(payload_len)

                    if not payload:
                        break

                    # Check if this frame is closer to target timestamp
                    diff = abs(timestamp - timestamp_seconds)
                    if diff < min_diff:
                        min_diff = diff
                        closest_frame = payload

                        # If we're very close, we can stop searching
                        if diff < 0.1:  # Within 100ms
                            break

                if closest_frame:
                    # Cache for future use (keep cache size reasonable)
                    if len(self.udp_cache) > 100:  # Limit cache size
                        # Remove oldest entries
                        oldest_key = next(iter(self.udp_cache))
                        del self.udp_cache[oldest_key]

                    self.udp_cache[cache_key] = closest_frame
                    return closest_frame

        except Exception as e:
            logger.error(f"Error reading binary file {binary_file}: {e}")

        return None

    def send_raw_frame_to_wled(self, frame_data, wled_host, wled_port):
        """Send raw frame data to WLED using wled_player.py approach"""
        if not self.udp_socket or not frame_data:
            return False

        try:
            # Use wled_player.py port configuration (default 19446 for UDP_RAW)
            # This matches the wled_player.py approach exactly
            self.udp_socket.sendto(frame_data, (wled_host, wled_port))
            return True
        except Exception as e:
            logger.error(f"Frame transmission error to {wled_host}:{wled_port}: {e}")
            return False

    def turn_off_wled(self):
        """Turn off WLED using simplified black frame approach"""
        try:
            # Send black frame using UDP_RAW protocol (simplified)
            led_count = WLED_LED_COUNT
            black_frame = bytes([0, 0, 0] * led_count)
            self.udp_socket.sendto(black_frame, (WLED_HOST, WLED_UDP_RAW_PORT))
            return True
        except Exception as e:
            logger.error(f"Turn off WLED error: {e}")
            return False

    def get_jellyfin_user_id(self):
        """Get the first available Jellyfin user ID"""
        try:
            base, host_header = self._jellyfin_base_resolved()
            hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
            hdrs.update(host_header)
            response = requests.get(
                f"{base}/Users",
                headers=hdrs,
                timeout=10
            )
            response.raise_for_status()

            users = response.json()
            if users:
                user_id = users[0]["Id"]
                logger.info(f"🔐 Using Jellyfin user: {users[0].get('Name', 'Unknown')}")
                return user_id
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Jellyfin server connection failed: {e}")
        except requests.exceptions.Timeout as e:
            logger.warning(f"Jellyfin server timeout: {e}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Jellyfin server request failed: {e}")
        except Exception as e:
            logger.warning(f"Failed to get Jellyfin user: {e}")

        return None

    def get_jellyfin_sessions(self):
        """Get current Jellyfin playback sessions via HTTP API (NOT WebSocket!)"""
        try:
            # Use proper MediaBrowser authorization header format
            headers = {
                "Authorization": f'MediaBrowser Client="ambilight-files", Device="Python", DeviceId="ambilight-files-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
            }

            base, host_header = self._jellyfin_base_resolved()
            headers.update(host_header)
            response = requests.get(
                f"{base}/Sessions",
                headers=headers,
                timeout=5
            )
            response.raise_for_status()
            sessions = response.json()

            # Filter for active video playback sessions only
            video_sessions = []
            for session in sessions:
                now_playing = session.get("NowPlayingItem")
                if now_playing and now_playing.get("Type") in ["Movie", "Episode", "Video"]:
                    video_sessions.append(session)

            return video_sessions

        except Exception as e:
            logger.error(f"Failed to get sessions: {e}")
            return []

    def monitor_playback_with_files(self):
        """Monitor playback and control ambilight using file storage"""
        logger.info("🎬 Starting file-based playback monitoring...")

        consecutive_errors = 0
        max_errors = 5

        while not shutdown_event.is_set():
            try:
                # Get video sessions (already filtered)
                active_video_sessions = self.get_jellyfin_sessions()

                # Reset error counter on success
                consecutive_errors = 0

                if active_video_sessions:
                    # Process each active session
                    for session in active_video_sessions:
                        session_id = session["Id"]
                        item = session["NowPlayingItem"]
                        item_id = item["Id"]

                        # Get playback state
                        play_state = session.get("PlayState", {})
                        is_playing = not play_state.get("IsPaused", True)
                        position_ticks = play_state.get("PositionTicks", 0)
                        position_seconds = position_ticks / 10_000_000 if position_ticks else 0

                        # Carry forward previously known target to avoid unbound locals on paused states
                        prev_info = self.active_sessions.get(session_id, {})
                        wled_host = prev_info.get('wled_host')
                        wled_port = prev_info.get('wled_port')

                        # Detect play start transition
                        prev_is_playing = self.active_sessions.get(session_id, {}).get('is_playing', False)
                        if is_playing and not prev_is_playing:
                            device_value = session.get(DEVICE_MATCH_FIELD, '').strip()
                            user_name = session.get('UserName', 'Unknown')
                            # Only log once per session+item until pause or item change
                            last_logged_item = self._play_logged_item_by_session.get(session_id)
                            if last_logged_item != item_id:
                                logger.info(f"▶️ Play started: {item.get('Name', 'Unknown')} ({item_id}) by {user_name} on device '{device_value}'")
                                self._play_logged_item_by_session[session_id] = item_id
                            # If we have an existing broadcaster and it was paused, resume it
                            b = self._broadcasters.get(session_id)
                            if b:
                                try:
                                    resume_broadcast(b)
                                except Exception:
                                    pass

                        if is_playing:
                            # Get device-specific WLED target
                            wled_host, wled_port = self.get_wled_target_for_session(session)
                            if not wled_host or not wled_port:
                                # No mapping match → log and skip broadcasting for this session
                                device_value = session.get(DEVICE_MATCH_FIELD, '').strip()
                                if device_value not in self._no_match_logged_devices:
                                    self._no_match_logged_devices.add(device_value)
                                    logger.info(f"🚫 No WLED_DEVICE_* match for device '{device_value}' (field {DEVICE_MATCH_FIELD}); ambilight will not play")
                                continue

                            # Ensure WLED is on (using wled_player.py approach)
                            self.ensure_wled_is_on(wled_host)

                            # Save WLED state on first playback
                            if session_id not in self.active_sessions:
                                self.save_wled_state(wled_host)

                            # Start or sync broadcaster for this session
                            # Build binary file path for the playing item
                            data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
                            binary_file = data_dir / "binaries" / f"{item_id}.bin"

                            if binary_file.exists():
                                # Create broadcaster if new session
                                if session_id not in self._broadcasters:
                                    try:
                                        b = create_broadcaster(str(binary_file), wled_host=wled_host, wled_port=wled_port)
                                        # Capture timestamp when we sampled playback state
                                        sample_ts = time.time()
                                        b.start(start_seconds=position_seconds, source_wall_ts=sample_ts)
                                        self._broadcasters[session_id] = b
                                        self._last_sync_ts[session_id] = time.time()
                                        logger.info(f"▶️  Broadcaster started for session {session_id} at {position_seconds:.2f}s")
                                    except Exception as e:
                                        logger.error(f"Failed to start broadcaster for {session_id}: {e}")
                                else:
                                    # Periodic resync (can be disabled)
                                    if not AMBILIGHT_DISABLE_PERIODIC_RESYNC:
                                        now = time.time()
                                        last = self._last_sync_ts.get(session_id, 0)
                                        if now - last >= 0.2:
                                            try:
                                                # Use the time we sampled to compensate for polling latency
                                                sample_ts = time.time()
                                                sync_broadcast_to(self._broadcasters[session_id], position_seconds, source_wall_ts=sample_ts)
                                                self._last_sync_ts[session_id] = now
                                            except Exception as e:
                                                logger.warning(f"Broadcaster sync failed for {session_id}: {e}")
                            else:
                                # No frame data available yet
                                if session_id not in self.active_sessions or self.active_sessions[session_id].get('warned', False) is False:
                                    logger.info(f"⏳ Waiting for frame extraction: {item.get('Name', 'Unknown')} ({item_id})")
                                    if session_id not in self.active_sessions:
                                        self.active_sessions[session_id] = {}
                                    self.active_sessions[session_id]['warned'] = True

                        else:
                            # Paused: pause any active broadcaster
                            b = self._broadcasters.get(session_id)
                            if b:
                                try:
                                    pause_broadcast(b)
                                except Exception:
                                    pass
                            # Allow future resume to log again
                            self._play_logged_item_by_session.pop(session_id, None)

                        # Track session
                        self.active_sessions[session_id] = {
                            'item_id': item_id,
                            'item_name': item.get('Name', 'Unknown'),
                            'is_playing': is_playing,
                            'position_seconds': position_seconds,
                            'last_seen': datetime.now(),
                            'warned': self.active_sessions.get(session_id, {}).get('warned', False),
                            'wled_host': wled_host,
                            'wled_port': wled_port
                        }

                        # Broadcaster watchdog: if playing but thread died, recreate and start
                        if is_playing:
                            b = self._broadcasters.get(session_id)
                            if b and hasattr(b, 'is_thread_alive') and not b.is_thread_alive():
                                try:
                                    logger.warning(f"🔁 Broadcaster thread not alive for session {session_id}, restarting")
                                    # Recreate broadcaster to ensure fresh resources
                                    b2 = create_broadcaster(str(binary_file), wled_host=wled_host, wled_port=wled_port)
                                    b2.start(start_seconds=position_seconds)
                                    self._broadcasters[session_id] = b2
                                    self._last_sync_ts[session_id] = time.time()
                                except Exception as e:
                                    logger.error(f"Failed to restart broadcaster for {session_id}: {e}")

                        # Reset sync state if this is a new item or significant position jump (seek)
                        if session_id in self._session_stream_state:
                            stream_state = self._session_stream_state[session_id]
                            last_item = stream_state.get('last_item_id')
                            last_position = stream_state.get('last_position', 0)

                            # Reset if new item or significant seek (>2 seconds jump)
                            if (last_item != item_id or
                                abs(position_seconds - last_position) > 2.0):
                                logger.info(f"🔄 Resetting sync state for {item_id} (new item or seek)")
                                self._session_stream_state[session_id] = {
                                    'last_index': -1,
                                    'data_load_start_time': None,
                                    'sync_offset': 0.0,
                                    'data_loaded': False,
                                    'last_item_id': item_id,
                                    'last_position': position_seconds
                                }

                else:
                    # No active sessions - stop broadcasters and turn off
                    if self.active_sessions:
                        logger.info("⏸️  No active video playback - stopping broadcasters and turning off ambilight")
                        for sid, b in list(self._broadcasters.items()):
                            try:
                                b.stop()
                            except Exception:
                                pass
                            finally:
                                self._broadcasters.pop(sid, None)
                                self._last_sync_ts.pop(sid, None)
                        self.turn_off_wled()
                        self.active_sessions.clear()
                        self.udp_cache.clear()  # Clear cache when idle

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"💥 Playback monitoring error ({consecutive_errors}/{max_errors}): {e}")

                if consecutive_errors >= max_errors:
                    logger.error("💥 Too many consecutive errors, stopping playback monitoring")
                    break

            # Wait before next check
            time.sleep(PLAYBACK_MONITOR_INTERVAL)

    def perform_incremental_library_update(self, user_id):
        """Update library items using file storage"""
        try:
            logger.info("🔄 Checking for library updates...")

            base, host_header = self._jellyfin_base_resolved()
            hdrs = {"X-Emby-Token": JELLYFIN_API_KEY}
            hdrs.update(host_header)
            response = requests.get(
                f"{base}/Users/{user_id}/Views",
                headers=hdrs,
                timeout=15
            )
            response.raise_for_status()
            libraries = response.json()

            # Process each library
            for lib in libraries.get("Items", []):
                lib_id = lib['Id']
                lib_name = lib['Name']

                logger.info(f"📚 Checking library: {lib_name}")

                # Get items from this library
                base, host_header = self._jellyfin_base_resolved()
                hdrs2 = {"X-Emby-Token": JELLYFIN_API_KEY}
                hdrs2.update(host_header)
                items_response = requests.get(
                    f"{base}/Users/{user_id}/Items",
                    headers=hdrs2,
                    params={
                        "ParentId": lib_id,
                        "Recursive": "true",
                        "IncludeItemTypes": "Movie,Episode,Video",
                        "Fields": "Path,MediaSources,DateCreated"
                    },
                    timeout=15
                )
                items_response.raise_for_status()
                items = items_response.json().get("Items", [])

                logger.info(f"   Found {len(items)} video items")

                # Save items to file storage (12x faster than database!)
                for item in items:
                    item_id = item["Id"]
                    title = item.get("Name", "Unknown")
                    item_type = item.get("Type", "Unknown")
                    jellyfin_date_created = item.get("DateCreated")  # When item was added to Jellyfin

                    # Get filepath
                    filepath = "Unknown"
                    if "Path" in item:
                        filepath = item["Path"]
                    elif "MediaSources" in item and item["MediaSources"]:
                        filepath = item["MediaSources"][0].get("Path", "Unknown")

                    # Save to file storage with Jellyfin date
                    self.storage.save_item(item_id, lib_id, title, item_type, filepath, jellyfin_date_created)

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Jellyfin server connection failed during library update: {e}")
            raise  # Re-raise to trigger fallback behavior
        except requests.exceptions.Timeout as e:
            logger.warning(f"Jellyfin server timeout during library update: {e}")
            raise  # Re-raise to trigger fallback behavior
        except requests.exceptions.RequestException as e:
            logger.warning(f"Jellyfin server request failed during library update: {e}")
            raise  # Re-raise to trigger fallback behavior
        except Exception as e:
            logger.error(f"Error in incremental library update: {e}")
            raise  # Re-raise to trigger fallback behavior

    def scan_library_for_new_videos(self):
        """Scan library and extract frames with file storage"""
        logger.info("🔄 Starting library scan with file-based storage...")

        # Try to get user ID, but don't fail if Jellyfin is down
        user_id = None
        try:
            user_id = self.get_jellyfin_user_id()
            if user_id:
                logger.info("✅ Jellyfin server accessible - will update library")
            else:
                logger.warning("⚠️  Jellyfin server not accessible - continuing with offline extraction")
        except Exception as e:
            logger.warning(f"⚠️  Jellyfin server not accessible: {e} - continuing with offline extraction")

        while not shutdown_event.is_set():
            try:
                # Update library only if Jellyfin is accessible
                if user_id:
                    try:
                        self.perform_incremental_library_update(user_id)
                        logger.info("✅ Library updated from Jellyfin")
                    except Exception as e:
                        logger.warning(f"⚠️  Failed to update library from Jellyfin: {e} - continuing with offline extraction")
                        user_id = None  # Mark as unavailable for this cycle
                else:
                    logger.info("🔄 Skipping library update (Jellyfin unavailable) - processing existing videos")

                # Drain all pending videos in successive batches without waiting the long interval
                while not shutdown_event.is_set():
                    stats = self.storage.get_extraction_statistics()
                    logger.info(f"📊 Extraction status: {stats['extracted_videos']}/{stats['total_videos']} " +
                               f"({stats['completion_percentage']:.1f}% complete)")

                    if stats['pending_videos'] <= 0:
                        logger.info("✅ No pending videos to extract")
                        break

                    videos_to_process = self.storage.get_videos_needing_extraction(
                        priority_order=EXTRACTION_PRIORITY,
                        limit=EXTRACTION_BATCH_SIZE
                    )
                    batch_count = len(videos_to_process)
                    if batch_count == 0:
                        logger.info("✅ Extraction queue empty")
                        break

                    logger.info(f"🎬 Processing batch of {batch_count} videos...")
                    for i, item in enumerate(videos_to_process):
                        if shutdown_event.is_set():
                            break
                        logger.info(f"📁 Extraction {i+1}/{batch_count}: {item['name']}")
                        try:
                            # Skip if binary exists and is up-to-date
                            data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
                            binary_file = data_dir / "binaries" / f"{item['id']}.bin"
                            src_mtime = Path(item['filepath']).stat().st_mtime if os.path.exists(item['filepath']) else 0
                            dst_mtime = binary_file.stat().st_mtime if binary_file.exists() else 0
                            if binary_file.exists() and dst_mtime >= src_mtime:
                                logger.info(f"⏭️  Skipping (up-to-date): {item['name']}")
                            else:
                                # Use simplified extractor to create binary file
                                extract_frames(item['filepath'], item['id'])

                            # Check if extraction was successful by looking for the binary file
                            data_dir = Path(os.getenv("AMBILIGHT_DATA_DIR", "./data"))
                            binary_file = data_dir / "binaries" / f"{item['id']}.bin"

                            if binary_file.exists():
                                # Get file size to estimate frame count
                                file_size = binary_file.stat().st_size
                                # Estimate frames: (file_size - header_size) / (frame_size + timestamp_size)
                                header_size = 11  # AMBI(4) + fps(2) + led_count(2) + format(1) + offset(2)
                                frame_header_size = 10  # timestamp(8) + payload_len(2)
                                led_count = int(os.getenv("AMBILIGHT_TOP_LED_COUNT", "89")) + int(os.getenv("AMBILIGHT_BOTTOM_LED_COUNT", "89")) + int(os.getenv("AMBILIGHT_LEFT_LED_COUNT", "49")) + int(os.getenv("AMBILIGHT_RIGHT_LED_COUNT", "49"))
                                bytes_per_led = 4 if os.getenv("AMBILIGHT_RGBW", "false").lower() in ("1", "true", "yes") else 3
                                frame_payload_size = led_count * bytes_per_led
                                estimated_frames = (file_size - header_size) // (frame_header_size + frame_payload_size)

                                logger.info(f"✅ Completed: {item['name']} (~{estimated_frames} frames)")
                            else:
                                logger.warning(f"⚠️  No binary file created for: {item['name']}")
                        except Exception as e:
                            logger.error(f"❌ Failed extraction for {item['name']}: {e}")
                    # small pause between batches to yield CPU
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in library scanning: {e}")

            # Wait before next scan
            for _ in range(LIBRARY_SCAN_INTERVAL):
                if shutdown_event.is_set():
                    break
                time.sleep(1)

    def show_storage_info(self):
        """Display storage information"""
        storage_info = self.storage.get_storage_info()
        stats = self.storage.get_extraction_statistics()

        logger.info("📁 FILE STORAGE STATUS:")
        logger.info(f"   Directory: {storage_info['data_directory']}")
        logger.info(f"   Total storage: {storage_info['total_size_mb']:.1f} MB")
        logger.info(f"   Binary files: {storage_info['binary_file_count']}")
        logger.info(f"   Index files: {storage_info['index_file_count']}")
        logger.info(f"   Videos: {stats['extracted_videos']}/{stats['total_videos']} extracted")

    def start(self):
        """Start the file-based daemon service"""
        logger.info("📁 Starting File-Based Ambilight Daemon...")

        # Show storage information
        self.show_storage_info()

        # Start monitoring and streaming threads
        library_thread = None
        if ENABLE_EXTRACTION:
            library_thread = threading.Thread(target=self.scan_library_for_new_videos, daemon=True)
        playback_thread = threading.Thread(target=self.monitor_playback_with_files, daemon=True)
        # Disable legacy streamer loop; broadcasters handle timing and sending
        # streamer_thread = threading.Thread(target=self.stream_frames_loop, daemon=True)

        if library_thread is not None:
            library_thread.start()
        playback_thread.start()
        # streamer_thread.start()

        logger.info("✅ File-based daemon started successfully!")
        if not ENABLE_EXTRACTION:
            logger.info("🛑 Extraction disabled via ENABLE_EXTRACTION=false - running playback only")

        try:
            # Keep main thread alive
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️  Shutdown requested...")
        finally:
            shutdown_event.set()
            # Stop any broadcasters
            for sid, b in list(self._broadcasters.items()):
                try:
                    b.stop()
                except Exception:
                    pass
                finally:
                    self._broadcasters.pop(sid, None)
                    self._last_sync_ts.pop(sid, None)
            self.turn_off_wled()
            # Restore original WLED state (using wled_player.py approach)
            self.restore_wled_state(WLED_HOST)
            logger.info("🔚 File-based daemon stopped")

    def stream_frames_loop(self):
        """Continuously stream RAW frames to WLED at FPS, synchronized to playback position."""
        if STREAM_FPS <= 0:
            logger.warning("⚠️  STREAM_FPS <= 0, streaming disabled")
            return

        while not shutdown_event.is_set():
            try:
                # Iterate over active sessions snapshot
                sessions = list(self.active_sessions.items())
                for session_id, info in sessions:
                    if not info.get('is_playing', False):
                        continue

                    item_id = info.get('item_id')
                    position_seconds = info.get('position_seconds', 0.0) or 0.0
                    wled_host = info.get('wled_host', WLED_HOST)
                    wled_port = info.get('wled_port', WLED_UDP_PORT)

                    # Determine effective FPS from file metadata if available
                    meta = self.storage.get_file_metadata(item_id)
                    fps = meta.get('fps', STREAM_FPS) or STREAM_FPS
                    # Upsample stream timing if TARGET_STREAM_FPS specified
                    # effective_fps = TARGET_STREAM_FPS if TARGET_STREAM_FPS and TARGET_STREAM_FPS > fps else fps

                    # Get stream state for this session
                    state = self._session_stream_state.setdefault(session_id, {
                        'last_index': -1,
                        'data_load_start_time': None,
                        'sync_offset': 0.0,
                        'data_loaded': False,
                        'last_item_id': item_id,
                        'last_position': position_seconds
                    })

                    # Check if we need to load data and track loading time
                    if not state['data_loaded']:
                        if state['data_load_start_time'] is None:
                            # Start loading data and record start time
                            state['data_load_start_time'] = time.time()
                            logger.info(f"🔄 Loading UDP data for {item_id}...")

                        # Try to get frame to trigger data loading
                        base = self.storage.get_udp_packet_by_index(item_id, 0)
                        if base is not None:
                            # Data is now loaded, calculate sync offset
                            load_time = time.time() - state['data_load_start_time']
                            state['sync_offset'] = load_time
                            state['data_loaded'] = True
                            logger.info(f"✅ UDP data loaded in {load_time:.2f}s - sync offset applied")
                        else:
                            # Still loading, skip this frame
                            continue

                    # Apply sync offset to compensate for loading delay
                    adjusted_position = position_seconds - state['sync_offset']
                    if adjusted_position < 0:
                        adjusted_position = 0.0

                    target_index = int(adjusted_position * fps)

                    # Send only if we haven't sent this index yet (or on seeks)
                    if target_index != state['last_index']:
                        # Get binary frame data for current timestamp
                        frame_data = self.get_binary_frame_for_playback(item_id, adjusted_position)
                        if frame_data:
                            # Send raw frame data to WLED
                            self.send_raw_frame_to_wled(frame_data, wled_host, wled_port)
                            state['last_index'] = target_index
                            state['last_position'] = position_seconds
                        else:
                            # If data not ready, skip this frame
                            pass
                # Sleep using effective fps for steady cadence
                eff = TARGET_STREAM_FPS if TARGET_STREAM_FPS and TARGET_STREAM_FPS > 0 else STREAM_FPS
                time.sleep(1.0 / eff)
            except Exception as e:
                logger.error(f"Streaming loop error: {e}")
                time.sleep(0.1)

    def _apply_color_filter(self, raw: bytes) -> bytes:
        """Reduce white tint in dark scenes and boost saturation slightly."""
        data = bytearray(raw)
        thr = DARK_BRIGHTNESS_THRESHOLD
        boost = SATURATION_BOOST
        for i in range(0, len(data), 3):
            r = data[i]
            g = data[i+1]
            b = data[i+2]
            m = (r + g + b) / 3.0
            if m < thr:
                data[i] = 0
                data[i+1] = 0
                data[i+2] = 0
            else:
                data[i] = max(0, min(255, int(m + (r - m) * boost)))
                data[i+1] = max(0, min(255, int(m + (g - m) * boost)))
                data[i+2] = max(0, min(255, int(m + (b - m) * boost)))
        return bytes(data)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"📡 Received signal {signum}")
    shutdown_event.set()

def main():
    """Main entry point"""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("📁 FILE-BASED AMBILIGHT DAEMON")
    print("=" * 50)
    print("🎯 Advantages:")
    print("   📁 No database - just files!")
    print("   🚀 12x faster item operations")
    print("   📦 Direct UDP packet storage")
    print("   🔧 Simple directory structure")
    print("   💾 Better storage efficiency")
    print("   🛠️  Easy debugging and backup")
    print("=" * 50)
    print()

    # Start the file-based daemon
    daemon = FileBasedAmbilightDaemon()
    daemon.start()

if __name__ == "__main__":
    main()
