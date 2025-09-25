import sqlite3
import os
import json
from datetime import datetime

DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/data/jellyfin.db")

def init_database():
    """Initialize the SQLite database with required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Create libraries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS libraries (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            library_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT,
            filepath TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (library_id) REFERENCES libraries (id)
        )
    ''')

    # Create sessions table for tracking play events
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            item_id TEXT,
            client TEXT,
            state TEXT,
            position_seconds REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items (id)
        )
    ''')

    # Create metadata table for storing scan timestamps
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create frames table for storing extracted frames
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            timestamp_seconds REAL NOT NULL,
            frame_path TEXT,
            width INTEGER,
            height INTEGER,
            led_colors TEXT,
            udp_packet BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items (id),
            UNIQUE(item_id, timestamp_seconds)
        )
    ''')

    # Create efficient index for timestamp-based lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_frames_item_timestamp
        ON frames (item_id, timestamp_seconds)
    ''')

    conn.commit()
    conn.close()

def save_library(library_id, library_name):
    """Save or update a library"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO libraries (id, name, updated_at)
        VALUES (?, ?, ?)
    ''', (library_id, library_name, datetime.now()))

    conn.commit()
    conn.close()

def save_item(item_id, library_id, name, item_type, filepath):
    """Save or update an item"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO items (id, library_id, name, type, filepath, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (item_id, library_id, name, item_type, filepath, datetime.now()))

    conn.commit()
    conn.close()

def get_item_by_filepath(filepath):
    """Get item information by filepath"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, library_id, name, type, filepath
        FROM items
        WHERE filepath = ?
    ''', (filepath,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'id': result[0],
            'library_id': result[1],
            'name': result[2],
            'type': result[3],
            'filepath': result[4]
        }
    return None

def save_session_event(session_id, item_id, client, state, position_seconds):
    """Save a session event"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO sessions (id, item_id, client, state, position_seconds, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session_id, item_id, client, state, position_seconds, datetime.now()))

    conn.commit()
    conn.close()

def get_all_libraries():
    """Get all libraries from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT id, name FROM libraries ORDER BY name')
    results = cursor.fetchall()
    conn.close()

    return [{'id': row[0], 'name': row[1]} for row in results]

def get_items_by_library(library_id):
    """Get all items for a specific library"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, name, type, filepath
        FROM items
        WHERE library_id = ?
        ORDER BY name
    ''', (library_id,))

    results = cursor.fetchall()
    conn.close()

    return [{'id': row[0], 'name': row[1], 'type': row[2], 'filepath': row[3]} for row in results]

def save_last_scan_time(scan_time):
    """Save the timestamp of the last library scan"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO metadata (key, value, updated_at)
        VALUES (?, ?, ?)
    ''', ('last_scan_time', scan_time.isoformat(), datetime.now()))

    conn.commit()
    conn.close()

def get_last_scan_time():
    """Get the timestamp of the last library scan"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT value FROM metadata WHERE key = ?
    ''', ('last_scan_time',))

    result = cursor.fetchone()
    conn.close()

    if result:
        from datetime import datetime
        return datetime.fromisoformat(result[0])
    return None

