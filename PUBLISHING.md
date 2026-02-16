# Publishing Guide

This guide explains how to publish new releases of the Jellyfin Ambilight Plugin.

## Prerequisites

- Push access to the GitHub repository
- Git configured locally
- .NET 8 SDK installed

## Release Process

### 1. Update Version Numbers

Update the version in these files:

1. **Jellyfin.Plugin.Ambilight.csproj**
   ```xml
   <AssemblyVersion>1.0.0.0</AssemblyVersion>
   <FileVersion>1.0.0.0</FileVersion>
   ```

2. **CHANGELOG.md**
   - Add a new section for the version
   - List all changes since last release

### 2. Commit Changes

```bash
git add .
git commit -m "Release v1.0.0.0"
git push origin master
```

### 3. Create and Push Tag

```bash
git tag v1.0.0.0
git push origin v1.0.0.0
```

This will automatically trigger the GitHub Actions workflow that:
- Builds the plugin
- Creates a release package (zip file)
- Calculates the MD5 checksum
- Creates a GitHub release
- Uploads the package as a release asset

### 4. Manifest.json is Updated Automatically

The manifest.json file is **automatically updated** by a GitHub Actions workflow when you publish a release. The workflow will:

1. Download the release zip file
2. Calculate the MD5 checksum
3. Update manifest.json with the new version, checksum, and timestamp
4. Commit and push the changes

**No manual action required!** Just wait a minute after publishing the release for the workflow to complete.

## Adding New Versions

When releasing a new version, add it to the `versions` array in `manifest.json`:

```json
{
  "version": "1.1.0.0",
  "changelog": "Description of changes",
  "targetAbi": "10.10.0.0",
  "sourceUrl": "https://github.com/gabrielprat/jellyfin-ambilight/releases/download/v1.1.0.0/jellyfin-plugin-ambilight_1.1.0.0.zip",
  "checksum": "md5-checksum-here",
  "timestamp": "2026-03-01T00:00:00Z"
}
```

Keep older versions in the array so users can downgrade if needed.

## Repository URL

Users can add your plugin repository to Jellyfin:

**Repository URL:** `https://raw.githubusercontent.com/gabrielprat/jellyfin-ambilight/master/manifest.json`

## Verification

After publishing, verify:
1. Release appears on GitHub releases page
2. Zip file is attached to release
3. Manifest.json is accessible at the raw GitHub URL
4. Plugin can be installed from the repository in Jellyfin
