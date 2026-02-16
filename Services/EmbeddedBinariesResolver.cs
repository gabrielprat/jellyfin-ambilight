using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using MediaBrowser.Common.Configuration;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// Resolves paths to the ambilight-extractor binary.
/// If the plugin has an embedded binary for the current platform, extracts it to a plugin bin directory.
/// Otherwise falls back to config path or default /usr/local/bin.
/// </summary>
public class EmbeddedBinariesResolver
{
    private const string ResourcePrefix = "Jellyfin.Plugin.Ambilight.Binaries.";
    private const string ExtractorName = "ambilight-extractor";

    private readonly IApplicationPaths _appPaths;
    private readonly PluginConfiguration _config;
    private readonly ILogger _logger;
    private string? _binDir;
    private string? _resolvedExtractorPath;

    public EmbeddedBinariesResolver(
        IApplicationPaths appPaths,
        PluginConfiguration config,
        ILogger logger)
    {
        _appPaths = appPaths;
        _config = config;
        _logger = logger;
    }

    /// <summary>
    /// Gets the path to use for the extractor. If config has RustExtractorPath, uses that.
    /// Otherwise tries to use an embedded binary for the current platform.
    /// </summary>
    public string GetExtractorPath()
    {
        if (!string.IsNullOrWhiteSpace(_config.RustExtractorPath))
        {
            return _config.RustExtractorPath!;
        }

        if (_resolvedExtractorPath != null)
        {
            return _resolvedExtractorPath;
        }

        _resolvedExtractorPath = TryGetEmbeddedBinaryPath(ExtractorName);
        if (_resolvedExtractorPath != null)
        {
            _logger.LogInformation("[Ambilight] Using embedded extractor at {Path}", _resolvedExtractorPath);
            return _resolvedExtractorPath;
        }

        _resolvedExtractorPath = "/usr/local/bin/ambilight-extractor";
        _logger.LogDebug("[Ambilight] No embedded extractor for this platform; using default {Path}", _resolvedExtractorPath);
        return _resolvedExtractorPath;
    }

    private string? TryGetEmbeddedBinaryPath(string binaryName)
    {
        var rid = GetRuntimeId();
        var name = GetBinaryFileName(binaryName, rid);
        var resourceName = ResourcePrefix + rid + "." + name;

        var assembly = Assembly.GetExecutingAssembly();
        using var stream = assembly.GetManifestResourceStream(resourceName);
        if (stream == null)
        {
            _logger.LogDebug("[Ambilight] No embedded binary resource {Resource}", resourceName);
            return null;
        }

        var binDir = GetOrCreateBinDirectory();
        var targetPath = Path.Combine(binDir, name);

        try
        {
            if (File.Exists(targetPath))
            {
                return targetPath;
            }

            using (var fs = File.Create(targetPath))
            {
                stream.CopyTo(fs);
            }

            SetExecutable(targetPath);
            return targetPath;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[Ambilight] Failed to extract embedded binary to {Path}", targetPath);
            try { File.Delete(targetPath); } catch { }
            return null;
        }
    }

    private string GetOrCreateBinDirectory()
    {
        if (_binDir != null)
        {
            return _binDir;
        }

        _binDir = Path.Combine(_appPaths.DataPath, "plugins", "Ambilight", "bin");
        try
        {
            if (!Directory.Exists(_binDir))
            {
                Directory.CreateDirectory(_binDir);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[Ambilight] Could not create plugin bin directory {Path}", _binDir);
        }

        return _binDir;
    }

    private static string GetRuntimeId()
    {
        var os = "linux";
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            os = "win";
        }
        else if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            os = "osx";
        }

        var arch = RuntimeInformation.ProcessArchitecture switch
        {
            Architecture.Arm64 => "arm64",
            Architecture.Arm => "arm",
            Architecture.X64 => "x64",
            Architecture.X86 => "x86",
            _ => "x64"
        };

        return os + "-" + arch;
    }

    private static string GetBinaryFileName(string baseName, string rid)
    {
        if (rid.StartsWith("win-", StringComparison.Ordinal))
        {
            return baseName + ".exe";
        }
        return baseName;
    }

    private static void SetExecutable(string path)
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return;
        }

        try
        {
            File.SetUnixFileMode(path,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                | UnixFileMode.GroupRead | UnixFileMode.GroupExecute
                | UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
        }
        catch (Exception)
        {
            // Best effort; process might still run on some systems
        }
    }
}
