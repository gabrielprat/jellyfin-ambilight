import json
import websocket
import os

# Jellyfin server details
JELLYFIN_URL = os.getenv("JELLYFIN_BASE_URL", "https://jellyfin.galagaon.com").replace("https://", "wss://").replace("http://", "ws://") + "/socket"
API_KEY = os.getenv("JELLYFIN_API_KEY", "9b53498f4e1b4325a420fd705fea0020")  # you can generate an API key in Jellyfin dashboard

def on_message(ws, message):
    print(f"RAW: {message}")
    try:
        data = json.loads(message)
        print(f"message: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Raw message: {message}")
        print(f"Error decoding: {e}")

def on_error(ws, error):
    print(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("Connection closed")

def on_open(ws):
    # You can still send Identity, but it’s optional if header is correct
    print("Connected.")
    ws.send(json.dumps({
        "MessageType": "SessionsStart",
        "Data": {}
    }))
    # auth_message = {
    #     "MessageType": "Identity",
    #     "Data": {
    #         "ServerId": "b39834e9984a40489a8b526bd2e621e4",
    #         "Client": "python-script",
    #         "Device": "python-client",
    #         "Version": "1.0",
    #         "Token": API_KEY
    #     }
    # }
    # ws.send(json.dumps(auth_message))
    # print("Connected and authentication sent.")

if __name__ == "__main__":
    websocket.enableTrace(False)

    # Add the Jellyfin authorization header
    headers = [
        f"X-Emby-Token: {API_KEY}"
    ]

    ws = websocket.WebSocketApp(
        JELLYFIN_URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever(sslopt={"cert_reqs": 0})  # remove sslopt if Let's Encrypt works fine
