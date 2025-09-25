import requests
import os
import argparse
from datetime import datetime
from database import init_database, save_library, save_item, update_item, save_last_scan_time, get_last_scan_time

API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")
BASE_URL = os.getenv("JELLYFIN_BASE_URL", "https://jellyfin.galagaon.com")

def get_users():
    r = requests.get(
        f"{BASE_URL}/Users",
        headers={"X-Emby-Token": API_KEY},
        verify=True
    )
    r.raise_for_status()
    return r.json()

def get_libraries(user_id):
    r = requests.get(
        f"{BASE_URL}/Users/{user_id}/Views",
        headers={"X-Emby-Token": API_KEY},
        verify=True
    )
    r.raise_for_status()
    return r.json()

def check_updates(user_id, since_time):
    r = requests.get(
        f"{BASE_URL}/Users/{user_id}/Items/Updates",
        params={"Since": since_time.isoformat()},
        headers={"X-Emby-Token": API_KEY}
    )
    r.raise_for_status()
    return r.json()

def get_all_items(user_id, library_id, recursive=True, page_size=100):
    """Fetch all items from a library with pagination"""
    all_items = []
    start = 0

    while True:
        r = requests.get(
            f"{BASE_URL}/Users/{user_id}/Items",
            params={
                "ParentId": library_id,
                "Recursive": str(recursive).lower(),
                "IncludeItemTypes": "Movie,Episode,Video",
                "Fields": "Path",
                "StartIndex": start,
                "Limit": page_size
            },
            headers={"X-Emby-Token": API_KEY},
            verify=True
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("Items", [])
        if not items:
            break

        all_items.extend(items)
        start += page_size

        # stop if we've fetched all reported items
        total = data.get("TotalRecordCount", len(all_items))
        if len(all_items) >= total:
            break

    return all_items

def get_item_detail(user_id, item_id):
    r = requests.get(
        f"{BASE_URL}/Users/{user_id}/Items/{item_id}",
        headers={"X-Emby-Token": API_KEY},
        verify=True
    )
    r.raise_for_status()
    return r.json()

def perform_full_scan(user_id):
    """Perform a complete library scan"""
    scan_start_time = datetime.now()
    print(f"Starting full library scan at {scan_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    libraries = get_libraries(user_id)
    total_items = 0

    for lib in libraries.get("Items", []):
        lib_id = lib['Id']
        lib_name = lib['Name']

        print(f"\n📚 Library: {lib_name} ({lib_id})")

        # Save library to database
        save_library(lib_id, lib_name)

        items = get_all_items(user_id, lib_id)
        print(f"  → Found {len(items)} items")
        total_items += len(items)

        for item in items:
            item_id = item["Id"]
            title = item.get("Name", "Unknown")
            item_type = item.get("Type", "Unknown")

            # Fetch full details to get filepath
            detail = get_item_detail(user_id, item_id)
            filepath = "Unknown"
            if "MediaSources" in detail and detail["MediaSources"]:
                filepath = detail["MediaSources"][0].get("Path", "Unknown")

            # Save item to database
            save_item(item_id, lib_id, title, item_type, filepath)

            print(f"🎬 Title: {title}")
            print(f"   📂 Filepath: {filepath}")

    # Save the scan completion time
    save_last_scan_time(scan_start_time)
    print(f"\n✅ Full scan complete - {total_items} items processed and saved to database")
    print(f"Last scan time saved: {scan_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

def perform_incremental_update(user_id):
    """Perform an incremental update since the last scan"""
    last_scan = get_last_scan_time()

    if not last_scan:
        print("⚠️  No previous scan found. Please run a full scan first.")
        print("Use: python jellyfin-library-api.py --full-scan")
        return

    print(f"Checking for updates since last scan: {last_scan.strftime('%Y-%m-%d %H:%M:%S')}")

    # Get updates from Jellyfin
    update_start_time = datetime.now()
    updates_data = check_updates(user_id, last_scan)

    items_added = updates_data.get("ItemsAdded", [])
    items_updated = updates_data.get("ItemsUpdated", [])
    items_removed = updates_data.get("ItemsRemoved", [])

    total_changes = len(items_added) + len(items_updated) + len(items_removed)

    if total_changes == 0:
        print("✅ No updates found - library is up to date")
        save_last_scan_time(update_start_time)
        return

    print(f"Found {total_changes} changes:")
    print(f"  ➕ Added: {len(items_added)}")
    print(f"  🔄 Updated: {len(items_updated)}")
    print(f"  ❌ Removed: {len(items_removed)}")

    # Process added items
    for item_id in items_added:
        try:
            detail = get_item_detail(user_id, item_id)
            title = detail.get("Name", "Unknown")
            item_type = detail.get("Type", "Unknown")
            library_id = detail.get("ParentId", "Unknown")

            filepath = "Unknown"
            if "MediaSources" in detail and detail["MediaSources"]:
                filepath = detail["MediaSources"][0].get("Path", "Unknown")

            action = update_item(item_id, library_id, title, item_type, filepath)
            print(f"➕ {action.capitalize()}: {title}")

        except Exception as e:
            print(f"⚠️  Error processing added item {item_id}: {e}")

    # Process updated items
    for item_id in items_updated:
        try:
            detail = get_item_detail(user_id, item_id)
            title = detail.get("Name", "Unknown")
            item_type = detail.get("Type", "Unknown")
            library_id = detail.get("ParentId", "Unknown")

            filepath = "Unknown"
            if "MediaSources" in detail and detail["MediaSources"]:
                filepath = detail["MediaSources"][0].get("Path", "Unknown")

            action = update_item(item_id, library_id, title, item_type, filepath)
            print(f"🔄 {action.capitalize()}: {title}")

        except Exception as e:
            print(f"⚠️  Error processing updated item {item_id}: {e}")

    # Process removed items (we'll just log them for now)
    for item_id in items_removed:
        print(f"❌ Removed item: {item_id}")
        # Note: We're not actually removing from database to preserve history
        # You could add a 'deleted' flag or actually remove if preferred

    # Save the update completion time
    save_last_scan_time(update_start_time)
    print(f"\n✅ Incremental update complete - {total_changes} changes processed")
    print(f"Last scan time updated: {update_start_time.strftime('%Y-%m-%d %H:%M:%S')}")

def main():
    parser = argparse.ArgumentParser(description='Jellyfin Library Scanner')
    parser.add_argument('--full-scan', action='store_true',
                        help='Perform a complete library scan')
    parser.add_argument('--update', action='store_true',
                        help='Perform incremental update since last scan')

    args = parser.parse_args()

    # If no arguments provided, default to incremental update
    if not args.full_scan and not args.update:
        args.update = True

    # Initialize database
    init_database()
    print("Database initialized")

    users = get_users()
    user_id = users[0]["Id"]
    print(f"Using UserId: {user_id}")

    if args.full_scan:
        perform_full_scan(user_id)
    elif args.update:
        perform_incremental_update(user_id)

if __name__ == "__main__":
    main()
