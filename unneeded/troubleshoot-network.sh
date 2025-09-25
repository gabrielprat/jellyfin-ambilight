#!/bin/bash

# Network Troubleshooting Script for Jellyfin Ambilight
echo "🌐 NETWORK TROUBLESHOOTING"
echo "=========================="

# Load environment if available
if [ -f "env.homeserver" ]; then
    echo "📁 Loading environment from env.homeserver..."
    export $(grep -E '^[A-Z_].*=' env.homeserver | xargs)
fi

echo ""
echo "🔧 Current Configuration:"
echo "  JELLYFIN_BASE_URL: ${JELLYFIN_BASE_URL}"
echo "  WLED_HOST: ${WLED_HOST}"
echo "  DNS_SERVER: ${DNS_SERVER}"

echo ""
echo "🧪 Network Tests:"
echo "=================="

# Test 1: Basic internet connectivity
echo "1. Testing internet connectivity..."
if ping -c 2 8.8.8.8 >/dev/null 2>&1; then
    echo "   ✅ Internet connectivity: OK"
else
    echo "   ❌ Internet connectivity: FAILED"
    echo "   ⚠️  This machine has no internet access"
fi

# Test 2: DNS resolution
echo ""
echo "2. Testing DNS resolution..."
if [ -n "$JELLYFIN_BASE_URL" ]; then
    # Extract hostname from URL
    JELLYFIN_HOST=$(echo "$JELLYFIN_BASE_URL" | sed 's|https\?://||' | sed 's|:.*||' | sed 's|/.*||')
    echo "   Testing: $JELLYFIN_HOST"

    if nslookup "$JELLYFIN_HOST" >/dev/null 2>&1; then
        echo "   ✅ DNS resolution: OK"
        JELLYFIN_IP=$(nslookup "$JELLYFIN_HOST" | grep -A1 "Name:" | tail -n1 | awk '{print $2}')
        echo "   📍 Resolved to: $JELLYFIN_IP"
    else
        echo "   ❌ DNS resolution: FAILED"
        echo "   ⚠️  Cannot resolve $JELLYFIN_HOST"

        # Try with different DNS servers
        echo ""
        echo "   🔍 Trying different DNS servers..."
        for dns in "8.8.8.8" "1.1.1.1" "192.168.1.1"; do
            echo "     Testing with DNS: $dns"
            if nslookup "$JELLYFIN_HOST" "$dns" >/dev/null 2>&1; then
                echo "     ✅ Works with $dns"
            else
                echo "     ❌ Failed with $dns"
            fi
        done
    fi
fi

# Test 3: Jellyfin connectivity
echo ""
echo "3. Testing Jellyfin HTTP connectivity..."
if [ -n "$JELLYFIN_BASE_URL" ] && [ -n "$JELLYFIN_API_KEY" ]; then
    echo "   Testing: $JELLYFIN_BASE_URL/System/Info"

    # Test with curl
    HTTP_CODE=$(curl -s -w "%{http_code}" -o /dev/null \
        -H "Authorization: MediaBrowser Client=\"test\", Device=\"troubleshoot\", DeviceId=\"test-001\", Version=\"1.0\", Token=\"$JELLYFIN_API_KEY\"" \
        --connect-timeout 10 \
        --max-time 30 \
        "$JELLYFIN_BASE_URL/System/Info" 2>/dev/null)

    if [ "$HTTP_CODE" = "200" ]; then
        echo "   ✅ Jellyfin HTTP: OK (HTTP $HTTP_CODE)"
    elif [ "$HTTP_CODE" = "000" ]; then
        echo "   ❌ Jellyfin HTTP: CONNECTION FAILED"
        echo "   ⚠️  Cannot connect to $JELLYFIN_BASE_URL"
    else
        echo "   ⚠️  Jellyfin HTTP: HTTP $HTTP_CODE"
        if [ "$HTTP_CODE" = "401" ]; then
            echo "   🔐 Authentication failed - check API key"
        fi
    fi
else
    echo "   ⚠️  Missing JELLYFIN_BASE_URL or JELLYFIN_API_KEY"
fi

# Test 4: WLED connectivity
echo ""
echo "4. Testing WLED connectivity..."
if [ -n "$WLED_HOST" ]; then
    echo "   Testing: $WLED_HOST"

    # Test DNS resolution
    if nslookup "$WLED_HOST" >/dev/null 2>&1; then
        echo "   ✅ WLED DNS resolution: OK"

        # Test UDP port (basic connectivity)
        if nc -u -z -w 3 "$WLED_HOST" "${WLED_UDP_PORT:-21324}" 2>/dev/null; then
            echo "   ✅ WLED UDP port: REACHABLE"
        else
            echo "   ❌ WLED UDP port: NOT REACHABLE"
        fi
    else
        echo "   ❌ WLED DNS resolution: FAILED"
        echo "   ⚠️  Cannot resolve $WLED_HOST"
    fi
fi

echo ""
echo "🔧 SOLUTIONS:"
echo "============="

if ! nslookup "$JELLYFIN_HOST" >/dev/null 2>&1; then
    echo ""
    echo "❌ DNS Resolution Failed - Try these fixes:"
    echo ""
    echo "1️⃣  OPTION 1: Use IP address instead of hostname"
    echo "   Find your Jellyfin server IP and update env.homeserver:"
    echo "   JELLYFIN_BASE_URL=https://192.168.1.XXX:8920"
    echo ""
    echo "2️⃣  OPTION 2: Fix DNS configuration"
    echo "   Update DNS_SERVER in env.homeserver to use public DNS:"
    echo "   DNS_SERVER=8.8.8.8"
    echo ""
    echo "3️⃣  OPTION 3: Add to /etc/hosts (if running on host)"
    echo "   Add this line to /etc/hosts:"
    echo "   192.168.1.XXX    jellyfin.galagaon.com"
    echo ""
    echo "4️⃣  OPTION 4: Use Docker host networking"
    echo "   Add to docker-compose.yaml:"
    echo "   network_mode: host"
fi

if [ "$HTTP_CODE" = "000" ]; then
    echo ""
    echo "❌ Connection Failed - Check these:"
    echo ""
    echo "🔒 Is Jellyfin accessible from this network?"
    echo "🔥 Is there a firewall blocking port 443/8920?"
    echo "📡 Is the target machine on the same network?"
    echo "🌐 Is this a local-only Jellyfin server?"
fi

echo ""
echo "🚀 Quick Fix Commands:"
echo ""
echo "# Test with IP address:"
echo "JELLYFIN_BASE_URL=https://192.168.1.XXX:8920 ./docker-manager.sh test homeserver"
echo ""
echo "# Test with public DNS:"
echo "DNS_SERVER=8.8.8.8 ./docker-manager.sh test homeserver"
echo ""
echo "# Test connectivity manually:"
echo "docker run --rm curlimages/curl curl -I https://jellyfin.galagaon.com"
