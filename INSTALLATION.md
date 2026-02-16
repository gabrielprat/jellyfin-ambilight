# Installation Guide

## Quick Install

1. **Download** the latest `jellyfin-plugin-ambilight_x.x.x.x.zip` from [Releases](https://github.com/gabrielprat/jellyfin-ambilight/releases)
2. **Extract** the zip file
3. **Copy** the `Jellyfin.Plugin.Ambilight` folder to your Jellyfin plugins directory:
   - Linux: `/var/lib/jellyfin/plugins/`
   - Windows: `C:\ProgramData\Jellyfin\Server\plugins\`
   - Docker: `/config/plugins/`
4. **Restart** Jellyfin

## Docker Installation

If running Jellyfin in Docker, you also need to add a volume for ambilight data:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin
    volumes:
      - /path/to/config:/config
      - /path/to/ambilight-data:/config/data/ambilight  # Add this line
```

Or with docker run:
```bash
docker run -v /path/to/ambilight-data:/config/data/ambilight jellyfin/jellyfin
```

## Adding the Plugin Repository (Optional)

You can add this repository to Jellyfin for easier updates:

1. Go to **Dashboard** → **Plugins** → **Repositories**
2. Click **Add Repository**
3. Enter:
   - **Repository Name**: Ambilight Plugin
   - **Repository URL**: `https://raw.githubusercontent.com/gabrielprat/jellyfin-ambilight/master/manifest.json`
4. Save and go to **Catalog**
5. Find **Ambilight** and click **Install**

## Verification

After installation:
1. Go to **Dashboard** → **Plugins**
2. You should see **Ambilight** in the list
3. Click **Settings** to configure

## Next Steps

See the [README](README.md) for configuration instructions.
