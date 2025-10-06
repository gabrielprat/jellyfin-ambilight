FROM python:3.11-slim

WORKDIR /app

# Install only essential packages for OpenCV headless
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Provide requirements to the image at build time
RUN mkdir -p /app/src
COPY requirements.txt /app/src/requirements.txt

# Install minimal Python dependencies
RUN pip install --no-cache-dir -r /app/src/requirements.txt

# Create data directory
RUN mkdir -p /app/data/ambilight

# Set environment
ENV PYTHONUNBUFFERED=1 \
    AMBILIGHT_DATA_DIR=/app/data/ambilight

# Simple CMD - no file modifications needed
CMD echo "💎 Jellyfin Ambilight - Simplified Setup" && \
    echo "📡 Jellyfin: $JELLYFIN_BASE_URL" && \
    echo "🔊 WLED: $WLED_HOST:$WLED_UDP_PORT" && \
    echo "🚀 Starting ambilight daemon..." && \
    python3 -u /app/src/ambilight-daemon-cv2.py
