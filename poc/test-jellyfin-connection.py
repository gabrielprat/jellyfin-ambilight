#!/usr/bin/env python3
"""
Simple test script to debug Jellyfin websocket connection issues.
Tests both HTTP API and WebSocket connectivity.
"""

import requests
import websocket
import json
import ssl
import time

# Configuration
JELLYFIN_URL = "https://jellyfin.galagaon.com"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"

def test_http_api():
    """Test basic HTTP API connectivity"""
    print("=== Testing HTTP API connectivity ===")

    try:
        # Test basic connectivity
        url = f"{JELLYFIN_URL}/System/Info"
        headers = {
            "Authorization": f'MediaBrowser Client="test-script", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
        }

        print(f"Testing URL: {url}")
        print(f"Headers: {headers}")

        response = requests.get(url, headers=headers, timeout=10)
        print(f"HTTP Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Server Name: {data.get('ServerName', 'Unknown')}")
            print(f"Version: {data.get('Version', 'Unknown')}")
            print("✅ HTTP API connection successful!")
            return True
        else:
            print(f"❌ HTTP API failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"❌ HTTP API test failed: {e}")
        return False

def test_websocket_connection():
    """Test WebSocket connectivity with detailed debugging"""
    print("\n=== Testing WebSocket connectivity ===")

    ws_url = f"wss://jellyfin.galagaon.com/socket"
    auth_header_val = f'MediaBrowser Client="test-script", Device="Python", DeviceId="test-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    print(f"WebSocket URL: {ws_url}")
    print(f"Auth header: {auth_header_val}")

    connection_success = False

    def on_open(ws):
        print("✅ WebSocket connection opened!")
        nonlocal connection_success
        connection_success = True

        # Send connection message
        connect_msg = {
            "MessageType": "Connect",
            "Data": {
                "Client": "test-script",
                "Device": "Python",
                "DeviceId": "test-001",
                "Version": "1.0"
            }
        }
        ws.send(json.dumps(connect_msg))
        print("📤 Sent Connect message")

        # Subscribe to events
        subscribe_msg = {
            "MessageType": "Subscribe",
            "Data": {}
        }
        ws.send(json.dumps(subscribe_msg))
        print("📤 Sent Subscribe message")

        # Close after a short delay for testing
        time.sleep(2)
        ws.close()

    def on_message(ws, message):
        try:
            data = json.loads(message)
            print(f"📥 Received message: {data.get('MessageType', 'Unknown')} - {data}")
        except:
            print(f"📥 Received raw message: {message}")

    def on_error(ws, error):
        print(f"❌ WebSocket error: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")

    try:
        # Create WebSocket app
        ws_app = websocket.WebSocketApp(
            ws_url,
            header=headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        # Run with timeout
        print("🔄 Attempting WebSocket connection...")
        ws_app.run_forever(ping_interval=30, ping_timeout=10)

        return connection_success

    except Exception as e:
        print(f"❌ WebSocket test failed: {e}")
        return False

def main():
    print("🧪 Jellyfin Connection Test")
    print("=" * 50)

    # Test HTTP API first
    http_success = test_http_api()

    # Test WebSocket
    ws_success = test_websocket_connection()

    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"HTTP API: {'✅ Success' if http_success else '❌ Failed'}")
    print(f"WebSocket: {'✅ Success' if ws_success else '❌ Failed'}")

    if not http_success:
        print("\n🔧 HTTP API Troubleshooting:")
        print("- Check if Jellyfin URL is correct")
        print("- Verify API key is valid")
        print("- Check if server is accessible")

    if not ws_success:
        print("\n🔧 WebSocket Troubleshooting:")
        print("- Check if nginx proxy manager has 'Websockets Support' enabled")
        print("- Verify the proxy passes WebSocket upgrade headers")
        print("- Check nginx configuration for WebSocket support")
        print("- Try connecting directly to Jellyfin (bypass proxy)")

if __name__ == "__main__":
    main()
