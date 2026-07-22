---
description: Build the Jellyfin Ambilight plugin
---

Run the following build commands (clean build to ensure fresh output):

```bash
dotnet clean --configuration Release 2>&1 && dotnet restore && dotnet build --no-restore --configuration Release
```

If the build fails, analyze the errors and suggest fixes.

If it succeeds, show the compiled plugin path and timestamp:

```bash
ls -la bin/Release/net8.0/Jellyfin.Plugin.Ambilight.dll
```

Report 0 warnings, 0 errors, and the full path to the compiled DLL.
