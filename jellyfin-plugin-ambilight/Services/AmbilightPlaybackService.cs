using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Session;
using MediaBrowser.Model.Session;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// Playback/session integration that mirrors the Python player daemon:
/// - Watches Jellyfin sessions
/// - Chooses a WLED target for each session
/// - Starts/stops the Rust ambilight-player process
/// - Sends PAUSE/RESUME/SEEK/STOP commands over stdin.
/// </summary>
public class AmbilightPlaybackService
{
    private readonly ILogger<AmbilightPlaybackService> _logger;
    private readonly ISessionManager _sessionManager;
    private readonly ILibraryManager _libraryManager;
    private readonly AmbilightStorageService _storage;
    private readonly PluginConfiguration _config;

    // In-process C# players, keyed by session Id.
    private readonly ConcurrentDictionary<string, AmbilightInProcessPlayer> _sessionPlayers = new();
    private readonly ConcurrentDictionary<string, double> _lastPositionSeconds = new();

    public AmbilightPlaybackService(
        ILogger<AmbilightPlaybackService> logger,
        ISessionManager sessionManager,
        ILibraryManager libraryManager,
        AmbilightStorageService storage,
        PluginConfiguration config)
    {
        _logger = logger;
        _sessionManager = sessionManager;
        _libraryManager = libraryManager;
        _storage = storage;
        _config = config;
    }

    public void OnPlaybackStart(SessionInfo session, PlaybackProgressInfo info)
    {
        try
        {
            var debug = _config.Debug;

            if (debug)
            {
                _logger.LogInformation("[Ambilight] Play detected for session {SessionId}, item {ItemId}", session.Id, info.ItemId);
            }

            if (!IsDeviceAllowed(session))
            {
                var devName = session.DeviceName ?? "(unknown device)";
                var clientName = session.Client ?? "(unknown client)";
                if (debug)
                {
                    _logger.LogInformation(
                        "[Ambilight] Skip: device {DeviceId} [{DeviceName}] ({Client}) not in allowed list.",
                        session.DeviceId,
                        devName,
                        clientName);
                }
                else
                {
                    _logger.LogDebug(
                        "[Ambilight] Device {DeviceId} [{DeviceName}] ({Client}) is not in allowed list; skipping ambilight.",
                        session.DeviceId,
                        devName,
                        clientName);
                }
                return;
            }

            var item = _libraryManager.GetItemById(info.ItemId);
            if (item == null || item.Path is null)
            {
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Skip: item not found or has no path (ItemId={ItemId}).", info.ItemId);
                }
                return;
            }

            var itemIdStr = item.Id.ToString("N");
            var binPath = _storage.GetBinaryPath(itemIdStr);
            if (debug)
            {
                _logger.LogInformation("[Ambilight] Looking for binary at {BinPath} for item {ItemId}", binPath, itemIdStr);
            }
            if (!File.Exists(binPath))
            {
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Skip: binary file not found at {BinPath}", binPath);
                }
                else
                {
                    _logger.LogInformation("[Ambilight] No .bin file for item {ItemName}", item.Name);
                }
                return;
            }

