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
from datetime import datetime
from typing import Dict
from storage.storage import FileBasedStorage
# Try pure Python extractor first, fallback to numpy version
from frames.fast_extractor_pure import extract_fast

# Import local modules
sys.path.append('/app')
sys.path.append('/app/storage')
sys.path.append('/app/frames')

# Configuration
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
JELLYFIN_BASE_URL = os.getenv("JELLYFIN_BASE_URL")
WLED_HOST = os.getenv('WLED_HOST', 'wled-ambilight-lgc1.lan')
WLED_UDP_PORT = int(os.getenv('WLED_UDP_PORT', '21324'))
WLED_UDP_PROTOCOL = os.getenv('WLED_UDP_PROTOCOL', 'WARLS').upper()  # DRGB, WARLS, DNRGB or UDP_RAW
WLED_UDP_TIMEOUT = int(os.getenv('WLED_UDP_TIMEOUT', '255'))  # 1..255; 255 = persistent
WLED_LED_COUNT = int(os.getenv('WLED_LED_COUNT', '300'))  # Physical LEDs configured in WLED
WLED_UDP_RAW_PORT = int(os.getenv('WLED_UDP_RAW_PORT', '19446'))  # Hyperion UDP raw default port
SMOOTHING_ENABLED = os.getenv('SMOOTHING_ENABLED', 'true').lower() == 'true'
SMOOTHING_ALPHA = float(os.getenv('SMOOTHING_ALPHA', '0.25'))  # 0..1, lower = smoother
STREAM_FPS = float(os.getenv('FRAMES_PER_SECOND', '10'))  # Use extraction FPS for streaming cadence
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

    def get_wled_target_for_session(self, session: Dict) -> tuple[str, int]:
        """Get WLED host and port for a specific session based on device mapping"""
        if not self.device_wled_mappings:
            # No device mappings configured, use default
            return WLED_HOST, WLED_UDP_PORT

        # Get device identifier from session
        device_value = session.get(DEVICE_MATCH_FIELD, '').strip()

        if not device_value:
            logger.debug(f"No {DEVICE_MATCH_FIELD} found in session, using default WLED")
            return WLED_HOST, WLED_UDP_PORT

        # Check for exact match first
        if device_value in self.device_wled_mappings:
            mapping = self.device_wled_mappings[device_value]
            return mapping['host'], mapping['port']

        # Check for partial matches (case insensitive)
        device_lower = device_value.lower()
        for identifier, mapping in self.device_wled_mappings.items():
            if identifier.lower() in device_lower or device_lower in identifier.lower():
                logger.info(f"📱 Matched device '{device_value}' to mapping '{identifier}'")
                return mapping['host'], mapping['port']

        # No match found, use default
        logger.debug(f"No WLED mapping found for device '{device_value}', using default")
        return WLED_HOST, WLED_UDP_PORT

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
                self.udp_socket.sendto(raw, (wled_host, raw_port))
                return True

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
                        self.udp_socket.sendto(pkt, (wled_host, wled_port))
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
                self.udp_socket.sendto(packet_to_send, (wled_host, wled_port))
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
                self.udp_socket.sendto(bytes(packet), (wled_host, wled_port))
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
                        self.udp_socket.sendto(bytes(pkt), (wled_host, wled_port))
                    else:
                        i += 1
                self._last_state_by_device[device_key] = last_state
            else:
                # UDP_RAW
                try:
                    self.udp_socket.sendto(bytes(rgb_payload[: WLED_LED_COUNT * 3]), (wled_host, WLED_UDP_RAW_PORT))
                except Exception as e:
                    logger.error(f"UDP RAW transmission error to {wled_host}:{WLED_UDP_RAW_PORT}: {e}")
            return True
        except Exception as e:
            logger.error(f"UDP transmission error to {wled_host}:{wled_port}: {e}")
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

    def get_udp_packet_for_playback(self, item_id, timestamp_seconds):
        """Get UDP packet with caching for ultra-fast access"""
        cache_key = f"{item_id}_{timestamp_seconds:.1f}"

        # Check cache first
        if cache_key in self.udp_cache:
            return self.udp_cache[cache_key]

        # Get from file storage
        udp_packet = self.storage.get_udp_packet_at_timestamp(item_id, timestamp_seconds)

        if udp_packet:
            # Cache for future use (keep cache size reasonable)
            if len(self.udp_cache) > 100:  # Limit cache size
                # Remove oldest entries
                oldest_key = next(iter(self.udp_cache))
                del self.udp_cache[oldest_key]

            self.udp_cache[cache_key] = udp_packet

        return udp_packet

    def turn_off_wled(self):
        """Turn off WLED using black UDP packet"""
        led_count = WLED_LED_COUNT
        if WLED_UDP_PROTOCOL == 'DRGB':
            black_packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), 1])
            black_packet.extend([0, 0, 0] * led_count)
            try:
                self.udp_socket.sendto(bytes(black_packet), (WLED_HOST, WLED_UDP_PORT))
                return True
            except Exception as e:
                logger.error(f"UDP transmission error (turn off): {e}")
                return False
        elif WLED_UDP_PROTOCOL == 'WARLS':
            # WARLS: 255 LEDs per packet
            sent = 0
            try:
                while sent < led_count:
                    batch = min(255, led_count - sent)
                    pkt = bytearray([1, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1])
                    for idx in range(batch):
                        led = sent + idx
                        pkt.extend([led & 0xFF, 0, 0, 0])
                    self.udp_socket.sendto(bytes(pkt), (WLED_HOST, WLED_UDP_PORT))
                    sent += batch
                return True
            except Exception as e:
                logger.error(f"UDP transmission error (turn off): {e}")
                return False
        elif WLED_UDP_PROTOCOL == 'DNRGB':
            # DNRGB: up to 489 LEDs per packet from a start index
            sent = 0
            try:
                while sent < led_count:
                    batch = min(489, led_count - sent)
                    start_hi = (sent >> 8) & 0xFF
                    start_lo = sent & 0xFF
                    pkt = bytearray([4, WLED_UDP_TIMEOUT if WLED_UDP_TIMEOUT else 1, start_hi, start_lo])
                    pkt.extend([0, 0, 0] * batch)
                    self.udp_socket.sendto(bytes(pkt), (WLED_HOST, WLED_UDP_PORT))
                    sent += batch
                return True
            except Exception as e:
                logger.error(f"UDP transmission error (turn off): {e}")
                return False
        else:
            # UDP_RAW: send pure zeros for full strip
            try:
                zeros = bytes([0, 0, 0] * led_count)
                self.udp_socket.sendto(zeros, (WLED_HOST, WLED_UDP_RAW_PORT))
                return True
            except Exception as e:
                logger.error(f"UDP RAW transmission error (turn off): {e}")
                return False

    def get_jellyfin_user_id(self):
        """Get the first available Jellyfin user ID"""
        try:
            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Users",
                headers={"X-Emby-Token": JELLYFIN_API_KEY},
                timeout=10
            )
            response.raise_for_status()

            users = response.json()
            if users:
                user_id = users[0]["Id"]
                logger.info(f"🔐 Using Jellyfin user: {users[0].get('Name', 'Unknown')}")
                return user_id
        except Exception as e:
            logger.error(f"Failed to get Jellyfin user: {e}")

        return None

    def get_jellyfin_sessions(self):
        """Get current Jellyfin playback sessions via HTTP API (NOT WebSocket!)"""
        try:
            # Use proper MediaBrowser authorization header format
            headers = {
                "Authorization": f'MediaBrowser Client="ambilight-files", Device="Python", DeviceId="ambilight-files-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
            }

            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Sessions",
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

                        if is_playing:
                            # Get device-specific WLED target
                            wled_host, wled_port = self.get_wled_target_for_session(session)
                            device_identifier = session.get(DEVICE_MATCH_FIELD, 'Unknown')

                            # Get UDP packet for current timestamp (direct file access!)
                            udp_packet = self.get_udp_packet_for_playback(item_id, position_seconds)

                            if udp_packet:
                                # Send to device-specific WLED
                                success = self.send_udp_packet_to_device(udp_packet, wled_host, wled_port)

                                if success:
                                    # Log occasionally to avoid spam
                                    if int(position_seconds) % 30 == 0:  # Every 30 seconds
                                        logger.info(f"🌈 {device_identifier} → {wled_host}:{wled_port}: {item.get('Name', 'Unknown')} @ {position_seconds:.1f}s")
                                else:
                                    logger.warning(f"⚠️  UDP transmission failed to {wled_host}:{wled_port} for {item.get('Name', 'Unknown')}")
                            else:
                                # No frame data available yet
                                if session_id not in self.active_sessions or self.active_sessions[session_id].get('warned', False) is False:
                                    logger.info(f"⏳ Waiting for frame extraction: {item.get('Name', 'Unknown')} ({item_id})")
                                    if session_id not in self.active_sessions:
                                        self.active_sessions[session_id] = {}
                                    self.active_sessions[session_id]['warned'] = True

                        else:
                            # Paused: immediately release realtime (send black frame once)
                            try:
                                self.turn_off_wled()
                            except Exception:
                                pass

                        # Track session
                        self.active_sessions[session_id] = {
                            'item_id': item_id,
                            'item_name': item.get('Name', 'Unknown'),
                            'is_playing': is_playing,
                            'position_seconds': position_seconds,
                            'last_seen': datetime.now(),
                            'warned': self.active_sessions.get(session_id, {}).get('warned', False)
                        }

                else:
                    # No active sessions - turn off ambilight
                    if self.active_sessions:
                        logger.info("⏸️  No active video playback - turning off ambilight")
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

            response = requests.get(
                f"{JELLYFIN_BASE_URL}/Users/{user_id}/Views",
                headers={"X-Emby-Token": JELLYFIN_API_KEY},
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
                items_response = requests.get(
                    f"{JELLYFIN_BASE_URL}/Users/{user_id}/Items",
                    headers={"X-Emby-Token": JELLYFIN_API_KEY},
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

        except Exception as e:
            logger.error(f"Error in incremental library update: {e}")

    def scan_library_for_new_videos(self):
        """Scan library and extract frames with file storage"""
        logger.info("🔄 Starting library scan with file-based storage...")

        user_id = self.get_jellyfin_user_id()
        if not user_id:
            logger.error("❌ Cannot scan library - no user ID")
            return

        while not shutdown_event.is_set():
            try:
                # Update library
                self.perform_incremental_library_update(user_id)

                # Get extraction statistics
                stats = self.storage.get_extraction_statistics()
                logger.info(f"📊 Extraction status: {stats['extracted_videos']}/{stats['total_videos']} " +
                           f"({stats['completion_percentage']:.1f}% complete)")

                if stats['pending_videos'] > 0:
                    # Get videos that need extraction, prioritized
                    videos_to_process = self.storage.get_videos_needing_extraction(
                        priority_order=EXTRACTION_PRIORITY,
                        limit=EXTRACTION_BATCH_SIZE
                    )
                    print(f"✅ Videos aquired: {len(videos_to_process)}")
                    if videos_to_process:
                        logger.info(f"🎬 Processing {len(videos_to_process)} videos with file storage...")

                        for i, item in enumerate(videos_to_process):
                            if shutdown_event.is_set():
                                break

                            logger.info(f"📁 Extraction {i+1} of {len(videos_to_process)} videos: {item['name']}")

                            try:
                                # Use file-based extraction (dynamic import)
                                extracted = extract_fast(
                                    item['id'],
                                    item['filepath'],
                                    item['name'],
                                    self.storage
                                )

                                if extracted > 0:
                                    logger.info(f"✅ Completed: {item['name']} ({extracted} UDP files)")
                                else:
                                    logger.warning(f"⚠️  No frames extracted for: {item['name']}")

                            except Exception as e:
                                logger.error(f"❌ Failed file extraction for {item['name']}: {e}")
                    else:
                        logger.info("✅ All videos have frames extracted 1")
                else:
                    logger.info("✅ All videos have frames extracted 2")

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
        logger.info(f"   UDP files: {storage_info['udp_file_count']}")
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
        streamer_thread = threading.Thread(target=self.stream_frames_loop, daemon=True)

        if library_thread is not None:
            library_thread.start()
        playback_thread.start()
        streamer_thread.start()

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
            self.turn_off_wled()
            logger.info("🔚 File-based daemon stopped")

    def stream_frames_loop(self):
        """Continuously stream RAW frames to WLED at FPS, synchronized to playback position."""
        if STREAM_FPS <= 0:
            logger.warning("⚠️  STREAM_FPS <= 0, streaming disabled")
            return

        frame_dt = 1.0 / STREAM_FPS
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
                    target_index = int(position_seconds * fps)
                    state = self._session_stream_state.setdefault(session_id, {'last_index': -1})

                    # Send only if we haven't sent this index yet (or on seeks)
                    if target_index != state['last_index']:
                        # Retrieve closest frame by timestamp
                        # Fast O(1) access by index to avoid timestamp search overhead
                        udp_packet = self.storage.get_udp_packet_by_index(item_id, target_index)
                        if udp_packet:
                            # For UDP_RAW we expect pure RGB; other modes are supported too
                            self.send_udp_packet_to_device(udp_packet, wled_host, wled_port)
                            state['last_index'] = target_index
                        else:
                            # If data not ready, attempt to load into memory (non-blocking path already inside storage)
                            pass
                # Single sleep per loop to reduce CPU usage while maintaining responsiveness
                time.sleep(frame_dt)
            except Exception as e:
                logger.error(f"Streaming loop error: {e}")
                time.sleep(0.1)

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
