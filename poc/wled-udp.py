import socket
import random

# WLED-IP-Adresse
WLED_IP = "wled-ambilight-lgc1.lan"

# WLED-UDP-Port
WLED_PORT = 21324

# Erstelle einen UDP-Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Escollir el protocol
# https://kno.wled.ge/interfaces/udp-realtime/
# 0 = WLED Notifier
# 1 = WARLS
# 2 = DRGB
# 3 = DRGBW
# 4 = DNRGB
protocol = 4
# Estableix el timeout a (1=1s, 255=persistent)
timeout = 255

# Colors for odd and even LEDs
odd_color = (255, 255, 0)
even_color = (255, 255, 0)

# Nombre de LEDs
num_leds = 256

colors = [odd_color if i % 2 == 1 else even_color for i in range(num_leds)]
# Convertir les dades en el protocol WARLS
data = bytearray([protocol, timeout])
for i in range(num_leds):
    if (protocol == 1 and i > 255) or (protocol == 4 and i > num_leds - 1):
        break
    if protocol == 1:
        data += bytearray([i, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)])
    elif protocol in [2, 3]:
        print("DRGB and DRGBW not implemented")
        data += bytearray([i, i, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)])
        break;
    elif protocol == 4:
        data += bytearray([i, i, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)])

# Estableix el byte 1 a 255 per aguantar en UDP mode
# data[1] = 255

# Enviem dades a WLED
sock.sendto(data, (WLED_IP, WLED_PORT))
print(data, (WLED_IP, WLED_PORT))
