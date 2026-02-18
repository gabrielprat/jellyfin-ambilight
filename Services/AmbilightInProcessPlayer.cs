// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight;
using Microsoft.Extensions.Logging;
using static Jellyfin.Plugin.Ambilight.PluginConfiguration;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// In-process implementation of the ambilight-player logic in C#.
/// Reads AMb2 binaries and streams frames over UDP to WLED, applying the same
/// gamma/saturation/brightness/smoothing logic as the Rust player.
/// </summary>
public sealed class AmbilightInProcessPlayer : IDisposable
{
    private readonly ILogger _logger;
    private readonly PluginConfiguration _config;

    private CancellationTokenSource? _cts;
    private Task? _playTask;
    private CancellationTokenSource? _loadingEffectCts;

    // Shared state controlled by PlaybackService via SetPaused/Seek while RunAsync is looping.
    private readonly object _stateLock = new();
    private bool _isPaused;
    private double? _pendingSeekSeconds;

    public AmbilightInProcessPlayer(ILogger logger, PluginConfiguration config)
    {
        _logger = logger;
        _config = config;
    }

    public void Start(string sessionId, string binPath, DeviceMapping mapping, double startSeconds, CancellationTokenSource? loadingEffectCts = null)
    {
        Stop();
        
        _loadingEffectCts = loadingEffectCts;
        _cts = new CancellationTokenSource();
        var token = _cts.Token;

        _playTask = Task.Run(() => RunAsync(sessionId, binPath, mapping, startSeconds, token), token);
    }

    public void Stop()
    {
        if (_cts == null)
        {
            return;
        }

        try
        {
            _cts.Cancel();
            _playTask?.Wait(2000);
        }
        catch
        {
            // ignore
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
            _playTask = null;
        }
    }

    public void Dispose()
    {
        Stop();
    }

    /// <summary>
    /// Request pause or resume of playback.
    /// </summary>
    public void SetPaused(bool paused)
    {
        lock (_stateLock)
        {
            _isPaused = paused;
        }
    }

    /// <summary>
    /// Request a seek to the given playback position in seconds.
    /// </summary>
    public void Seek(double seconds)
    {
        lock (_stateLock)
        {
            _pendingSeekSeconds = seconds;
        }
    }