def update_item(item_id, library_id, name, item_type, filepath):
    """Update an existing item or create if it doesn't exist"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Check if item exists
    cursor.execute('SELECT id FROM items WHERE id = ?', (item_id,))
    exists = cursor.fetchone()

    if exists:
        cursor.execute('''
            UPDATE items
            SET library_id = ?, name = ?, type = ?, filepath = ?, updated_at = ?
            WHERE id = ?
        ''', (library_id, name, item_type, filepath, datetime.now(), item_id))
        action = "updated"
    else:
        cursor.execute('''
            INSERT INTO items (id, library_id, name, type, filepath, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (item_id, library_id, name, item_type, filepath, datetime.now()))
        action = "added"

    conn.commit()
    conn.close()

    return action

def save_frame(item_id, timestamp_seconds, frame_path=None, width=None, height=None, led_colors=None, udp_packet=None):
    """Save frame information to database with optional UDP packet data"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Convert LED colors list to JSON string if provided (legacy support)
    led_colors_json = None
    if led_colors:
        import json
        led_colors_json = json.dumps(led_colors)

    cursor.execute('''
        INSERT OR REPLACE INTO frames (item_id, timestamp_seconds, frame_path, width, height, led_colors, udp_packet, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (item_id, timestamp_seconds, frame_path, width, height, led_colors_json, udp_packet, datetime.now()))

    conn.commit()
    conn.close()

def save_frame_udp(item_id, timestamp_seconds, led_colors, width=None, height=None):
    """Save frame with UDP packet data (efficient storage)"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Create WLED DRGB UDP packet
    udp_packet = create_wled_udp_packet(led_colors)

    cursor.execute('''
        INSERT OR REPLACE INTO frames (item_id, timestamp_seconds, width, height, udp_packet, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (item_id, timestamp_seconds, width, height, udp_packet, datetime.now()))

    conn.commit()
    conn.close()

def create_wled_udp_packet(led_colors, timeout=1):
    """Create WLED DRGB UDP packet from LED colors"""
    # DRGB protocol: [D][R][G][B][timeout][RGB][RGB][RGB]...
    packet = bytearray([ord('D'), ord('R'), ord('G'), ord('B'), timeout])

    for color in led_colors:
        if color and len(color) >= 3:
            packet.extend([int(color[0]), int(color[1]), int(color[2])])
        else:
            packet.extend([0, 0, 0])

    return bytes(packet)

def parse_wled_udp_packet(udp_packet):
    """Parse WLED UDP packet back to LED colors"""
    if not udp_packet or len(udp_packet) < 5:
        return None

    # Verify DRGB header
    if udp_packet[:4] != b'DRGB':
        return None

    # Extract LED colors (skip 5-byte header)
    led_data = udp_packet[5:]
    led_colors = []

    for i in range(0, len(led_data), 3):
        if i + 2 < len(led_data):
            r, g, b = led_data[i], led_data[i+1], led_data[i+2]
            led_colors.append([r, g, b])

    return led_colors

def get_frames_for_item(item_id):
    """Get all frames for a specific item"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, timestamp_seconds, frame_path, width, height, led_colors, udp_packet, created_at
        FROM frames
        WHERE item_id = ?
        ORDER BY timestamp_seconds
    ''', (item_id,))

    results = cursor.fetchall()
    conn.close()

    frames = []
    for row in results:
        # Parse LED colors from UDP packet (preferred) or JSON (legacy)
        led_colors = None
        udp_packet = row[6]  # udp_packet column

        if udp_packet:
            # Parse from efficient UDP packet
            led_colors = parse_wled_udp_packet(udp_packet)
        elif row[5]:  # led_colors JSON column (legacy)
            try:
                import json
                led_colors = json.loads(row[5])
            except (json.JSONDecodeError, TypeError):
                led_colors = None

        frames.append({
            'id': row[0],
            'timestamp_seconds': row[1],
            'frame_path': row[2],
            'width': row[3],
            'height': row[4],
            'led_colors': led_colors,
            'udp_packet': udp_packet,
            'created_at': row[7]
        })

    return frames

def get_udp_packet_at_timestamp(item_id, timestamp_seconds):
    """Get UDP packet for direct WLED transmission (ultra-fast)"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Find the closest frame
    cursor.execute('''
        SELECT udp_packet, timestamp_seconds
        FROM frames
        WHERE item_id = ? AND udp_packet IS NOT NULL
        ORDER BY ABS(timestamp_seconds - ?) ASC
        LIMIT 1
    ''', (item_id, timestamp_seconds))

    result = cursor.fetchone()
    conn.close()

    if result:
        return result[0]  # Return raw UDP packet for direct transmission
    return None

def frame_exists(item_id, timestamp_seconds):
    """Check if a frame already exists for this item and timestamp"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COUNT(*) FROM frames WHERE item_id = ? AND timestamp_seconds = ?
    ''', (item_id, timestamp_seconds))

    result = cursor.fetchone()
    conn.close()

    return result[0] > 0

def get_item_by_id(item_id):
    """Get item information by ID"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, library_id, name, type, filepath
        FROM items
        WHERE id = ?
    ''', (item_id,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'id': result[0],
            'library_id': result[1],
            'name': result[2],
            'type': result[3],
            'filepath': result[4]
        }
    return None

def get_videos_needing_extraction(priority_order='newest_first', limit=None):
    """Get videos that need frame extraction, ordered by priority

    Args:
        priority_order: 'newest_first', 'oldest_first', 'alphabetical', or 'random'
        limit: Maximum number of items to return (None for all)

    Returns:
        List of video items that need frame extraction
    """
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
    # Movies are prioritized over Episodes/TV shows in all ordering modes
    if priority_order == 'newest_first':
        order_clause = '''ORDER BY
            CASE
                WHEN i.type = 'Movie' THEN 0
                WHEN i.type = 'Episode' THEN 1
                ELSE 2
            END,
            i.updated_at DESC, i.created_at DESC'''
    elif priority_order == 'oldest_first':
        order_clause = '''ORDER BY
            CASE
                WHEN i.type = 'Movie' THEN 0
                WHEN i.type = 'Episode' THEN 1
                ELSE 2
            END,
            i.created_at ASC, i.updated_at ASC'''
    elif priority_order == 'alphabetical':
        order_clause = '''ORDER BY
            CASE
                WHEN i.type = 'Movie' THEN 0
                WHEN i.type = 'Episode' THEN 1
                ELSE 2
            END,
            i.name ASC'''
    elif priority_order == 'random':
        order_clause = '''ORDER BY
            CASE
                WHEN i.type = 'Movie' THEN 0
                WHEN i.type = 'Episode' THEN 1
                ELSE 2
            END,
            RANDOM()'''
    else:
        order_clause = '''ORDER BY
            CASE
                WHEN i.type = 'Movie' THEN 0
                WHEN i.type = 'Episode' THEN 1
                ELSE 2
            END,
            i.updated_at DESC'''  # Default to newest first

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

    # Most recent extraction
    cursor.execute('''
        SELECT MAX(created_at) FROM frames
    ''')
    last_extraction = cursor.fetchone()[0]

    # Most recent video added
    cursor.execute('''
        SELECT MAX(updated_at) FROM items
        WHERE type IN ('Movie', 'Episode', 'Video')
    ''')
    last_video_added = cursor.fetchone()[0]

    conn.close()

    return {
        'total_videos': total_videos,
        'extracted_videos': extracted_videos,
        'pending_videos': pending_videos,
        'completion_percentage': (extracted_videos / total_videos * 100) if total_videos > 0 else 0,
        'last_extraction': last_extraction,
        'last_video_added': last_video_added
    }
