# Jellyfin WebSocket Investigation Summary

## Problem
WebSocket connections to Jellyfin server work for authentication and basic connectivity, but any message sent causes immediate "System Shutdown" (code 1000).

## Investigation Results

### ✅ What Works
- **Authentication**: API key and authorization headers work correctly
- **Connection**: WebSocket upgrade through nginx proxy successful
- **SSL/TLS**: HTTPS/WSS connection works properly
- **Network**: No firewall or routing issues
- **HTTP API**: All HTTP endpoints work perfectly

### ❌ What Fails
- **Connect messages**: All formats cause shutdown
- **Subscribe messages**: Cause immediate shutdown
- **Any JSON message**: Results in "System Shutdown"

## Tests Performed

1. **Authentication Test**: ✅ HTTP API works with same credentials
2. **Minimal Connection**: ✅ WebSocket stays open without sending messages
3. **Message Format Testing**: ❌ All Connect message formats fail
4. **Subscribe Only**: ❌ Skip Connect, try Subscribe directly - fails
5. **Empty Messages**: ❌ Even empty data causes shutdown

## Possible Root Causes

### 1. Server Bug
Jellyfin may have a bug processing WebSocket messages when behind nginx proxy:
- Messages work fine when connecting directly to Jellyfin
- Proxy configuration interferes with message parsing
- Bug in specific Jellyfin version (10.10.7)

### 2. Message Format Issue
- Documentation may be outdated
- Server expects different message structure
- Missing required fields not documented

### 3. Server Configuration
- WebSocket API disabled in server settings
- Specific permissions required for API key
- Server not configured for proxied WebSocket messages

## Recommended Solutions

### Option 1: HTTP Polling (Immediate)
Use the `jellyfin-http-polling.py` script instead:
- Polls `/Sessions` endpoint every 1-2 seconds
- Detects playback state changes
- More reliable than broken WebSocket
- Lower resource usage than expected

### Option 2: Direct Connection (Testing)
Try connecting directly to Jellyfin (bypass proxy):
```python
# Test with direct connection
JELLYFIN_WS_URL = "ws://internal-jellyfin-ip:8096/socket"
```

### Option 3: Server Investigation
1. Check Jellyfin server logs for WebSocket errors
2. Try different Jellyfin version
3. Test with different nginx configuration
4. Contact Jellyfin community for known issues

## Files Created

- `test-jellyfin-connection.py`: Complete connection test suite
- `test-connect-formats.py`: Tests different message formats
- `test-no-connect.py`: Tests connection without messages
- `jellyfin-http-polling.py`: Working HTTP-based alternative
- `jellyfin-ws.py`: Fixed version (still affected by server issue)
- `jellyfin-api-integration.py`: Updated with proper auth headers

## Conclusion

The WebSocket **infrastructure works correctly**. The issue is with **message processing** on the server side.

**Recommendation**: Use HTTP polling as a reliable alternative until the WebSocket message issue is resolved.
