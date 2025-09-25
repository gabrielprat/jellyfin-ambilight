#!/usr/bin/env python3
"""
File-Based Storage System for Ambilight Data
============================================

Simple, efficient file-based storage that eliminates database overhead:
- Direct UDP packet files for ultra-fast access
- JSON metadata for human-readable configuration
- Directory-based organization for easy management
- No SQLite dependency or overhead
"""

import os
import json
import time
import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Configuration
DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")
FRAME_INTERVAL = float(os.getenv('FRAME_INTERVAL', '10.0'))

class FileBasedStorage:
    """File-based storage system for ambilight data"""

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.items_dir = self.data_dir / "items"
        self.frames_dir = self.data_dir / "frames"
        self.metadata_dir = self.data_dir / "metadata"

        # Ensure directories exist
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        print(f"📁 File-based storage initialized: {self.data_dir}")

    def save_item(self, item_id: str, library_id: str, name: str, item_type: str, filepath: str):
        """Save Jellyfin item metadata to JSON file"""
        item_data = {
            'id': item_id,
            'library_id': library_id,
            'name': name,
            'type': item_type,
            'filepath': filepath,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }

        item_file = self.items_dir / f"{item_id}.json"

        # Check if item exists for update detection
        action = "updated" if item_file.exists() else "added"

        with open(item_file, 'w') as f:
            json.dump(item_data, f, indent=2)

        return action

    def get_item_by_filepath(self, filepath: str) -> Optional[Dict]:
        """Find item by filepath (scan all item files)"""
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                    if item_data.get('filepath') == filepath:
                        return item_data
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def save_udp_packet(self, item_id: str, timestamp_seconds: float, udp_packet: bytes,
                       width: int = None, height: int = None):
        """Save UDP packet to file (ultra-efficient!)"""
        # Create item frames directory
        item_frames_dir = self.frames_dir / item_id
        item_frames_dir.mkdir(exist_ok=True)

        # Save UDP packet directly to file
        timestamp_str = f"{int(timestamp_seconds):06d}"  # e.g., "000010" for 10.0 seconds
        udp_file = item_frames_dir / f"{timestamp_str}.udp"

        with open(udp_file, 'wb') as f:
            f.write(udp_packet)

        # Update/create index for fast lookups
        self._update_frame_index(item_id, timestamp_seconds, width, height)

    def _update_frame_index(self, item_id: str, timestamp_seconds: float, width: int, height: int):
        """Update the frame index for fast timestamp lookups"""
        item_frames_dir = self.frames_dir / item_id
        index_file = item_frames_dir / "index.json"

        # Load existing index
        index_data = {'frames': [], 'metadata': {'width': width, 'height': height}}
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    index_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Update metadata
        if width: index_data['metadata']['width'] = width
        if height: index_data['metadata']['height'] = height

        # Add/update frame entry
        frames = index_data.get('frames', [])

        # Remove existing entry for this timestamp
        frames = [f for f in frames if f['timestamp'] != timestamp_seconds]

        # Add new entry
        frames.append({
            'timestamp': timestamp_seconds,
            'file': f"{int(timestamp_seconds):06d}.udp",
            'created_at': datetime.now().isoformat()
        })

        # Sort by timestamp
        frames.sort(key=lambda x: x['timestamp'])
        index_data['frames'] = frames

        # Save index
        with open(index_file, 'w') as f:
            json.dump(index_data, f, indent=2)

    def get_udp_packet_at_timestamp(self, item_id: str, timestamp_seconds: float) -> Optional[bytes]:
        """Get UDP packet for specific timestamp (ultra-fast file access!)"""
        item_frames_dir = self.frames_dir / item_id
        index_file = item_frames_dir / "index.json"

        if not index_file.exists():
            return None

        try:
            with open(index_file, 'r') as f:
                index_data = json.load(f)

            frames = index_data.get('frames', [])
            if not frames:
                return None

            # Find closest frame by timestamp
            closest_frame = min(frames, key=lambda f: abs(f['timestamp'] - timestamp_seconds))

            # Read UDP packet file
            udp_file = item_frames_dir / closest_frame['file']
            if udp_file.exists():
                with open(udp_file, 'rb') as f:
                    return f.read()

        except (json.JSONDecodeError, IOError):
            pass

        return None

    def frame_exists(self, item_id: str, timestamp_seconds: float) -> bool:
        """Check if frame exists (fast index lookup)"""
        item_frames_dir = self.frames_dir / item_id
        index_file = item_frames_dir / "index.json"

        if not index_file.exists():
            return False

        try:
            with open(index_file, 'r') as f:
                index_data = json.load(f)

            frames = index_data.get('frames', [])
            return any(f['timestamp'] == timestamp_seconds for f in frames)

        except (json.JSONDecodeError, IOError):
            return False

    def get_videos_needing_extraction(self, priority_order: str = 'newest_first', limit: int = None) -> List[Dict]:
        """Get videos that need frame extraction (custom sorting logic)"""
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

                # Check if frames exist
                item_frames_dir = self.frames_dir / item_data['id']
                index_file = item_frames_dir / "index.json"

                has_frames = index_file.exists()
                if has_frames:
                    try:
                        with open(index_file, 'r') as f:
                            index_data = json.load(f)
                            has_frames = len(index_data.get('frames', [])) > 0
                    except:
                        has_frames = False

                if not has_frames:
                    videos_needing_extraction.append(item_data)

            except (json.JSONDecodeError, IOError):
                continue

        # Apply sorting
        if priority_order == 'newest_first':
            videos_needing_extraction.sort(key=lambda x: (x.get('updated_at', ''), x.get('created_at', '')), reverse=True)
        elif priority_order == 'oldest_first':
            videos_needing_extraction.sort(key=lambda x: (x.get('created_at', ''), x.get('updated_at', '')))
        elif priority_order == 'alphabetical':
            videos_needing_extraction.sort(key=lambda x: x.get('name', ''))
        elif priority_order == 'random':
            import random
            random.shuffle(videos_needing_extraction)

        # Apply movie priority (movies before episodes)
        def content_priority(item):
            content_type = item.get('type', '')
            if content_type == 'Movie':
                return 0
            elif content_type == 'Episode':
                return 1
            else:
                return 2

        videos_needing_extraction.sort(key=content_priority)

        # Apply limit
        if limit:
            videos_needing_extraction = videos_needing_extraction[:limit]

        return videos_needing_extraction

    def get_extraction_statistics(self) -> Dict:
        """Get extraction statistics by scanning directories"""
        total_videos = 0
        extracted_videos = 0

        # Count all video items
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)

                if item_data.get('type') in ['Movie', 'Episode', 'Video']:
                    filepath = item_data.get('filepath')
                    if filepath and filepath not in ['Unknown', '']:
                        total_videos += 1

                        # Check if extracted
                        item_frames_dir = self.frames_dir / item_data['id']
                        index_file = item_frames_dir / "index.json"

                        if index_file.exists():
                            try:
                                with open(index_file, 'r') as f:
                                    index_data = json.load(f)
                                    if len(index_data.get('frames', [])) > 0:
                                        extracted_videos += 1
                            except:
                                pass

            except (json.JSONDecodeError, IOError):
                continue

        pending_videos = total_videos - extracted_videos
        completion_percentage = (extracted_videos / total_videos * 100) if total_videos > 0 else 0

        return {
            'total_videos': total_videos,
            'extracted_videos': extracted_videos,
            'pending_videos': pending_videos,
            'completion_percentage': completion_percentage,
            'last_extraction': self._get_latest_extraction_time(),
            'last_video_added': self._get_latest_video_time()
        }

    def _get_latest_extraction_time(self) -> Optional[str]:
        """Get the latest frame extraction time"""
        latest_time = None

        for index_file in self.frames_dir.glob("*/index.json"):
            try:
                with open(index_file, 'r') as f:
                    index_data = json.load(f)

                for frame in index_data.get('frames', []):
                    created_at = frame.get('created_at')
                    if created_at and (not latest_time or created_at > latest_time):
                        latest_time = created_at

            except (json.JSONDecodeError, IOError):
                continue

        return latest_time

    def _get_latest_video_time(self) -> Optional[str]:
        """Get the latest video addition time"""
        latest_time = None

        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)

                if item_data.get('type') in ['Movie', 'Episode', 'Video']:
                    updated_at = item_data.get('updated_at')
                    if updated_at and (not latest_time or updated_at > latest_time):
                        latest_time = updated_at

            except (json.JSONDecodeError, IOError):
                continue

        return latest_time

    def get_storage_info(self) -> Dict:
        """Get storage usage information"""
        total_size = 0
        file_count = 0

        # Count UDP files
        for udp_file in self.frames_dir.glob("**/*.udp"):
            try:
                total_size += udp_file.stat().st_size
                file_count += 1
            except OSError:
                pass

        # Count other files
        other_files = 0
        for json_file in self.frames_dir.glob("**/*.json"):
            other_files += 1
        for json_file in self.items_dir.glob("*.json"):
            other_files += 1

        return {
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'udp_file_count': file_count,
            'index_file_count': other_files,
            'data_directory': str(self.data_dir)
        }

