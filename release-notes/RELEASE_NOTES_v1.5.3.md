# Release Notes - v1.5.3

## 🐛 Bug Fixes

This patch release fixes a critical workflow issue and ensures proper plugin distribution.

### Fixed GitHub Actions Workflow

**Problem:** The GitHub Actions workflow was incorrectly handling `manifest.json`:
- `manifest.json` was in `.gitignore`, preventing Jellyfin from fetching plugin updates
- Workflow failed when trying to checkout the master branch due to file conflicts
- Releases were not being created properly

**Solution:**
- ✅ Removed `manifest.json` from `.gitignore` - it must be tracked for Jellyfin to detect updates
- ✅ Simplified workflow to avoid file conflicts during branch checkout
- ✅ Ensured release creation and manifest updates work correctly

**Impact:**
- Jellyfin can now properly detect and display plugin updates
- GitHub releases are created successfully
- `manifest.json` is automatically updated on each release

### Maintained Hardware Acceleration Fix

All hardware acceleration fixes from v1.5.1 remain in place:
- ✅ Intel Quick Sync (QSV) working with `yuv420p` format
- ✅ VAAPI working correctly
- ✅ CUDA acceleration fixed
- ✅ VideoToolbox acceleration fixed

## 📝 What Changed from v1.5.1

- Fixed GitHub Actions workflow for proper release handling
- Restored `manifest.json` to Git tracking (required for Jellyfin updates)
- No code changes to plugin functionality

## 📝 Migration Notes

### For Users

**Recommended upgrade:**

1. Download v1.5.3 from the releases page
2. Replace `Jellyfin.Plugin.Ambilight.dll` in your plugins folder
3. Restart Jellyfin

This release ensures future updates will be properly detected by Jellyfin's plugin system.

### For Plugin Distribution

`manifest.json` is now properly tracked and automatically updated by CI/CD, allowing Jellyfin to:
- Detect new plugin versions
- Display changelog information
- Download updates automatically

## 🔗 Links

- **Full Changelog**: https://github.com/gabrielprat/jellyfin-ambilight/compare/v1.5.1...v1.5.3
- **Previous Release**: [v1.5.1](RELEASE_NOTES_v1.5.1.md)
- **Installation Guide**: [README.md](../README.md#installation)

---

**Update recommended for proper plugin update detection!** 🚀
