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
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Configuration
DATA_DIR = os.getenv("AMBILIGHT_DATA_DIR", "/app/data/ambilight")

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
        self.binaries_dir = self.data_dir / "binaries"

        # Ensure directories exist (only active ones)
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.binaries_dir.mkdir(parents=True, exist_ok=True)

        print(f"📁 Optimized storage initialized: {self.data_dir}")

    def save_item(self, item_id: str, library_id: str, name: str, item_type: str, filepath: str, jellyfin_date_created: str = None, kind: Optional[str] = None, season: Optional[int] = None, episode: Optional[int] = None):
        """Save Jellyfin item metadata to JSON file"""
        # check if filepath exists
        if not os.path.exists(filepath):
            # print(f"❌ Filepath does not exist: {filepath}")
            return "skipped"

        # Prefer explicit kind if provided, otherwise derive from Jellyfin type
        derived_kind = kind or ("Serie" if (item_type or "").lower() in ("episode", "series", "season") else ("Movie" if (item_type or "").lower() == "movie" else (item_type or "Video")))

        item_file = self.items_dir / f"{item_id}.json"
        existing = {}
        if item_file.exists():
            try:
                with open(item_file, 'r') as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = {}

        # Preserve certain fields if already present
        created_at = existing.get('created_at') or datetime.now().isoformat()
        extraction_status = existing.get('extraction_status', 'pending')
        extraction_error = existing.get('extraction_error')
        extraction_attempts = existing.get('extraction_attempts', 0)

        # Merge/overwrite with new info
        item_data = {
            'id': item_id,
            'library_id': library_id,
            'name': name,
            'type': item_type,
            'kind': derived_kind,
            'season': season if season is not None else existing.get('season'),
            'episode': episode if episode is not None else existing.get('episode'),
            'filepath': filepath,
            'jellyfin_date_created': jellyfin_date_created or existing.get('jellyfin_date_created'),
            'created_at': created_at,
            'updated_at': datetime.now().isoformat(),
            'extraction_status': extraction_status,
            'extraction_error': extraction_error,
            'extraction_attempts': extraction_attempts
        }

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

    # Legacy UDP APIs removed

    def mark_extraction_failed(self, item_id: str, error_message: str):
        """Mark an item as failed extraction to prevent retry"""
        item_file = self.items_dir / f"{item_id}.json"
        if not item_file.exists():
            return

        try:
            with open(item_file, 'r') as f:
                item_data = json.load(f)

            item_data['extraction_status'] = 'failed'
            item_data['extraction_error'] = error_message
            item_data['extraction_attempts'] = item_data.get('extraction_attempts', 0) + 1
            item_data['updated_at'] = datetime.now().isoformat()

            with open(item_file, 'w') as f:
                json.dump(item_data, f, indent=2)

            print(f"❌ Marked {item_data.get('name', item_id)} as failed: {error_message}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"❌ Failed to mark {item_id} as failed: {e}")

    def mark_extraction_completed(self, item_id: str):
        """Mark an item as successfully extracted"""
        item_file = self.items_dir / f"{item_id}.json"
        if not item_file.exists():
            return

        try:
            with open(item_file, 'r') as f:
                item_data = json.load(f)

            item_data['extraction_status'] = 'completed'
            item_data['extraction_error'] = None
            item_data['updated_at'] = datetime.now().isoformat()

            with open(item_file, 'w') as f:
                json.dump(item_data, f, indent=2)
        except (json.JSONDecodeError, IOError) as e:
            print(f"❌ Failed to mark {item_id} as completed: {e}")

    def get_videos_needing_extraction(self, priority_order: str = 'newest_first', limit: int = None) -> List[Dict]:
        """Get videos that need frame extraction (excluding failed ones)"""
        print("Getting videos needing extraction...")
        videos_needing_extraction = []

        # Get age filtering configuration
        extraction_max_age_days = float(os.getenv("EXTRACTION_MAX_AGE_DAYS", "0"))
        current_time = time.time()

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

                # Skip if extraction has already failed
                if item_data.get('extraction_status') == 'failed':
                    continue

                # Age filtering: Skip videos older than EXTRACTION_MAX_AGE_DAYS
                if extraction_max_age_days > 0:
                    jellyfin_date_created = item_data.get('jellyfin_date_created')
                    if jellyfin_date_created:
                        try:
                            # Parse the date string (assuming ISO format)
                            if 'T' in jellyfin_date_created:
                                # ISO format with time
                                created_dt = datetime.fromisoformat(jellyfin_date_created.replace('Z', '+00:00'))
                            else:
                                # Date only format
                                created_dt = datetime.fromisoformat(jellyfin_date_created)

                            # Convert to timestamp and calculate age
                            created_timestamp = created_dt.timestamp()
                            age_days = (current_time - created_timestamp) / (24 * 3600)

                            if age_days > extraction_max_age_days:
                                print(f"⏰ Skipping {item_data.get('name', 'Unknown')} - too old ({age_days:.1f} days > {extraction_max_age_days} days)")
                                continue
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ Could not parse date for {item_data.get('name', 'Unknown')}: {jellyfin_date_created} - {e}")
                            # Continue processing if date parsing fails

                # Check if binary exists
                bin_file = self.binaries_dir / f"{item_data['id']}.bin"
                if not bin_file.exists():
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
        failed_videos = 0
        for item_file in self.items_dir.glob("*.json"):
            try:
                with open(item_file, 'r') as f:
                    item_data = json.load(f)
                if item_data.get('type') in ['Movie', 'Episode', 'Video']:
                    filepath = item_data.get('filepath')
                    if filepath and filepath not in ['Unknown', ''] and os.path.exists(filepath):
                        total_videos += 1

                        # Check extraction status
                        extraction_status = item_data.get('extraction_status', 'pending')
                        if extraction_status == 'failed':
                            failed_videos += 1
                        else:
                            # Check if binary exists
                            bin_file = self.binaries_dir / f"{item_data['id']}.bin"
                            if bin_file.exists():
                                extracted_videos += 1

            except (json.JSONDecodeError, IOError):
                continue

        completion_percentage = (extracted_videos / total_videos * 100) if total_videos > 0 else 0
        pending_videos = total_videos - extracted_videos - failed_videos

        return {
            'total_videos': total_videos,
            'extracted_videos': extracted_videos,
            'failed_videos': failed_videos,
            'pending_videos': pending_videos,
            'completion_percentage': completion_percentage
        }

    def get_storage_info(self) -> Dict:
        """Get storage usage information"""
        total_size = 0
        bin_file_count = 0

        # Count binary files
        for bin_file in self.binaries_dir.glob("*.bin"):
            try:
                total_size += bin_file.stat().st_size
                bin_file_count += 1
            except OSError:
                pass

        # Count other files
        other_files = 0
        # metadata dir deprecated
        for json_file in self.items_dir.glob("*.json"):
            other_files += 1

        return {
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'binary_file_count': bin_file_count,
            'index_file_count': other_files,
            'data_directory': str(self.data_dir)
        }

    # For backward compatibility, create an alias
FileBasedStorage = OptimizedFileBasedStorage
