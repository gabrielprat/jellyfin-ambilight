#!/bin/bash

echo "🦔 Testing Sonic Movie Ambilight"
echo "================================"

# Test WLED connection first
echo "1. Testing WLED connection..."
docker-compose run --rm jellyfin-ambilight python test-video-ambilight.py --test-connection

if [ $? -eq 0 ]; then
    echo ""
    echo "2. Extracting frames from Sonic movie (first 30 seconds)..."
    docker-compose run --rm jellyfin-ambilight python test-video-ambilight.py \
        --file "/app/test/Sonic.The.Hedgehog.3.2024.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv" \
        --duration 300 \
        --start 60 \
        --interval 0.1
else
    echo "❌ WLED connection failed. Please check your WLED configuration."
    echo "   Make sure WLED_HOST is set correctly in your .env file"
fi
