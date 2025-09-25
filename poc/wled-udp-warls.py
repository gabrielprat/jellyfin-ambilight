import socket

# WLED-IP-Adresse
WLED_IP = "192.168.1.86"
# WLED-UDP-Port
WLED_PORT = 65506

# Erstelle einen UDP-Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Protokoll auswählen
protocol = 1
# Timeout auf 1 Sekunde setzen
timeout = 1

# Farben für ungerade und gerade LEDs
odd_color = (255, 0, 0)
even_color = (0, 255, 0)

# Anzahl der LEDs
num_leds = 100

# Farbdaten für alle LEDs erstellen
colors = [odd_color if i % 2 == 1 else even_color for i in range(num_leds)]

# Farbdaten in das WARLS-Protokoll konvertieren
data = bytearray([protocol, timeout])
for i in range(num_leds):
    data += bytearray([i, colors[i][0], colors[i][1], colors[i][2]])

# Byte 1 auf 1 setzen, um die Farben dauerhaft zu ändern
data[1] = 255

# Daten an WLED senden
sock.sendto(data, (WLED_IP, WLED_PORT))
print(data, (WLED_IP, WLED_PORT))