            var target = ResolveWledTarget(session);
            if (target is null)
            {
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Skip: no WLED target (set Default WLED host or device mapping).");
                }
                else
                {
                    _logger.LogDebug("[Ambilight] No WLED mapping for this session; skipping ambilight.");
                }
                return;
            }

            var (host, port) = target.Value;
            if (debug)
            {
                _logger.LogInformation("[Ambilight] Binary found at {BinPath}, connecting to WLED {Host}:{Port}", binPath, host, port);
            }

            var startSeconds = (info.PositionTicks ?? 0) / 10_000_000.0;
            StartPlayerForSession(session.Id, binPath, host, port, startSeconds);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[Ambilight] Error handling PlaybackStart");
        }
    }

    public void OnPlaybackStopped(SessionInfo session, PlaybackStopInfo info)
    {
        if (_config.Debug)
        {
            _logger.LogInformation("[Ambilight] Stop detected for session {SessionId}", session.Id);
        }
        StopPlayerForSession(session.Id);
    }

    public void OnPlaybackProgress(SessionInfo session, PlaybackProgressInfo info)
    {
        if (!_sessionPlayers.ContainsKey(session.Id))
        {
            return;
        }

        if (_sessionPlayers.TryGetValue(session.Id, out var inProc))
        {
            var positionTicks = info.PositionTicks ?? 0;
            var currSeconds = positionTicks / 10_000_000.0;
            var paused = info.IsPaused is true;

            inProc.SetPaused(paused);

            var last = _lastPositionSeconds.GetOrAdd(session.Id, currSeconds);
            _lastPositionSeconds[session.Id] = currSeconds;

            // Detect significant jumps (seek) – keep threshold small so manual skips resync quickly
            if (Math.Abs(currSeconds - last) > 0.5)
            {
                if (_config.Debug)
                {
                    _logger.LogInformation("[Ambilight] Seek detected for session {SessionId} to {Seconds:F1}s", session.Id, currSeconds);
                }
                inProc.Seek(currSeconds);
            }
        }
    }

    private bool IsDeviceAllowed(SessionInfo session)
    {
        var allowed = _config.AllowedDeviceIds;
        if (allowed == null || allowed.Count == 0)
        {
            // No restriction configured: allow all devices
            return true;
        }

        var deviceId = session.DeviceId;
        if (string.IsNullOrEmpty(deviceId))
        {
            // Missing DeviceId, treat as allowed to avoid surprising breakage
            return true;
        }

        // Match against known device Ids from /Devices (case-insensitive).
        return allowed.Any(id => string.Equals(id, deviceId, StringComparison.OrdinalIgnoreCase));
    }

    private (string host, int port)? ResolveWledTarget(SessionInfo session)
    {
        var deviceField = _config.DeviceMatchField ?? "DeviceName";
        var deviceValue = GetSessionField(session, deviceField) ?? session.DeviceName ?? string.Empty;
        var norm = Normalize(deviceValue);

        foreach (var mapping in _config.DeviceMappings)
        {
            if (string.IsNullOrWhiteSpace(mapping.DeviceIdentifier))
            {
                continue;
            }

            if (norm.Contains(Normalize(mapping.DeviceIdentifier)))
            {
                return (mapping.Host, mapping.Port);
            }
        }

        if (!string.IsNullOrWhiteSpace(_config.DefaultWledHost))
        {
            return (_config.DefaultWledHost, _config.DefaultWledUdpPort);
        }

        return null;
    }

    private static string Normalize(string value)
    {
        var lower = value.ToLowerInvariant();
        var chars = lower.Where(char.IsLetterOrDigit).ToArray();
        return new string(chars);
    }

    private static string? GetSessionField(SessionInfo session, string fieldName)
    {
        // Simple reflection-based lookup so we can support arbitrary fields like DeviceName, Client, etc.
        var prop = typeof(SessionInfo).GetProperty(fieldName);
        return prop?.GetValue(session)?.ToString();
    }

    private void StartPlayerForSession(string sessionId, string binPath, string host, int port, double startSeconds)
    {
        StopPlayerForSession(sessionId);

        var player = new AmbilightInProcessPlayer(_logger, _config);
        player.Start(sessionId, binPath, host, port, startSeconds);
        _sessionPlayers[sessionId] = player;
        _logger.LogInformation("[Ambilight] Started in-process player for session {SessionId} → {Host}:{Port}", sessionId, host, port);
    }

    private void StopPlayerForSession(string sessionId)
    {
        if (!_sessionPlayers.TryRemove(sessionId, out var inProc))
        {
            return;
        }

        inProc.Stop();
        inProc.Dispose();
        _logger.LogInformation("[Ambilight] Stopped in-process player for session {SessionId}", sessionId);
    }
}
