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

    // In-process C# players, keyed by session Id. Each session can have multiple players for multiple WLED instances.
    private readonly ConcurrentDictionary<string, List<AmbilightInProcessPlayer>> _sessionPlayers = new();
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
                _logger.LogInformation("[Ambilight] Play detected for session {SessionId}, item {ItemId}, device {DeviceName}", 
                    session.Id, info.ItemId, session.DeviceName ?? session.DeviceId);
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
            
            var targets = ResolveWledTargets(session);
            if (targets.Count == 0)
            {
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Skip: no WLED mapping configured for device {DeviceName} (ID: {DeviceId}). Add a device mapping in plugin settings.",
                        session.DeviceName ?? "(unknown)",
                        session.DeviceId);
                }
                return;
            }

            if (debug)
            {
                var wledList = string.Join(", ", targets.Select(t => $"{t.Host}:{t.Port}"));
                _logger.LogInformation("[Ambilight] Device {DeviceName} → {Count} WLED target(s): {Targets}", 
                    session.DeviceName ?? session.DeviceId, targets.Count, wledList);
            }
            
            if (!File.Exists(binPath))
            {
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Skip: binary file not found at {BinPath}", binPath);
                }
                
                // Show failure flash on all WLED instances
                foreach (var mapping in targets)
                {
                    int ledCount = mapping.TopLedCount + mapping.BottomLedCount + mapping.LeftLedCount + mapping.RightLedCount;
                    _ = AmbilightInProcessPlayer.SendFailureFlashAsync(mapping.Host, mapping.Port, ledCount, _logger);
                }
                return;
            }
            
            // Start loading effect on all targets before starting player
            var loadingCts = new CancellationTokenSource();
            _loadingEffectCancellations[session.Id] = loadingCts;
            
            foreach (var mapping in targets)
            {
                int ledCount = mapping.TopLedCount + mapping.BottomLedCount + mapping.LeftLedCount + mapping.RightLedCount;
                
                if (debug)
                {
                    _logger.LogInformation("[Ambilight] Starting loading effect on WLED {Host}:{Port} ({Leds} LEDs)", 
                        mapping.Host, mapping.Port, ledCount);
                }
                
                _ = AmbilightInProcessPlayer.SendLoadingEffectAsync(mapping.Host, mapping.Port, ledCount, _logger, loadingCts.Token);
            }
            
            if (debug)
            {
                _logger.LogInformation("[Ambilight] Binary found at {BinPath}, connecting to {Count} WLED instance(s)", binPath, targets.Count);
            }

            var startSeconds = (info.PositionTicks ?? 0) / 10_000_000.0;
            
            // Try to start players for all targets (this is async, returns immediately)
            // Pass the loading effect cancellation token so the player can stop it when ready
            bool success = StartPlayersForSession(session.Id, binPath, targets, startSeconds, loadingCts);
            
            // Don't stop loading effect here - let the player stop it when it actually starts broadcasting
            // The loading effect will be stopped by the player in RunAsync or on playback stop
            
            // Show failure flash if player didn't start at all (immediate failure)
            if (!success)
            {
                StopLoadingEffect(session.Id);
                foreach (var mapping in targets)
                {
                    int totalLeds = mapping.TopLedCount + mapping.BottomLedCount + mapping.LeftLedCount + mapping.RightLedCount;
                    _ = AmbilightInProcessPlayer.SendFailureFlashAsync(mapping.Host, mapping.Port, totalLeds, _logger);
                }
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
        
        // Stop players
        StopPlayersForSession(session.Id);
    }

    public void OnPlaybackProgress(SessionInfo session, PlaybackProgressInfo info)
    {
        if (!_sessionPlayers.TryGetValue(session.Id, out var players) || players.Count == 0)
        {
            return;
        }

        foreach (var inProc in players)
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

    // Device access is now controlled entirely by device mappings
    // Any device with at least one WLED mapping will have ambilight enabled

    private List<DeviceMapping> ResolveWledTargets(SessionInfo session)
    {
        var targets = new List<DeviceMapping>();
        var seenTargets = new HashSet<(string host, int port)>();
        
        // Get session identifiers
        var deviceId = session.DeviceId ?? string.Empty;
        var deviceName = session.DeviceName ?? string.Empty;
        
        // Normalize deviceId by stripping timestamp (Jellyfin web clients use base64(UserAgent|timestamp))
        var normalizedDeviceId = StripDeviceIdTimestamp(deviceId);

        // Find all matching device mappings
        foreach (var mapping in _config.DeviceMappings)
        {
            if (string.IsNullOrWhiteSpace(mapping.DeviceIdentifier) || string.IsNullOrWhiteSpace(mapping.Host))
            {
                continue;
            }

            var isMatch = false;
            
            // Try exact DeviceId match first
            if (!string.IsNullOrWhiteSpace(deviceId))
            {
                var normalizedMappingId = StripDeviceIdTimestamp(mapping.DeviceIdentifier);
                isMatch = string.Equals(normalizedMappingId, normalizedDeviceId, StringComparison.OrdinalIgnoreCase);
            }
            
            // Fallback to DeviceName matching
            if (!isMatch && !string.IsNullOrWhiteSpace(deviceName))
            {
                isMatch = string.Equals(mapping.DeviceIdentifier, deviceName, StringComparison.OrdinalIgnoreCase) ||
                         Normalize(deviceName).Contains(Normalize(mapping.DeviceIdentifier));
            }

            if (isMatch)
            {
                var targetKey = (mapping.Host, mapping.Port);
                // Avoid duplicate WLED instances (but preserve the full mapping with LED config)
                if (!seenTargets.Contains(targetKey))
                {
                    targets.Add(mapping);
                    seenTargets.Add(targetKey);
                }
            }
        }

        return targets;
    }
    
    private static string StripDeviceIdTimestamp(string deviceId)
    {
        if (string.IsNullOrWhiteSpace(deviceId))
        {
            return deviceId;
        }

        // Jellyfin Web client DeviceIds are base64(UserAgent|timestamp)
        // We need to strip the timestamp for consistent matching across sessions
        try
        {
            var decoded = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(deviceId));
            var pipeIndex = decoded.LastIndexOf('|');
            
            // If we find a pipe and the part after it looks like a timestamp (10-20 chars, typically)
            if (pipeIndex > 0 && decoded.Length - pipeIndex <= 20)
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

    private bool StartPlayersForSession(string sessionId, string binPath, List<DeviceMapping> targets, double startSeconds, CancellationTokenSource? loadingEffectCts = null)
    {
        try
        {
            StopPlayersForSession(sessionId);

            var players = new List<AmbilightInProcessPlayer>();
            
            foreach (var mapping in targets)
            {
                var player = new AmbilightInProcessPlayer(_logger, _config);
                player.Start(sessionId, binPath, mapping, startSeconds, loadingEffectCts);
                players.Add(player);
                
                if (_config.Debug)
                {
                    int totalLeds = mapping.TopLedCount + mapping.BottomLedCount + mapping.LeftLedCount + mapping.RightLedCount;
                    _logger.LogInformation("[Ambilight] Started player for session {SessionId} → {Host}:{Port} ({Leds} LEDs: T{Top} B{Bottom} L{Left} R{Right})", 
                        sessionId, mapping.Host, mapping.Port, totalLeds, 
                        mapping.TopLedCount, mapping.BottomLedCount, mapping.LeftLedCount, mapping.RightLedCount);
                }
            }
            
            _sessionPlayers[sessionId] = players;
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "[Ambilight] Failed to start players for session {SessionId}", sessionId);
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

    private void StopPlayersForSession(string sessionId)
    {
        if (!_sessionPlayers.TryRemove(sessionId, out var players) || players.Count == 0)
        {
            return;
        }

        foreach (var player in players)
        {
            player.Stop();
            player.Dispose();
        }
        
        if (_config.Debug)
        {
            _logger.LogInformation("[Ambilight] Stopped {Count} in-process player(s) for session {SessionId}", players.Count, sessionId);
        }
    }
}
