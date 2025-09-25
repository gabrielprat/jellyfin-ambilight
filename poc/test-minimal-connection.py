#!/usr/bin/env python3
"""
Minimal test - just connect and keep connection open without sending any messages
"""

import websocket
import time
import threading

JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

def on_open(ws):
    print("[ws] ✅ Connected to Jellyfin - NOT sending any messages")

def on_message(ws, message):
    print(f"[ws] 📥 Received: {message}")

def on_error(ws, error):
    print(f"[ws] ❌ Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[ws] 🔌 Connection closed: {close_status_code} - {close_msg}")

def main():
    print("🧪 Testing Minimal WebSocket Connection (No Messages)")
    print("=" * 60)

    # Build authorization header
    auth_header_val = f'MediaBrowser Client="minimal-test", Device="Python", DeviceId="minimal-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    print(f"[ws] Connecting to {JELLYFIN_WS_URL}")
    print("[ws] Will NOT send Connect/Subscribe messages")

    ws_app = websocket.WebSocketApp(
        JELLYFIN_WS_URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # Run for 15 seconds then close
    def close_after_delay():
        time.sleep(15)
        print("\n[test] ⏰ 15 seconds elapsed, closing connection...")
        ws_app.close()

    close_thread = threading.Thread(target=close_after_delay, daemon=True)
    close_thread.start()

    ws_app.run_forever(ping_interval=30, ping_timeout=10)

    print("\n" + "=" * 60)
    print("📊 Test Complete - Check if connection stayed open longer")

if __name__ == "__main__":
    main()