    private async Task RunAsync(string sessionId, string binPath, DeviceMapping mapping, double startSeconds, CancellationToken cancellationToken)
    {
        try
        {
            if (!File.Exists(binPath))
            {
                if (_config.Debug)
                {
                    _logger.LogInformation("[Ambilight] Binary file not found: {Path}", binPath);
                }
                _logger.LogWarning("[Ambilight] AMb2 binary not found for session {SessionId}: {Path}", sessionId, binPath);
                return;
            }

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Binary file found: {Path}", binPath);
            }

            using var fs = File.OpenRead(binPath);
            using var reader = new BinaryReader(fs);

            // Header
            var magic = reader.ReadBytes(4);
            if (magic.Length != 4 || magic[0] != (byte)'A' || magic[1] != (byte)'M' || magic[2] != (byte)'b' || magic[3] != (byte)'2')
            {
                _logger.LogWarning("[Ambilight] Invalid AMb2 header in {Path}", binPath);
                return;
            }

            var fps = reader.ReadSingle();
            double fpsD = fps;
            if (double.IsNaN(fpsD) || fpsD <= 0.001 || fpsD > 300.0)
            {
                fpsD = 0.0;
            }

            var topSrc = reader.ReadUInt16();
            var bottomSrc = reader.ReadUInt16();
            var leftSrc = reader.ReadUInt16();
            var rightSrc = reader.ReadUInt16();
            var fmt = reader.ReadByte();
            var rgbw = fmt == 1;
            var bytesPerLed = rgbw ? 4 : 3;
            var frameSize = (topSrc + bottomSrc + leftSrc + rightSrc) * bytesPerLed;

            // Target counts from mapping (falling back to source counts when unset)
            int tgtTop = mapping.TopLedCount > 0 ? mapping.TopLedCount : Math.Max(1, (int)topSrc);
            int tgtBottom = mapping.BottomLedCount > 0 ? mapping.BottomLedCount : Math.Max(1, (int)bottomSrc);
            int tgtLeft = mapping.LeftLedCount > 0 ? mapping.LeftLedCount : Math.Max(1, (int)leftSrc);
            int tgtRight = mapping.RightLedCount > 0 ? mapping.RightLedCount : Math.Max(1, (int)rightSrc);

            int totalSrc = topSrc + bottomSrc + leftSrc + rightSrc;
            if (totalSrc <= 0 && frameSize > 0)
            {
                totalSrc = frameSize / bytesPerLed;
            }
            int totalTgt = tgtTop + tgtRight + tgtBottom + tgtLeft;

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Playing {Path} → {Host}:{Port} (src {Src} LEDs → tgt {Tgt} LEDs, rgbw={Rgbw})",
                    binPath, mapping.Host, mapping.Port, totalSrc, totalTgt, rgbw);
            }

            var frames = new List<byte[]>();
            var timestampsUs = new List<ulong>();

            while (fs.Position < fs.Length && !cancellationToken.IsCancellationRequested)
            {
                var tsBytes = reader.ReadBytes(8);
                if (tsBytes.Length < 8)
                {
                    break;
                }
                ulong ts = BitConverter.ToUInt64(tsBytes, 0);

                var payload = reader.ReadBytes(frameSize);
                if (payload.Length < frameSize)
                {
                    break;
                }

                timestampsUs.Add(ts);
                frames.Add(payload);
            }

            if (frames.Count == 0)
            {
                _logger.LogWarning("[Ambilight] No frames in AMb2 file for session {SessionId}", sessionId);
                return;
            }

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Binary loaded into memory: {FrameCount} frames", frames.Count);
            }

            if (fpsD <= 0.0 && timestampsUs.Count >= 2)
            {
                double dtUs = Math.Abs((double)timestampsUs[1] - timestampsUs[0]);
                if (dtUs > 0.0)
                {
                    fpsD = 1e6 / dtUs;
                }
                else
                {
                    fpsD = 24.0;
                }
            }
            else if (fpsD <= 0.0)
            {
                fpsD = 24.0;
            }

            // Resolve host to IP so we get a clear error if DNS fails (e.g. .lan not resolvable in Docker).
            IPAddress? targetIp = null;
            if (IPAddress.TryParse(mapping.Host, out var parsedIp))
            {
                targetIp = parsedIp;
            }
            else
            {
                try
                {
                    var addresses = Dns.GetHostAddresses(mapping.Host);
                    foreach (var addr in addresses)
                    {
                        if (addr.AddressFamily == AddressFamily.InterNetwork)
                        {
                            targetIp = addr;
                            break;
                        }
                    }
                    targetIp ??= addresses.Length > 0 ? addresses[0] : null;
                }
                catch (SocketException ex)
                {
                    _logger.LogError("[Ambilight] Cannot resolve WLED host \"{Host}\": {Message}. If Jellyfin runs in Docker, use the device IP address (e.g. 192.168.1.x) instead of a hostname.", mapping.Host, ex.Message);
                    throw;
                }
            }

            if (targetIp == null)
            {
                _logger.LogError("[Ambilight] No IP address for WLED host \"{Host}\". Use an IP address in device mapping.", mapping.Host);
                return;
            }

            using var udp = new UdpClient();
            udp.Connect(targetIp, mapping.Port);

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Connected to WLED at {Host}:{Port}", mapping.Host, mapping.Port);
            }

            double baseSyncLead = _config.AmbilightSyncLeadSeconds;
            double effectiveStart = Math.Max(0.0, startSeconds + baseSyncLead);
            ulong startTsUs = (ulong)(effectiveStart * 1_000_000.0);
            int startFrame = 0;
            while (startFrame < timestampsUs.Count && timestampsUs[startFrame] < startTsUs)
            {
                startFrame++;
            }
            int frameIndex = Math.Min(startFrame, frames.Count - 1);

            var startInstant = DateTime.UtcNow;

            // Smoothing: configured directly in seconds. 0 = no smoothing (per-frame colors).
            float smoothSeconds = (float)_config.AmbilightSmoothSeconds;
            bool noSmoothing = smoothSeconds <= 0.0f;
            float smoothTau = noSmoothing ? 0.0f : ClampF(smoothSeconds, 0.001f, 5.0f);

            var emaAcc = (float[]?)null;

            float gammaBase = (float)_config.AmbilightGamma;
            float saturation = (float)_config.AmbilightSaturation;
            float brightnessTarget = (float)_config.AmbilightBrightnessTarget;
            float gammaRed = (float)_config.AmbilightGammaRed;
            float gammaGreen = (float)_config.AmbilightGammaGreen;
            float gammaBlue = (float)_config.AmbilightGammaBlue;
            float redBoost = (float)_config.AmbilightRedBoost;
            float greenBoost = (float)_config.AmbilightGreenBoost;
            float blueBoost = (float)_config.AmbilightBlueBoost;
            float minLedBrightness = (float)_config.AmbilightMinLedBrightness;
            int inputPosition = mapping.InputPosition;

            int rotLeds = totalTgt > 0 ? Math.Abs(inputPosition) % totalTgt : 0;

            TimeSpan elapsedBase = TimeSpan.Zero;
            bool lastPaused = false;

            // Stop loading effect now that we're about to start broadcasting
            if (_loadingEffectCts != null)
            {
                try
                {
                    _loadingEffectCts.Cancel();
                    _loadingEffectCts.Dispose();
                    _loadingEffectCts = null;
                    if (_config.Debug)
                    {
                        _logger.LogInformation("[Ambilight] Stopped loading effect, starting ambilight broadcast");
                    }
                }
                catch
                {
                    // Ignore cancellation errors
                }
            }

            while (!cancellationToken.IsCancellationRequested && frameIndex < frames.Count)
            {
                // Apply pending seek / pause state from PlaybackService
                bool pausedNow;
                double? seekSec;
                lock (_stateLock)
                {
                    pausedNow = _isPaused;
                    seekSec = _pendingSeekSeconds;
                    _pendingSeekSeconds = null;
                }

                if (seekSec.HasValue)
                {
                    var targetUs = (ulong)(Math.Max(0.0, seekSec.Value) * 1_000_000.0);
                    int targetFrame = 0;
                    while (targetFrame < timestampsUs.Count && timestampsUs[targetFrame] < targetUs)
                    {
                        targetFrame++;
                    }
                    frameIndex = Math.Min(targetFrame, frames.Count - 1);
                    startFrame = frameIndex;
                    startInstant = DateTime.UtcNow;
                    elapsedBase = TimeSpan.Zero;
                    if (_config.Debug)
                    {
                        _logger.LogInformation("[Ambilight] Seek to {Seconds:F3}s → frame {Frame}", seekSec.Value, frameIndex);
                    }
                    else
                    {
                        _logger.LogDebug("[Ambilight] In-process SEEK to {Seconds:F3}s → frame {Frame}", seekSec.Value, frameIndex);
                    }
                }

                if (pausedNow && !lastPaused)
                {
                    // Pause: freeze the current ambilight frame and stop advancing time.
                    // We do NOT blank the LEDs here so the last video frame stays visible.
                    elapsedBase += DateTime.UtcNow - startInstant;
                    if (_config.Debug)
                    {
                        _logger.LogInformation("[Ambilight] Pause detected – holding current frame");
                    }
                    else
                    {
                        _logger.LogDebug("[Ambilight] In-process player paused");
                    }
                }
                if (!pausedNow && lastPaused)
                {
                    startInstant = DateTime.UtcNow;
                    if (_config.Debug)
                    {
                        _logger.LogInformation("[Ambilight] Resume detected – resuming broadcast");
                    }
                    else
                    {
                        _logger.LogDebug("[Ambilight] In-process player resumed");
                    }
                }
                lastPaused = pausedNow;

                if (pausedNow)
                {
                    // While paused we simply sleep; WLED keeps displaying the last frame.
                    try
                    {
                        await Task.Delay(80, cancellationToken).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                    continue;
                }

                ulong frameTs = frameIndex < timestampsUs.Count ? timestampsUs[frameIndex] : 0;
                ulong baseTs = startFrame < timestampsUs.Count ? timestampsUs[startFrame] : 0;
                var frameTargetUs = frameTs > baseTs ? frameTs - baseTs : 0UL;
                var elapsed = elapsedBase + (DateTime.UtcNow - startInstant);
                ulong elapsedUs = (ulong)(elapsed.TotalSeconds * 1_000_000.0);
                if (elapsedUs < frameTargetUs)
                {
                    var sleepUs = frameTargetUs - elapsedUs;
                    var sleepMs = (int)Math.Max(0, sleepUs / 1000UL);
                    if (sleepMs > 0)
                    {
                        await Task.Delay(sleepMs, cancellationToken).ConfigureAwait(false);
                    }
                }

                var raw = frames[frameIndex];

                // avg luminance
                float sumLum = 0f;
                int countPix = 0;
                int idx = 0;
                while (idx + 2 < raw.Length)
                {
                    float r = raw[idx];
                    float g = raw[idx + 1];
                    float b = raw[idx + 2];
                    float lum = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                    sumLum += lum;
                    countPix++;
                    idx += bytesPerLed;
                }
                float avgLum = countPix > 0 ? sumLum / countPix : 0f;
                float gammaAdj = ClampF(gammaBase * (1.0f - (avgLum / 255.0f) * 0.6f), 1.0f, 3.0f);
                float invGamma = 1.0f / gammaAdj;

                float frameDtS;
                if (frameIndex == 0)
                {
                    frameDtS = (float)(1.0 / fpsD);
                }
                else
                {
                    double prevUs = frameIndex > 0 && frameIndex - 1 < timestampsUs.Count ? timestampsUs[frameIndex - 1] : 0;
                    double curUs = frameIndex < timestampsUs.Count ? timestampsUs[frameIndex] : 0;
                    double dt = (curUs - prevUs) / 1e6;
                    frameDtS = dt > 0.0 ? (float)dt : (float)(1.0 / fpsD);
                }
                float k = noSmoothing
                    ? 1.0f  // no EMA: use the current frame only
                    : 1.0f - (float)Math.Exp(-frameDtS / smoothTau);

                if (emaAcc == null)
                {
                    emaAcc = new float[totalTgt * bytesPerLed];
                    for (int t = 0; t < totalTgt; t++)
                    {
                        int srcIdx = totalTgt > 0 ? (t * totalSrc) / totalTgt : 0;
                        int sb = srcIdx * bytesPerLed;
                        for (int b = 0; b < bytesPerLed; b++)
                        {
                            emaAcc[t * bytesPerLed + b] = raw[sb + b];
                        }
                    }
                }

                var acc = emaAcc!;
                var outFrame = new byte[totalTgt * bytesPerLed];

                float sUser = ClampF(saturation, 0.0f, 5.0f);
                float gUser = Math.Max(0.01f, (float)_config.AmbilightGamma);
                float bTarget = Math.Max(1.0f, brightnessTarget);
                float minB = Math.Max(0.0f, minLedBrightness);

                float brightnessFactor = 1.0f;
                if (avgLum > 1.0f)
                {
                    float factor = (bTarget / avgLum) * 0.7f + 0.3f;
                    brightnessFactor = ClampF(factor, 0.05f, 2.5f);
                }

                for (int t = 0; t < totalTgt; t++)
                {
                    int srcIdx = totalTgt > 0 ? (t * totalSrc) / totalTgt : 0;
                    int sb = srcIdx * bytesPerLed;

                    float rU = raw[sb];
                    float gU = raw[sb + 1];
                    float bU = raw[sb + 2];

                    float rN = ClampF(rU / 255.0f, 0.0f, 1.0f);
                    float gN = ClampF(gU / 255.0f, 0.0f, 1.0f);
                    float bN = ClampF(bU / 255.0f, 0.0f, 1.0f);

                    float rLin = (float)MathF.Pow(rN, gammaRed);
                    float gLin = (float)MathF.Pow(gN, gammaGreen);
                    float bLin = (float)MathF.Pow(bN, gammaBlue);

                    float avgIntensity = (rLin + gLin + bLin) / 3.0f;
                    float rSat = avgIntensity + (rLin - avgIntensity) * sUser;
                    float gSat = avgIntensity + (gLin - avgIntensity) * sUser;
                    float bSat = avgIntensity + (bLin - avgIntensity) * sUser;

                    float rG = ClampF((float)MathF.Pow(rSat, invGamma), 0.0f, 1.0f);
                    float gG = ClampF((float)MathF.Pow(gSat, invGamma), 0.0f, 1.0f);
                    float bG = ClampF((float)MathF.Pow(bSat, invGamma), 0.0f, 1.0f);

                    float brightnessFactorAdj = ClampF(brightnessFactor, 0.3f, 1.8f);
                    float rF = rG * brightnessFactorAdj * 255.0f;
                    float gF = gG * brightnessFactorAdj * 255.0f;
                    float bF = bG * brightnessFactorAdj * 255.0f;

                    int @base = t * bytesPerLed;
                    acc[@base] = acc[@base] * (1.0f - k) + rF * k;
                    acc[@base + 1] = acc[@base + 1] * (1.0f - k) + gF * k;
                    acc[@base + 2] = acc[@base + 2] * (1.0f - k) + bF * k;

                    // Match Rust: round smoothed accumulator before min clamp and output (avoids truncation bias / blue tint)
                    float rOut = MathF.Round(acc[@base]);
                    float gOut = MathF.Round(acc[@base + 1]);
                    float bOut = MathF.Round(acc[@base + 2]);

                    float minR = minB * redBoost;
                    float minG = minB * greenBoost;
                    float minBB = minB * blueBoost;

                    if (rOut > 0.0f && rOut < minR) rOut = minR;
                    if (gOut > 0.0f && gOut < minG) gOut = minG;
                    if (bOut > 0.0f && bOut < minBB) bOut = minBB;

                    float lumLed = 0.2126f * rOut + 0.7152f * gOut + 0.0722f * bOut;
                    if (lumLed < minB * 0.5f)
                    {
                        rOut = 0.0f;
                        gOut = 0.0f;
                        bOut = 0.0f;
                    }

                    // Round before cast to byte to match Rust (truncation was darkening and boosting blue floor)
                    // Send RGB order - WLED handles color order remapping based on its own configuration
                    outFrame[@base] = (byte)Math.Clamp((int)Math.Round(rOut), 0, 255);
                    outFrame[@base + 1] = (byte)Math.Clamp((int)Math.Round(gOut), 0, 255);
                    outFrame[@base + 2] = (byte)Math.Clamp((int)Math.Round(bOut), 0, 255);

                    if (bytesPerLed == 4)
                    {
                        int srcWIdx = srcIdx * bytesPerLed + 3;
                        float wVal = raw[srcWIdx];
                        acc[@base + 3] = acc[@base + 3] * (1.0f - k) + wVal * k;
                        outFrame[@base + 3] = (byte)Math.Clamp((int)Math.Round(acc[@base + 3]), 0, 255);
                    }
                }

                byte[] frameToSend = outFrame;
                if (rotLeds > 0)
                {
                    frameToSend = RotateLedFrame(outFrame, rotLeds, totalTgt, bytesPerLed);
                }

                try
                {
                    await udp.SendAsync(frameToSend, frameToSend.Length).ConfigureAwait(false);
                    if (_config.Debug && frameIndex > 0 && frameIndex % 100 == 0)
                    {
                        _logger.LogInformation("[Ambilight] Broadcast: frame {FrameIndex}/{TotalFrames}", frameIndex, frames.Count);
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "[Ambilight] Failed to send frame {Index}", frameIndex);
                }

                frameIndex++;
            }

            // Blank on exit
            if (totalTgt > 0 && bytesPerLed > 0)
            {
                var zeroes = new byte[totalTgt * bytesPerLed];
                for (int i = 0; i < 3; i++)
                {
                    try
                    {
                        await udp.SendAsync(zeroes, zeroes.Length).ConfigureAwait(false);
                    }
                    catch
                    {
                        break;
                    }
                    await Task.Delay(20, cancellationToken).ConfigureAwait(false);
                }
            }
        }
        catch (Exception ex)
        {
            if (!cancellationToken.IsCancellationRequested)
            {
                _logger.LogError(ex, "[Ambilight] In-process player error for session {SessionId}", sessionId);
            }
        }
    }

    private static float ClampF(float v, float lo, float hi)
    {
        if (float.IsNaN(v)) return lo;
        if (v < lo) return lo;
        if (v > hi) return hi;
        return v;
    }


    private static byte[] RotateLedFrame(byte[] frame, int rotationLeds, int totalLeds, int bytesPerLed)
    {
        if (rotationLeds == 0 || totalLeds == 0)
        {
            return frame;
        }

        var rotated = new byte[frame.Length];

        for (int i = 0; i < totalLeds; i++)
        {
            int dstStart = i * bytesPerLed;
            int srcLed = (i + rotationLeds) % totalLeds;
            int srcStart = srcLed * bytesPerLed;

            Buffer.BlockCopy(frame, srcStart, rotated, dstStart, bytesPerLed);
        }

        return rotated;
    }

    /// <summary>
    /// Send a loading effect to WLED: rotating ochre segment around the LED strip.
    /// Returns a cancellation task that should be cancelled when loading completes or fails.
    /// </summary>
    public static Task SendLoadingEffectAsync(string host, int port, int totalLeds, ILogger logger, CancellationToken cancellationToken)
    {
        return Task.Run(async () =>
        {
            try
            {
                // Parse host to IP
                if (!IPAddress.TryParse(host, out var targetIp))
                {
                    targetIp = Dns.GetHostAddresses(host).FirstOrDefault();
                }

                if (targetIp == null)
                {
                    logger.LogWarning("[Ambilight] Cannot send loading effect: no IP for host {Host}", host);
                    return;
                }

                using var udp = new UdpClient();
                udp.Connect(targetIp, port);

                // Ochre/amber color (RGB: 204, 119, 34)
                byte r = 204, g = 119, b = 34;
                int segmentSize = Math.Max(totalLeds / 8, 5); // 1/8 of strip or minimum 5 LEDs
                int bytesPerLed = 3; // RGB
                
                var frame = new byte[totalLeds * bytesPerLed];
                int rotation = 0;

                logger.LogInformation("[Ambilight] Showing loading effect on WLED {Host}:{Port}", host, port);

                while (!cancellationToken.IsCancellationRequested)
                {
                    // Clear frame
                    Array.Clear(frame, 0, frame.Length);

                    // Draw rotating segment
                    for (int i = 0; i < segmentSize; i++)
                    {
                        int ledIndex = (rotation + i) % totalLeds;
                        int offset = ledIndex * bytesPerLed;
                        frame[offset] = r;
                        frame[offset + 1] = g;
                        frame[offset + 2] = b;
                    }

                    await udp.SendAsync(frame, frame.Length).ConfigureAwait(false);
                    
                    rotation = (rotation + 1) % totalLeds;
                    await Task.Delay(30, cancellationToken).ConfigureAwait(false); // ~33fps rotation
                }
            }
            catch (OperationCanceledException)
            {
                // Normal cancellation, don't log
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "[Ambilight] Error during loading effect");
            }
        }, cancellationToken);
    }

    /// <summary>
    /// Send a failure flash effect to WLED: 3 red flashes, then return to original state.
    /// WLED automatically returns to previous state when UDP stream stops.
    /// </summary>
    public static async Task SendFailureFlashAsync(string host, int port, int totalLeds, ILogger logger)
    {
        try
        {
            // Parse host to IP
            if (!IPAddress.TryParse(host, out var targetIp))
            {
                targetIp = Dns.GetHostAddresses(host).FirstOrDefault();
            }

            if (targetIp == null)
            {
                logger.LogWarning("[Ambilight] Cannot send failure flash: no IP for host {Host}", host);
                return;
            }

            using var udp = new UdpClient();
            udp.Connect(targetIp, port);

            int bytesPerLed = 3; // RGB
            var redFrame = new byte[totalLeds * bytesPerLed];
            var blackFrame = new byte[totalLeds * bytesPerLed];

            // Fill red frame (255, 0, 0)
            for (int i = 0; i < totalLeds; i++)
            {
                redFrame[i * bytesPerLed] = 255;
                redFrame[i * bytesPerLed + 1] = 0;
                redFrame[i * bytesPerLed + 2] = 0;
            }

            logger.LogInformation("[Ambilight] Showing failure flash on WLED {Host}:{Port}", host, port);

            // Flash 3 times (red on, black off)
            for (int flash = 0; flash < 3; flash++)
            {
                await udp.SendAsync(redFrame, redFrame.Length).ConfigureAwait(false);
                await Task.Delay(150).ConfigureAwait(false);
                await udp.SendAsync(blackFrame, blackFrame.Length).ConfigureAwait(false);
                await Task.Delay(150).ConfigureAwait(false);
            }

            // Don't send final black frame - WLED will automatically return to its
            // previous state (effect, pattern, or static color) when UDP stream stops
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "[Ambilight] Error during failure flash effect");
        }
    }
}

