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
    private readonly ConcurrentDictionary<string, CancellationTokenSource> _loadingEffectCancellations = new();

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
            
            // Calculate total LEDs for effects
            int totalLeds = _config.AmbilightTopLedCount + _config.AmbilightBottomLedCount + 
                           _config.AmbilightLeftLedCount + _config.AmbilightRightLedCount;
            
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
                
                // Show failure flash on WLED
                _ = AmbilightInProcessPlayer.SendFailureFlashAsync(host, port, totalLeds, _logger);
                return;
            }
            
            // Start loading effect before starting player
            var loadingCts = new CancellationTokenSource();
            _loadingEffectCancellations[session.Id] = loadingCts;
            _ = AmbilightInProcessPlayer.SendLoadingEffectAsync(host, port, totalLeds, _logger, loadingCts.Token);
            
            if (debug)
            {
                _logger.LogInformation("[Ambilight] Binary found at {BinPath}, connecting to WLED {Host}:{Port}", binPath, host, port);
            }

            var startSeconds = (info.PositionTicks ?? 0) / 10_000_000.0;
            
            // Try to start player
            bool success = StartPlayerForSession(session.Id, binPath, host, port, startSeconds);
            
            // Stop loading effect
            StopLoadingEffect(session.Id);
            
            // Show failure flash if player didn't start
            if (!success)
            {
                _ = AmbilightInProcessPlayer.SendFailureFlashAsync(host, port, totalLeds, _logger);
            }
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
        
        // Stop loading effect if still running
        StopLoadingEffect(session.Id);
        
        // Stop player
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
        var deviceName = session.DeviceName ?? string.Empty;
        var clientName = session.Client ?? string.Empty;

        if (_config.Debug)
        {
            var list = string.Join(", ", allowed);
            _logger.LogInformation(
                "[Ambilight] Device gating: session DeviceId={DeviceId}, Name={DeviceName}, Client={Client}; Allowed={Allowed}",
                deviceId,
                deviceName,
                clientName,
                list);
        }

        // If Jellyfin doesn't provide a DeviceId, don't unexpectedly block playback.
        if (string.IsNullOrEmpty(deviceId) && string.IsNullOrEmpty(deviceName) && string.IsNullOrEmpty(clientName))
        {
            return true;
        }

        // We accept a match on any of the common identifiers so that older configs
        // (that may have stored names or clients) keep working.
        bool Match(string a, string b) =>
            !string.IsNullOrEmpty(a) &&
            !string.IsNullOrEmpty(b) &&
            string.Equals(a, b, StringComparison.OrdinalIgnoreCase);

        // For DeviceId, strip session timestamps before comparing
        // Jellyfin Web client DeviceIds are base64(UserAgent|timestamp), so we need fuzzy matching
        string StripDeviceIdTimestamp(string deviceId)
        {
            if (string.IsNullOrEmpty(deviceId))
            {
                return deviceId;
            }

            // Try to decode if it looks like base64 and strip the timestamp after the pipe
            try
            {
                var decoded = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(deviceId));
                var pipeIndex = decoded.LastIndexOf('|');
                if (pipeIndex > 0 && decoded.Length - pipeIndex <= 20) // timestamp is typically 13-20 chars
                {
                    var withoutTimestamp = decoded.Substring(0, pipeIndex);
                    return Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(withoutTimestamp));
                }
            }
            catch
            {
                // Not base64 or decode failed, return as-is
            }

            return deviceId;
        }

        var normalizedDeviceId = StripDeviceIdTimestamp(deviceId);

        foreach (var entry in allowed)
        {
            var normalizedEntry = StripDeviceIdTimestamp(entry);
            if (Match(normalizedEntry, normalizedDeviceId) || Match(entry, deviceName) || Match(entry, clientName))
            {
                return true;
            }
        }

        return false;
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

    private bool StartPlayerForSession(string sessionId, string binPath, string host, int port, double startSeconds)
    {
        try
        {
            StopPlayerForSession(sessionId);

            var player = new AmbilightInProcessPlayer(_logger, _config);
            player.Start(sessionId, binPath, host, port, startSeconds);
            _sessionPlayers[sessionId] = player;
            _logger.LogInformation("[Ambilight] Started in-process player for session {SessionId} → {Host}:{Port}", sessionId, host, port);
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[Ambilight] Failed to start player for session {SessionId}", sessionId);
            return false;
        }
    }

    private void StopLoadingEffect(string sessionId)
    {
        if (_loadingEffectCancellations.TryRemove(sessionId, out var cts))
        {
            try
            {
                cts.Cancel();
                cts.Dispose();
            }
            catch
            {
                // Ignore cancellation errors
            }
        }
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
