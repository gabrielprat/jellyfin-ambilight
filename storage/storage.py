#!/usr/bin/env python3
"""
Optimized File-Based Storage System for Ambilight Data
======================================================

Enhanced version with single-file UDP storage for maximum performance:
- Single file per video instead of thousands of small files
- Memory-mapped access for ultra-fast playback
- Reduced disk I/O and filesystem overhead
- Binary format: [timestamp][packet_size][udp_data]...
"""

import os
import json
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Configuration
DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")
FRAME_INTERVAL = float(os.getenv('FRAME_INTERVAL', '0.1'))

class OptimizedFileBasedStorage:
    """
    Optimized file-based storage with single UDP file per video

    File format for {item_id}.udpdata:
    [timestamp:float32][packet_size:uint32][udp_packet:bytes]...

    This reduces file count from 72,000 files to 1 file per 2-hour movie!
    """

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.items_dir = self.data_dir / "items"
        self.udp_dir = self.data_dir / "udp"  # Single UDP file per video
        self.metadata_dir = self.data_dir / "metadata"

        # Memory cache for loaded UDP data
        self._udp_cache: Dict[str, Dict[float, bytes]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._file_metadata: Dict[str, Dict] = {}

        # Ensure directories exist
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.udp_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        print(f"📁 Optimized storage initialized: {self.data_dir}")

    def save_item(self, item_id: str, library_id: str, name: str, item_type: str, filepath: str, jellyfin_date_created: str = None):
        """Save Jellyfin item metadata to JSON file"""
        # check if filepath exists
        if not os.path.exists(filepath):
            # print(f"❌ Filepath does not exist: {filepath}")
            return "skipped"

        item_data = {
            'id': item_id,
            'library_id': library_id,
            'name': name,
            'type': item_type,
            'filepath': filepath,
            'jellyfin_date_created': jellyfin_date_created,  # When item was added to Jellyfin library
            'created_at': datetime.now().isoformat(),        # When we retrieved it via API
            'updated_at': datetime.now().isoformat()         # When we last updated it
        }
        item_file = self.items_dir / f"{item_id}.json"
        action = "updated" if item_file.exists() else "added"

        with open(item_file, 'w') as f:
            json.dump(item_data, f, indent=2)

        return action

    def get_item_by_filepath(self, filepath: str) -> Optional[Dict]:
        """Find item by filepath"""
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                    if item_data.get('filepath') == filepath:
                        return item_data
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def start_udp_session(self, item_id: str) -> 'UDPWriteSession':
        """Start a new UDP writing session for efficient batch writes"""
        return UDPWriteSession(self, item_id)


    def load_udp_data_into_memory(self, item_id: str) -> bool:
        """Load entire UDP file into memory for ultra-fast access"""
        udp_file = self.udp_dir / f"{item_id}.udpdata"

        if not udp_file.exists():
            return False

        try:
            print(f"📥 Loading UDP data into memory: {item_id}")
            udp_data = {}

            with open(udp_file, 'rb') as f:
                file_size = udp_file.stat().st_size
                bytes_read = 0

                # Optional header: 'UDPR' magic + version + metadata
                header_checked = False
                while bytes_read < file_size:
                    # Read timestamp (4 bytes)
                    if not header_checked:
                        peek = f.read(4)
                        if len(peek) < 4:
                            break
                        if peek == b'UDPR':
                            # Header format: 'UDPR'[4] + version u8 + fps f32 + wled_led_count u16 + expected_led_count u16 + protocol u8 + reserved u8
                            version_b = f.read(1)
                            meta = f.read(4 + 2 + 2 + 1 + 1)
                            if len(version_b) == 1 and len(meta) == 10:
                                import struct
                                version = version_b[0]
                                fps, wled_leds, expected_leds, protocol, _ = struct.unpack('<fHHBB', meta)
                                self._file_metadata[item_id] = {
                                    'version': version,
                                    'fps': fps,
                                    'wled_led_count': wled_leds,
                                    'expected_led_count': expected_leds,
                                    'protocol': protocol,
                                }
                                bytes_read += 4 + 1 + 10
                                header_checked = True
                                # Read the first timestamp after header
                                timestamp_bytes = f.read(4)
                                if len(timestamp_bytes) < 4:
                                    break
                            else:
                                # Invalid header; rewind and treat as timestamp
                                f.seek(- (1 + len(meta)), 1)
                                timestamp_bytes = peek
                                header_checked = True
                        else:
                            # No header, treat as timestamp
                            timestamp_bytes = peek
                            header_checked = True
                    else:
                        timestamp_bytes = f.read(4)
                    if len(timestamp_bytes) < 4:
                        break

                    timestamp = struct.unpack('<f', timestamp_bytes)[0]

                    # Read packet size (4 bytes)
                    size_bytes = f.read(4)
                    if len(size_bytes) < 4:
                        break

                    packet_size = struct.unpack('<I', size_bytes)[0]

                    # Read UDP packet
                    udp_packet = f.read(packet_size)
                    if len(udp_packet) < packet_size:
                        break

                    udp_data[timestamp] = udp_packet
                    bytes_read += 8 + packet_size

            # Cache the data
            self._udp_cache[item_id] = udp_data
            self._cache_timestamps[item_id] = time.time()

            print(f"✅ Loaded {len(udp_data):,} UDP packets into memory")
            return True

        except Exception as e:
            print(f"❌ Failed to load UDP data: {e}")
            return False

    def get_udp_packet_at_timestamp(self, item_id: str, timestamp_seconds: float) -> Optional[bytes]:
        """Get UDP packet for specific timestamp (memory-cached ultra-fast!)"""

        # Check if data is in memory cache
        if item_id not in self._udp_cache:
            # Try to load into memory
            if not self.load_udp_data_into_memory(item_id):
                return None

        udp_data = self._udp_cache.get(item_id, {})
        if not udp_data:
            return None

        # Find closest timestamp
        available_timestamps = list(udp_data.keys())
        closest_timestamp = min(available_timestamps,
                               key=lambda t: abs(t - timestamp_seconds))

        return udp_data.get(closest_timestamp)

    def get_file_metadata(self, item_id: str) -> Dict:
        """Return metadata for udpdata file if present (fps, counts, protocol)."""
        # Ensure metadata is loaded
        if item_id not in self._file_metadata:
            self.load_udp_data_into_memory(item_id)
        return self._file_metadata.get(item_id, {})

    def frame_exists(self, item_id: str, timestamp_seconds: float) -> bool:
        """Check if frame exists for timestamp"""
        udp_file = self.udp_dir / f"{item_id}.udpdata"

        if not udp_file.exists():
            return False

        # If in memory cache, check there
        if item_id in self._udp_cache:
            return any(abs(t - timestamp_seconds) < 0.01
                      for t in self._udp_cache[item_id].keys())

        # For existence check, we can check file metadata
        metadata_file = self.metadata_dir / f"{item_id}.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    timestamps = metadata.get('timestamps', [])
                    return any(abs(t - timestamp_seconds) < 0.01 for t in timestamps)
            except:
                pass

        return False

    def get_videos_needing_extraction(self, priority_order: str = 'newest_first', limit: int = None) -> List[Dict]:
        """Get videos that need frame extraction"""
        print("Getting videos needing extraction...")
        videos_needing_extraction = []

        # Scan all items
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)

                # Filter video types
                if item_data.get('type') not in ['Movie', 'Episode', 'Video']:
                    continue

                filepath = item_data.get('filepath')
                if not filepath or filepath in ['Unknown', '']:
                    continue

                # Skip if video file doesn't exist (no data creation, just ignore)
                if not os.path.exists(filepath):
                    continue  # Simply skip missing files completely

                # Check if UDP data exists
                udp_file = self.udp_dir / f"{item_data['id']}.udpdata"
                if not udp_file.exists():
                    videos_needing_extraction.append(item_data)

            except (json.JSONDecodeError, IOError):
                continue
        # Apply sorting using Jellyfin library dates (when items were actually added to library)
        if priority_order == 'movies_newest_first':
            videos_needing_extraction.sort(key=lambda x: (x.get('type', ''), x.get('jellyfin_date_created', x.get('created_at', ''))), reverse=True)
        if priority_order == 'newest_first':
            videos_needing_extraction.sort(key=lambda x: x.get('jellyfin_date_created', x.get('created_at', '')), reverse=True)
        elif priority_order == 'oldest_first':
            videos_needing_extraction.sort(key=lambda x: x.get('jellyfin_date_created', x.get('created_at', '')))
        elif priority_order == 'alphabetical':
            videos_needing_extraction.sort(key=lambda x: x.get('name', ''))

        # Apply limit
        if limit:
            videos_needing_extraction = videos_needing_extraction[:limit]

        return videos_needing_extraction

    def get_extraction_statistics(self) -> Dict:
        """Get extraction progress statistics"""
        print("Getting extraction statistics...")
        total_videos = 0
        extracted_videos = 0
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                if item_data.get('type') in ['Movie', 'Episode', 'Video']:
                    filepath = item_data.get('filepath')
                    if filepath and filepath not in ['Unknown', ''] and os.path.exists(filepath):
                        total_videos += 1

                        # Check if UDP file exists
                        udp_file = self.udp_dir / f"{item_data['id']}.udpdata"
                        if udp_file.exists():
                            extracted_videos += 1

            except (json.JSONDecodeError, IOError):
                continue

        completion_percentage = (extracted_videos / total_videos * 100) if total_videos > 0 else 0
        pending_videos = total_videos - extracted_videos

        return {
            'total_videos': total_videos,
            'extracted_videos': extracted_videos,
            'pending_videos': pending_videos,
            'completion_percentage': completion_percentage
        }

    def get_storage_info(self) -> Dict:
        """Get storage usage information"""
        total_size = 0
        udp_file_count = 0

        # Count UDP files
        for udp_file in self.udp_dir.glob("*.udpdata"):
            try:
                total_size += udp_file.stat().st_size
                udp_file_count += 1
            except OSError:
                pass

        # Count other files
        other_files = 0
        for json_file in self.metadata_dir.glob("*.json"):
            other_files += 1
        for json_file in self.items_dir.glob("*.json"):
            other_files += 1

        return {
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'udp_file_count': udp_file_count,
            'index_file_count': other_files,
            'data_directory': str(self.data_dir)
        }

    def clear_memory_cache(self, item_id: str = None):
        """Clear memory cache for specific item or all items"""
        if item_id:
            self._udp_cache.pop(item_id, None)
            self._cache_timestamps.pop(item_id, None)
        else:
            self._udp_cache.clear()
            self._cache_timestamps.clear()


    def save_udp_packet(self, item_id: str, timestamp_seconds: float, udp_packet: bytes,
                       width: int = None, height: int = None):
        """Backward compatibility method for current extractors with memory buffering"""
        # Buffer packets in memory for efficient writing
        if not hasattr(self, '_temp_sessions'):
            self._temp_sessions = {}

        if item_id not in self._temp_sessions:
            self._temp_sessions[item_id] = []

        self._temp_sessions[item_id].append((timestamp_seconds, udp_packet))

        # Only show progress occasionally to avoid spam
        packet_count = len(self._temp_sessions[item_id])
        if packet_count % 1000 == 0:  # Every 1000 packets
            print(f"📦 Buffered {packet_count:,} packets in memory for {item_id}")

        # For very large extractions, we might want to flush periodically
        # But keep the buffer size large for optimal performance
        if packet_count >= 10000:  # Flush every 10,000 packets (~8MB)
            print(f"📦 Auto-flushing large buffer ({packet_count:,} packets)")
            self._flush_temp_session(item_id)

    def _flush_temp_session(self, item_id: str):
        """Flush temporary session to optimized file"""
        if item_id not in self._temp_sessions:
            return

        packets = self._temp_sessions[item_id]

        # Write all packets to optimized file
        with self.start_udp_session(item_id) as session:
            for timestamp, udp_packet in packets:
                session.add_frame(timestamp, udp_packet)

        # Clear temporary session
        del self._temp_sessions[item_id]

    def finalize_extraction(self, item_id: str):
        """Finalize extraction by flushing any remaining packets"""
        if hasattr(self, '_temp_sessions') and item_id in self._temp_sessions:
            self._flush_temp_session(item_id)


