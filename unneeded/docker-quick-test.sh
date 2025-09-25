#!/bin/bash

# Quick Docker setup test
echo "🐳 Quick Docker Test"
echo "==================="

# Test environment loading
echo "Testing environment file loading..."
if [ -f "env.development" ]; then
    echo "✅ env.development exists"
    echo "Sample variables:"
    grep -E '^[A-Z_].*=' env.development | head -5
else
    echo "❌ env.development missing"
fi

echo ""
echo "Testing Docker setup..."

# Test Docker
if command -v docker &> /dev/null; then
    echo "✅ Docker available"
    docker --version
else
    echo "❌ Docker not found"
    exit 1
fi

# Test Docker Compose
if command -v docker-compose &> /dev/null; then
    echo "✅ Docker Compose available"
    docker-compose --version
else
    echo "❌ Docker Compose not found"
    exit 1
fi

echo ""
echo "Testing configuration..."

# Load development environment
export $(grep -E '^[A-Z_].*=' env.development | xargs)

echo "Loaded environment:"
echo "  JELLYFIN_BASE_URL: $JELLYFIN_BASE_URL"
echo "  WLED_HOST: $WLED_HOST"
echo "  DATA_PATH: $DATA_PATH"

echo ""
echo "Testing basic connectivity..."

# Test Jellyfin connectivity
if [ -n "$JELLYFIN_BASE_URL" ] && [ -n "$JELLYFIN_API_KEY" ]; then
    echo "Testing Jellyfin connection..."
    curl -s -w "HTTP %{http_code}" -o /dev/null \
        -H "Authorization: MediaBrowser Client=\"test\", Device=\"Docker\", DeviceId=\"test-001\", Version=\"1.0\", Token=\"$JELLYFIN_API_KEY\"" \
        "$JELLYFIN_BASE_URL/System/Info" || echo "Connection test failed"
else
    echo "⚠️ Jellyfin credentials not set"
fi

echo ""
echo "🎯 Ready for Docker deployment!"
echo ""
echo "Next steps:"
echo "1. Build image:     ./docker-manager.sh build"
echo "2. Start service:   ./docker-manager.sh start development"
echo "3. View logs:       ./docker-manager.sh logs"
