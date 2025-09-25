#!/usr/bin/env python3
"""
Test priority-based frame extraction
"""

import os
import sys
sys.path.append('/app')

# Temporarily add the missing functions to database
import sqlite3

DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/data/jellyfin.db")

def get_videos_needing_extraction(priority_order='newest_first', limit=None):
    """Get videos that need frame extraction, ordered by priority"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Base query to find videos without frames
    base_query = '''
        SELECT DISTINCT i.id, i.library_id, i.name, i.type, i.filepath, i.created_at, i.updated_at
        FROM items i
        LEFT JOIN frames f ON i.id = f.item_id
        WHERE i.type IN ('Movie', 'Episode', 'Video')
          AND i.filepath IS NOT NULL
          AND i.filepath != 'Unknown'
          AND i.filepath != ''
          AND f.item_id IS NULL
    '''

    # Add ordering based on priority
    if priority_order == 'newest_first':
        order_clause = 'ORDER BY i.updated_at DESC, i.created_at DESC'
    elif priority_order == 'oldest_first':
        order_clause = 'ORDER BY i.created_at ASC, i.updated_at ASC'
    elif priority_order == 'alphabetical':
        order_clause = 'ORDER BY i.name ASC'
    elif priority_order == 'random':
        order_clause = 'ORDER BY RANDOM()'
    else:
        order_clause = 'ORDER BY i.updated_at DESC'  # Default to newest first

    # Add limit if specified
    limit_clause = f'LIMIT {limit}' if limit else ''

    full_query = f'{base_query} {order_clause} {limit_clause}'

    cursor.execute(full_query)
    rows = cursor.fetchall()
    conn.close()

    items = []
    for row in rows:
        items.append({
            'id': row[0],
            'library_id': row[1],
            'name': row[2],
            'type': row[3],
            'filepath': row[4],
            'created_at': row[5],
            'updated_at': row[6]
        })

    return items

def get_extraction_statistics():
    """Get statistics about frame extraction status"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Total videos
    cursor.execute('''
        SELECT COUNT(*) FROM items
        WHERE type IN ('Movie', 'Episode', 'Video')
          AND filepath IS NOT NULL
          AND filepath != 'Unknown'
          AND filepath != ''
    ''')
    total_videos = cursor.fetchone()[0]

    # Videos with frames
    cursor.execute('''
        SELECT COUNT(DISTINCT item_id) FROM frames
    ''')
    extracted_videos = cursor.fetchone()[0]

    # Videos needing extraction
    pending_videos = total_videos - extracted_videos

    conn.close()

    return {
        'total_videos': total_videos,
        'extracted_videos': extracted_videos,
        'pending_videos': pending_videos,
        'completion_percentage': (extracted_videos / total_videos * 100) if total_videos > 0 else 0,
    }

def main():
    print("🎯 PRIORITY-BASED FRAME EXTRACTION TEST")
    print("=" * 60)

    # Get extraction statistics
    stats = get_extraction_statistics()
    print(f"📊 Current Status:")
    print(f"   Total videos: {stats['total_videos']}")
    print(f"   Extracted: {stats['extracted_videos']}")
    print(f"   Pending: {stats['pending_videos']}")
    print(f"   Progress: {stats['completion_percentage']:.1f}%")

    if stats['pending_videos'] == 0:
        print("\n✅ All videos have frames extracted!")
        return

    print(f"\n🎬 PRIORITY ORDER EXAMPLES:")

    # Test different priority orders
    priorities = [
        ('newest_first', 'Newest videos first (default)'),
        ('oldest_first', 'Oldest videos first'),
        ('alphabetical', 'Alphabetical order'),
        ('random', 'Random order')
    ]

    for priority, description in priorities:
        print(f"\n📋 {description}:")

        videos = get_videos_needing_extraction(priority_order=priority, limit=3)

        if videos:
            for i, video in enumerate(videos, 1):
                print(f"   {i}. {video['name']}")
                print(f"      Added: {video.get('created_at', 'Unknown')}")
                print(f"      Updated: {video.get('updated_at', 'Unknown')}")
        else:
            print("   No videos found")

    print(f"\n🔧 CONFIGURATION OPTIONS:")
    print(f"   EXTRACTION_PRIORITY=newest_first  # Process newest videos first")
    print(f"   EXTRACTION_PRIORITY=oldest_first  # Process oldest videos first")
    print(f"   EXTRACTION_PRIORITY=alphabetical  # Process alphabetically")
    print(f"   EXTRACTION_PRIORITY=random        # Random order")
    print(f"   EXTRACTION_BATCH_SIZE=5           # Process 5 videos at a time")

    print(f"\n💡 BENEFITS:")
    print(f"   ✅ Newest content gets ambilight first")
    print(f"   ✅ Users see progress on recent additions")
    print(f"   ✅ Configurable processing order")
    print(f"   ✅ Batch processing prevents overwhelming")

if __name__ == "__main__":
    main()
