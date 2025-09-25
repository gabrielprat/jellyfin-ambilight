import socket
import struct
import time

UDP_IP = "192.168.1.123"   # IP del teu WLED
UDP_PORT = 21324           # port UDP de WLED

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

input_file = "frames_with_payload.bin"

with open(input_file, "rb") as f:
    start_time = time.time()
    while True:
        header = f.read(10)  # 8 (double) + 2 (uint16)
        if not header:
            break

        timestamp, payload_len = struct.unpack("<dH", header)
        payload = f.read(payload_len)

        # Espera fins al moment adequat
        while time.time() - start_time < timestamp:
            time.sleep(0.001)

        # Envia a WLED
        sock.sendto(payload, (UDP_IP, UDP_PORT))

