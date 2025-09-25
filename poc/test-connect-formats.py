#!/usr/bin/env python3
"""
Test different Connect message formats to find the right one
"""

import websocket
import json
import time
import threading

JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

test_results = []

def test_connect_format(format_name, connect_data):
    print(f"\n🧪 Testing format: {format_name}")
    print("=" * 50)

    result = {"format": format_name, "success": False, "messages_received": 0, "close_reason": None}

    def on_open(ws):
        print("[ws] ✅ Connected")

        def send_connect():
            time.sleep(0.5)
            try:
                connect_msg = {
                    "MessageType": "Connect",
                    "Data": connect_data
                }
                print(f"[ws] 📤 Sending: {json.dumps(connect_msg, indent=2)}")
                ws.send(json.dumps(connect_msg))
            except Exception as e:
                print(f"[ws] ❌ Error: {e}")

        threading.Thread(target=send_connect, daemon=True).start()

    def on_message(ws, message):
        result["messages_received"] += 1
        print(f"[ws] 📥 Response: {message}")

        # If we get a response, mark as success
        try:
            msg = json.loads(message)
            if msg.get("MessageType") == "ConnectResponse":
                result["success"] = True
                print("[ws] ✅ Connect successful!")
        except:
            pass

    def on_close(ws, close_status_code, close_msg):
        result["close_reason"] = f"{close_status_code} - {close_msg}"
        print(f"[ws] 🔌 Closed: {result['close_reason']}")

    def on_error(ws, error):
        print(f"[ws] ❌ Error: {error}")

    auth_header_val = f'MediaBrowser Client="test-client", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    ws_app = websocket.WebSocketApp(
        JELLYFIN_WS_URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    def close_after_delay():
        time.sleep(5)
        ws_app.close()

    threading.Thread(target=close_after_delay, daemon=True).start()

    ws_app.run_forever()

    test_results.append(result)
    return result

def main():
    print("🧪 Testing Different Connect Message Formats")
    print("=" * 60)

    # Test 1: Current format
    test_connect_format("Current Format", {
        "Client": "test-client",
        "Device": "Python",
        "DeviceId": "test-001",
        "Version": "1.0"
    })

    # Test 2: Without Version
    test_connect_format("No Version", {
        "Client": "test-client",
        "Device": "Python",
        "DeviceId": "test-001"
    })

    # Test 3: Empty Data
    test_connect_format("Empty Data", {})

    # Test 4: Just Client and DeviceId
    test_connect_format("Minimal", {
        "Client": "test-client",
        "DeviceId": "test-001"
    })

    # Test 5: Web client format
    test_connect_format("Web Client Format", {
        "Client": "Jellyfin Web",
        "Device": "Python",
        "DeviceId": "test-001",
        "Version": "10.10.7"
    })

    print("\n" + "=" * 60)
    print("📊 Test Results Summary:")
    print("=" * 60)

    for result in test_results:
        status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
        print(f"{result['format']:<20} | {status} | Msgs: {result['messages_received']} | Close: {result['close_reason']}")

    successful = [r for r in test_results if r["success"]]
    if successful:
        print(f"\n🎉 Found {len(successful)} working format(s)!")
    else:
        print(f"\n😞 No formats worked. All caused server shutdown.")

if __name__ == "__main__":
    main()