class UDPWriteSession:
    """Context manager for efficient UDP data writing with memory buffering"""

    def __init__(self, storage: OptimizedFileBasedStorage, item_id: str):
        self.storage = storage
        self.item_id = item_id
        self.udp_file = storage.udp_dir / f"{item_id}.udpdata"
        self.metadata_file = storage.metadata_dir / f"{item_id}.json"
        self.memory_buffer = bytearray()  # Buffer all data in memory
        self.timestamps = []

    def __enter__(self):
        # Initialize memory buffer - no file I/O yet
        self.memory_buffer = bytearray()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Write entire buffer to file in one operation
        if self.memory_buffer:
            print(f"💾 Writing {len(self.memory_buffer):,} bytes to {self.udp_file.name}...")
            with open(self.udp_file, 'wb') as f:
                f.write(self.memory_buffer)
            print(f"✅ Single write operation completed!")

        # Save metadata with timestamps
        metadata = {
            'item_id': self.item_id,
            'timestamps': self.timestamps,
            'frame_count': len(self.timestamps),
            'created_at': datetime.now().isoformat(),
            'file_size_bytes': len(self.memory_buffer)
        }

        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    def add_frame(self, timestamp: float, udp_packet: bytes):
        """Add a frame to the memory buffer"""
        # Write to memory buffer instead of file
        self._write_udp_entry_to_buffer(timestamp, udp_packet)
        self.timestamps.append(timestamp)

    def write_header(self, header_bytes: bytes):
        """Write a binary header at the start of the file buffer (use before frames)."""
        if self.memory_buffer:
            # Header must be written before any frames
            return
        self.memory_buffer.extend(header_bytes)

    def _write_udp_entry_to_buffer(self, timestamp: float, udp_packet: bytes):
        """Write single UDP entry to memory buffer in binary format"""
        # Format: [timestamp:float32][packet_size:uint32][udp_packet:bytes]
        self.memory_buffer.extend(struct.pack('<f', timestamp))  # 4 bytes - timestamp
        self.memory_buffer.extend(struct.pack('<I', len(udp_packet)))  # 4 bytes - packet size
        self.memory_buffer.extend(udp_packet)  # variable bytes - UDP packet


# For backward compatibility, create an alias
FileBasedStorage = OptimizedFileBasedStorage
