#!/usr/bin/env python3
"""
Quick test to verify the fixed websocket connection works properly
"""

import websocket
import json
import time
import threading

JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

connected = False
messages_received = 0

def on_open(ws):
    global connected
    connected = True
    print("[ws] ✅ Connected to Jellyfin")

    # Connect / register
    ws.send(json.dumps({
        "MessageType": "Connect",
        "Data": {
            "Client": "test-script",
            "Device": "Python",
            "DeviceId": "test-001",
            "Version": "1.0"
        }
    }))

    # Subscribe to specific events
    ws.send(json.dumps({
        "MessageType": "Subscribe",
        "Data": {
            "EventNames": [
                "PlaybackStart",
                "PlaybackProgress",
                "PlaybackStopped",
                "SessionsStart",
                "SessionsEnd"
            ]
        }
    }))

def on_message(ws, message):
    global messages_received
    messages_received += 1

    try:
        msg = json.loads(message)
        msg_type = msg.get("MessageType")
        print(f"[ws] 📥 Message #{messages_received}: {msg_type}")

        if msg_type == "ForceKeepAlive":
            print("[ws] 💓 Responding to keep-alive")
            ws.send(json.dumps({"MessageType": "KeepAlive"}))
        elif msg_type == "ConnectResponse":
            print("[ws] ✅ Connection acknowledged")
        elif msg_type == "SubscribeResponse":
            print("[ws] ✅ Subscription confirmed")

    except Exception as e:
        print(f"[ws] ❌ Error parsing message: {e}")

def on_error(ws, error):
    print(f"[ws] ❌ Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[ws] 🔌 Connection closed: {close_status_code} - {close_msg}")

def main():
    print("🧪 Testing Fixed WebSocket Connection")
    print("=" * 50)

    # Build authorization header
    auth_header_val = f'MediaBrowser Client="test-script", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    print(f"[ws] Connecting to {JELLYFIN_WS_URL}")

    ws_app = websocket.WebSocketApp(
        JELLYFIN_WS_URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # Run for 10 seconds then close
    def close_after_delay():
        time.sleep(10)
        print("\n[test] ⏰ 10 seconds elapsed, closing connection...")
        ws_app.close()

    close_thread = threading.Thread(target=close_after_delay, daemon=True)
    close_thread.start()

    ws_app.run_forever(ping_interval=30, ping_timeout=10)

    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"Connected: {'✅ Yes' if connected else '❌ No'}")
    print(f"Messages received: {messages_received}")

    if connected and messages_received > 0:
        print("🎉 WebSocket connection is working properly!")
    else:
        print("⚠️  WebSocket connection may have issues")

if __name__ == "__main__":
    main()
