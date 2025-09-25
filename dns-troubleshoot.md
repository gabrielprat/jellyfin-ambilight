# DNS Resolution Issues - Solutions

## 🔍 Problem Analysis

The error `Failed to resolve 'jellyfin.galagaon.com'` occurs intermittently during library scanning, suggesting:

1. **DNS caching issues** in Docker custom networks
2. **Network isolation** preventing external DNS resolution
3. **DNS server overload** during heavy API calls

## 🚀 Solutions (Try in Order)

### Solution 1: Use Host Networking (Recommended)
This bypasses Docker's DNS entirely:

```yaml
# In docker-compose.yml, replace networks section with:
network_mode: host

# Remove the networks section entirely
```

### Solution 2: Add Local IP Resolution
If you know your Jellyfin server's local IP:

```bash
# In .env file, add:
JELLYFIN_LOCAL_IP=192.168.1.XXX

# This creates a hosts entry: jellyfin.galagaon.com -> 192.168.1.XXX
```

### Solution 3: Use Multiple DNS Servers (Already Applied)
The compose file now includes multiple DNS fallbacks:

```yaml
dns:
  - 192.168.1.191  # Your homelab DNS
  - 8.8.8.8        # Google (fallback)
  - 1.1.1.1        # Cloudflare (fallback)
```

### Solution 4: Test DNS Resolution
Check if the container can resolve the hostname:

```bash
# Test DNS resolution in container
docker exec jellyfin-ambilight nslookup jellyfin.galagaon.com

# Test with different DNS servers
docker exec jellyfin-ambilight nslookup jellyfin.galagaon.com 8.8.8.8
```

## 🎯 Quick Fix (Recommended)

**Use host networking** - this is the most reliable solution:

1. **Edit docker-compose.yml:**
   ```yaml
   services:
     jellyfin-ambilight:
       # ... other config ...
       network_mode: host  # Add this line
       # Remove the networks: section entirely
   ```

2. **Remove network configuration:**
   ```yaml
   # Delete this entire section:
   # networks:
   #   homelab-network:
   #     ipv4_address: 10.1.0.20
   ```

3. **Keep DNS config** (optional with host networking):
   ```yaml
   dns:
     - 192.168.1.191
     - 8.8.8.8
   ```

## 🔄 Alternative: Restart Strategy

If you prefer keeping custom networking, add automatic restart on DNS failures:

```yaml
restart: always  # Already set to unless-stopped
healthcheck:
  test: ["CMD", "nslookup", "jellyfin.galagaon.com"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## 🏠 Homelab Considerations

For homelab setups, **host networking is often preferred** because:
- ✅ No DNS resolution issues
- ✅ Direct access to local services
- ✅ Simpler configuration
- ✅ Better performance
- ❌ Loses network isolation (security consideration)

**Recommendation**: Try host networking first - it's the most reliable solution for homelab environments.
