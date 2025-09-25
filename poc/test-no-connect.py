#!/usr/bin/env python3
"""
Test: Skip Connect message entirely, just try Subscribe or listen for events
"""

import websocket
import json
import time
import threading

JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

def test_no_connect():
    print("🧪 Test 1: No Connect, No Subscribe - Just Listen")
    messages_received = 0

    def on_open(ws):
        print("[ws] ✅ Connected - Doing NOTHING, just listening...")

    def on_message(ws, message):
        nonlocal messages_received
        messages_received += 1
        print(f"[ws] 📥 Message #{messages_received}: {message}")

    def on_close(ws, close_status_code, close_msg):
        print(f"[ws] 🔌 Closed: {close_status_code} - {close_msg}")

    def on_error(ws, error):
        print(f"[ws] ❌ Error: {error}")

    auth_header_val = f'MediaBrowser Client="listener", Device="Python", DeviceId="listener-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    ws_app = websocket.WebSocketApp(JELLYFIN_WS_URL, header=headers, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)

    def close_after_delay():
        time.sleep(10)
        print("\n[test] ⏰ Closing after 10 seconds...")
        ws_app.close()

    threading.Thread(target=close_after_delay, daemon=True).start()
    ws_app.run_forever()

    return messages_received

def test_subscribe_only():
    print("\n🧪 Test 2: Skip Connect, Try Subscribe Only")
    messages_received = 0

    def on_open(ws):
        print("[ws] ✅ Connected - Skipping Connect, trying Subscribe...")

        def send_subscribe():
            time.sleep(1)
            try:
                subscribe_msg = {"MessageType": "Subscribe", "Data": {}}
                print(f"[ws] 📤 Sending Subscribe: {subscribe_msg}")
                ws.send(json.dumps(subscribe_msg))
            except Exception as e:
                print(f"[ws] ❌ Error: {e}")

        threading.Thread(target=send_subscribe, daemon=True).start()

    def on_message(ws, message):
        nonlocal messages_received
        messages_received += 1
        print(f"[ws] 📥 Message #{messages_received}: {message}")

    def on_close(ws, close_status_code, close_msg):
        print(f"[ws] 🔌 Closed: {close_status_code} - {close_msg}")

    def on_error(ws, error):
        print(f"[ws] ❌ Error: {error}")

    auth_header_val = f'MediaBrowser Client="subscriber", Device="Python", DeviceId="subscriber-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    ws_app = websocket.WebSocketApp(JELLYFIN_WS_URL, header=headers, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)

    def close_after_delay():
        time.sleep(10)
        print("\n[test] ⏰ Closing after 10 seconds...")
        ws_app.close()

    threading.Thread(target=close_after_delay, daemon=True).start()
    ws_app.run_forever()

    return messages_received

def main():
    print("🧪 Testing WebSocket Without Connect Message")
    print("=" * 60)

    # Test 1: Just connect and listen
    result1 = test_no_connect()

    # Test 2: Subscribe without Connect
    result2 = test_subscribe_only()

    print("\n" + "=" * 60)
    print("📊 Results:")
    print(f"Test 1 (No messages): {result1} messages received")
    print(f"Test 2 (Subscribe only): {result2} messages received")

    if result1 > 0:
        print("✅ Server sends messages without any client messages!")
    elif result2 > 0:
        print("✅ Subscribe works without Connect!")
    else:
        print("❌ Server requires specific message sequence")

if __name__ == "__main__":
    main()
