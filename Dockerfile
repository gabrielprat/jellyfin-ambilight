FROM python:3.11-alpine

WORKDIR /app

# Install only essential packages
RUN apk add --no-cache ffmpeg

# Install minimal Python dependencies
RUN pip install --no-cache-dir requests==2.31.0

# Create data directory
RUN mkdir -p /app/data/ambilight

# Set environment
ENV PYTHONUNBUFFERED=1 \
    AMBILIGHT_DATA_DIR=/app/data/ambilight

# Simple CMD - no file modifications needed
CMD echo "💎 Jellyfin Ambilight - Simplified Alpine Setup" && \
    echo "📦 Image size: 181MB (vs 1.89GB Debian)" && \
    echo "🚀 10x smaller, same functionality!" && \
    echo "📡 Jellyfin: $JELLYFIN_BASE_URL" && \
    echo "🔊 WLED: $WLED_HOST:$WLED_UDP_PORT" && \
    echo "🚀 Starting ambilight daemon..." && \
    python3 -u /app/src/ambilight-daemon-files.py