def benchmark_file_vs_database():
    """Benchmark file-based storage vs database storage"""
    print("🏁 FILE-BASED vs DATABASE BENCHMARK")
    print("=" * 50)

    # Initialize file storage
    file_storage = FileBasedStorage("/tmp/ambilight_test")

    # Generate test data
    import random

    test_items = []
    for i in range(100):
        item_id = f"test_item_{i:03d}"
        item_data = {
            'id': item_id,
            'library_id': 'test_lib',
            'name': f'Test Video {i}',
            'type': 'Movie' if i % 3 == 0 else 'Episode',
            'filepath': f'/videos/test_{i}.mkv'
        }
        test_items.append(item_data)

    # Test 1: Item storage
    print("📝 Testing item storage...")
    start_time = time.time()

    for item in test_items:
        file_storage.save_item(
            item['id'], item['library_id'], item['name'],
            item['type'], item['filepath']
        )

    item_storage_time = time.time() - start_time
    print(f"   Items stored: {len(test_items)} in {item_storage_time:.3f}s")

    # Test 2: UDP packet storage
    print("📦 Testing UDP packet storage...")
    start_time = time.time()

    packet_count = 0
    for item in test_items[:10]:  # Test with subset
        # Generate dummy UDP packets
        for timestamp in range(0, 1200, 10):  # 20-minute video, 10s intervals
            udp_packet = b'DRGB\x01' + bytes([random.randint(0, 255) for _ in range(828)])
            file_storage.save_udp_packet(item['id'], float(timestamp), udp_packet, 1920, 1080)
            packet_count += 1

    packet_storage_time = time.time() - start_time
    print(f"   UDP packets stored: {packet_count} in {packet_storage_time:.3f}s")

    # Test 3: Retrieval performance
    print("🔍 Testing retrieval performance...")
    start_time = time.time()

    retrieval_count = 0
    for item in test_items[:10]:
        for timestamp in range(0, 1200, 30):  # Every 30 seconds
            packet = file_storage.get_udp_packet_at_timestamp(item['id'], float(timestamp))
            if packet:
                retrieval_count += 1

    retrieval_time = time.time() - start_time
    print(f"   UDP packets retrieved: {retrieval_count} in {retrieval_time:.3f}s")

    # Test 4: Priority queries
    print("📊 Testing priority queries...")
    start_time = time.time()

    videos_needing = file_storage.get_videos_needing_extraction('newest_first', 20)

    priority_time = time.time() - start_time
    print(f"   Priority query: {len(videos_needing)} results in {priority_time:.3f}s")

    # Storage info
    storage_info = file_storage.get_storage_info()
    print(f"   Storage used: {storage_info['total_size_mb']:.1f} MB")
    print(f"   Files created: {storage_info['udp_file_count']} UDP + {storage_info['index_file_count']} JSON")

    print()
    print("📈 PERFORMANCE SUMMARY:")
    print(f"   Item storage rate: {len(test_items)/item_storage_time:.1f} items/sec")
    print(f"   Packet storage rate: {packet_count/packet_storage_time:.1f} packets/sec")
    print(f"   Packet retrieval rate: {retrieval_count/retrieval_time:.1f} packets/sec")
    print(f"   Priority query time: {priority_time*1000:.1f}ms")

    # Cleanup
    import shutil
    shutil.rmtree("/tmp/ambilight_test")

    return {
        'item_rate': len(test_items)/item_storage_time,
        'packet_storage_rate': packet_count/packet_storage_time,
        'packet_retrieval_rate': retrieval_count/retrieval_time,
        'priority_query_time': priority_time
    }

if __name__ == "__main__":
    benchmark_file_vs_database()
