import websocket
import threading
import json
import signal
import sys
import time

# ===== CONFIG =====
JELLYFIN_URL = "https://jellyfin.galagaon.com"
JELLYFIN_API_KEY = "9b53498f4e1b4325a420fd705fea0020"
JELLYFIN_WS_URL = "wss://jellyfin.galagaon.com/socket"  # No API key in URL
# ==================

ws_app = None
running = True

# ===== HANDLERS =====
def on_open(ws):
    print("[ws] Connected to Jellyfin")

    # Don't send messages immediately - wait a moment for connection to stabilize
    import threading
    def send_initial_messages():
        import time
        time.sleep(0.5)  # Give connection time to stabilize

        try:
            # Connect / register with more complete client info
            connect_msg = {
                "MessageType": "Connect",
                "Data": {
                    "Client": "ambilight-script",
                    "Device": "Python",
                    "DeviceId": "ambilight-001",
                    "Version": "1.0",
                    "ApplicationVersion": "1.0"
                }
            }
            print(f"[ws] Sending Connect: {connect_msg}")
            ws.send(json.dumps(connect_msg))

            # Wait before subscribing
            time.sleep(0.5)

            # Subscribe to events - try simpler format first
            subscribe_msg = {
                "MessageType": "Subscribe",
                "Data": {}  # Empty data to subscribe to all events
            }
            print(f"[ws] Sending Subscribe: {subscribe_msg}")
            ws.send(json.dumps(subscribe_msg))

        except Exception as e:
            print(f"[ws] Error sending initial messages: {e}")

    # Send messages in separate thread to avoid blocking
    threading.Thread(target=send_initial_messages, daemon=True).start()


def on_close(ws, close_status_code, close_msg):
    print(f"[ws] Connection closed: {close_status_code}, {close_msg}")

def on_error(ws, error):
    print("[ws error]", error)

def on_message(ws, message):
    try:
        msg = json.loads(message)
    except Exception:
        print("[ws] Invalid JSON:", message)
        return

    # Debug: show all raw messages
    print("[ws raw]", msg)

    # Handle different message types
    msg_type = msg.get("MessageType")

    if msg_type == "ConnectResponse":
        print("[ws] ✅ Connection acknowledged by server")
    elif msg_type == "SubscribeResponse":
        print("[ws] ✅ Subscription confirmed")
    elif msg_type == "ForceKeepAlive":
        print("[ws] 💓 Keep-alive received")
        # Respond to keep-alive
        ws.send(json.dumps({"MessageType": "KeepAlive"}))
    else:
        # Handle playback events
        data = msg.get("Data", {})
        event_name = data.get("EventName")
        if event_name in ("PlaybackStart", "PlaybackProgress", "PlaybackStopped"):
            item = data.get("Item", {})
            position = data.get("PositionTicks", 0) / 10_000_000  # convert ticks to seconds
            print(f"[ws event] {event_name} | {item.get('Name', item.get('Id'))} | position={position:.2f}s")

# ===== RUN WEBSOCKET =====
def run_ws():
    global ws_app

    # Build proper authorization header for Jellyfin
    auth_header_val = f'MediaBrowser Client="ambilight-script", Device="Python", DeviceId="ambilight-001", Version="1.0", Token="{JELLYFIN_API_KEY}"'
    headers = [f"Authorization: {auth_header_val}"]

    print(f"[ws] Connecting to {JELLYFIN_WS_URL}")
    print(f"[ws] Auth header: {auth_header_val}")

    ws_app = websocket.WebSocketApp(
        JELLYFIN_WS_URL,
        header=headers,
        on_open=on_open,
        on_close=on_close,
        on_error=on_error,
        on_message=on_message
    )
    # Run with reconnection logic
    while running:
        try:
            ws_app.run_forever(ping_interval=30, ping_timeout=10)
            if not running:
                break
            print("[ws] Connection lost, reconnecting in 3 seconds...")
            time.sleep(3)
        except Exception as e:
            print(f"[ws] Error: {e}")
            if not running:
                break
            print("[ws] Reconnecting in 5 seconds...")
            time.sleep(5)

# ===== SIGNAL HANDLER =====
def signal_handler(sig, frame):
    global running
    print("\n[ws] KeyboardInterrupt -> closing websocket...")
    running = False
    if ws_app:
        ws_app.close()

signal.signal(signal.SIGINT, signal_handler)

# ===== MAIN =====
if __name__ == "__main__":
    thread = threading.Thread(target=run_ws)
    thread.start()

    try:
        while running:
            time.sleep(0.5)
    finally:
        if ws_app:
            ws_app.close()
        thread.join()
        print("[ws] Exited cleanly")
