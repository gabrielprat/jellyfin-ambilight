# Tech Stack

## Runtime

| Component | Version |
|---|---|
| Target framework | .NET 8 (`net8.0`) |
| Language | C# 12 (nullable reference types, implicit usings) |
| Jellyfin SDK | `10.10.*` (pinned, `PrivateAssets="All"`) |
| NuGet restore | nuget.org only, no lockfile |

## Project structure

- **Single project**, no solution file (`Jellyfin.Plugin.Ambilight.csproj`)
- **13 C# source files** across `Server/`, `Services/`, `Api/`, `Tasks/`
- **Embedded resources:** `Configuration/configPage.html` (config UI)
- **License:** GPL-3.0-or-later

## Key dependencies (all shipped as PrivateAssets)

| Package | Purpose |
|---|---|
| `Jellyfin.Model` | Plugin base types, `BasePlugin<T>`, `IHasWebPages` |
| `Jellyfin.Controller` | `IPluginServiceRegistrator`, `IHostedService` hosting |

## External tools (runtime)

| Tool | Purpose | Resolution |
|---|---|---|
| `ffmpeg` | Video → raw RGB24 frames | PATH, `/usr/lib/jellyfin-ffmpeg/`, `/usr/bin/` |
| `ffprobe` | FPS + duration probing | Same paths as ffmpeg |

## No-dependency compression

- `System.IO.Compression.DeflateStream` — AMb3 chapter compression
- No LZ4, Zstd, or other third-party libraries

## Binary format versions

| Format | Magic | Status |
|---|---|---|
| AMb2 | `"AMb2"` | Legacy, fully supported for playback |
| AMb3 | `"AMb3"` | Current, used for all new extractions |

## Conventions

- GPL-3.0 license headers on all `.cs` files
- Nullable reference types enabled project-wide
- Implicit usings enabled
- No test suite, linter, or formatter
- Build verification: `dotnet restore && dotnet build --no-restore --configuration Release` must produce 0 warnings, 0 errors
- Git flow: `master` (stable), `devel` (integration), `feature/*` (work branches)
- Config values read directly from `Plugin.Instance?.Configuration` — no caching layer

## Platform support

| Platform | Arch | Notes |
|---|---|---|
| Linux | x64, arm64 | Primary target (Docker) |
| macOS | arm64, x64 | Development |
| Windows | x64 | Community support |

## Storage layout

```
{AmbilightDataFolder}/          (default: /data/ambilight)
├── {itemId}.ambilight.json     (metadata)
└── {itemId}.bin                (AMb2 or AMb3 binary data)
```
