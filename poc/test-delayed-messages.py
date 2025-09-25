#!/usr/bin/env python3
"""
Test delayed message sending to see what happens
"""

import websocket
import json
import time
import threading

JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

messages_sent = 0
messages_received = 0

def on_open(ws):
    print("[ws] ✅ Connected to Jellyfin")

    def send_delayed_messages():
        global messages_sent
        time.sleep(1)  # Wait 1 second

        try:
            # Send simple Connect message
            connect_msg = {
                "MessageType": "Connect",
                "Data": {
                    "Client": "test-client",
                    "Device": "Python",
                    "DeviceId": "test-001",
                    "Version": "1.0"
                }
            }
            print(f"[ws] 📤 Sending Connect message...")
            ws.send(json.dumps(connect_msg))
            messages_sent += 1

            time.sleep(1)  # Wait before subscribing

            subscribe_msg = {
                "MessageType": "Subscribe",
                "Data": {}
            }
            print(f"[ws] 📤 Sending Subscribe message...")
            ws.send(json.dumps(subscribe_msg))
            messages_sent += 1

        except Exception as e:
            print(f"[ws] ❌ Error sending messages: {e}")

    threading.Thread(target=send_delayed_messages, daemon=True).start()

def on_message(ws, message):
    global messages_received
    messages_received += 1
    print(f"[ws] 📥 Message #{messages_received}: {message}")

def on_error(ws, error):
    print(f"[ws] ❌ Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[ws] 🔌 Connection closed: {close_status_code} - {close_msg}")

def main():
    print("🧪 Testing Delayed Message Sending")
    print("=" * 50)

    auth_header_val = f'MediaBrowser Client="test-client", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
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

    def close_after_delay():
        time.sleep(10)
        print("\n[test] ⏰ Time's up, closing...")
        ws_app.close()

    threading.Thread(target=close_after_delay, daemon=True).start()

    ws_app.run_forever(ping_interval=30, ping_timeout=10)

    print("\n" + "=" * 50)
    print("📊 Results:")
    print(f"Messages sent: {messages_sent}")
    print(f"Messages received: {messages_received}")

if __name__ == "__main__":
    main()
