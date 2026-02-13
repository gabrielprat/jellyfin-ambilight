using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using Jellyfin.Plugin.Ambilight;
using Microsoft.Extensions.Logging;

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

    // Shared state controlled by PlaybackService via SetPaused/Seek while RunAsync is looping.
    private readonly object _stateLock = new();
    private bool _isPaused;
    private double? _pendingSeekSeconds;

    public AmbilightInProcessPlayer(ILogger logger, PluginConfiguration config)
    {
        _logger = logger;
        _config = config;
    }

    public void Start(string sessionId, string binPath, string host, int port, double startSeconds)
    {
        Stop();

        _cts = new CancellationTokenSource();
        var token = _cts.Token;

        _playTask = Task.Run(() => RunAsync(sessionId, binPath, host, port, startSeconds, token), token);
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

    private async Task RunAsync(string sessionId, string binPath, string host, int port, double startSeconds, CancellationToken cancellationToken)
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

            // Target counts from config (falling back to source counts when unset)
            int tgtTop = _config.AmbilightTopLedCount > 0
                ? _config.AmbilightTopLedCount
                : Math.Max(1, (int)topSrc);
            int tgtBottom = _config.AmbilightBottomLedCount > 0
                ? _config.AmbilightBottomLedCount
                : Math.Max(1, (int)bottomSrc);
            int tgtLeft = _config.AmbilightLeftLedCount > 0
                ? _config.AmbilightLeftLedCount
                : Math.Max(1, (int)leftSrc);
            int tgtRight = _config.AmbilightRightLedCount > 0
                ? _config.AmbilightRightLedCount
                : Math.Max(1, (int)rightSrc);

            int totalSrc = topSrc + bottomSrc + leftSrc + rightSrc;
            if (totalSrc <= 0 && frameSize > 0)
            {
                totalSrc = frameSize / bytesPerLed;
            }
            int totalTgt = tgtTop + tgtRight + tgtBottom + tgtLeft;

            _logger.LogInformation("[Ambilight] Playing {Path} → src {Src} LEDs → tgt {Tgt} LEDs (rgbw={Rgbw})",
                binPath, totalSrc, totalTgt, rgbw);

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
            if (IPAddress.TryParse(host, out var parsedIp))
            {
                targetIp = parsedIp;
            }
            else
            {
                try
                {
                    var addresses = Dns.GetHostAddresses(host);
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
                    _logger.LogError("[Ambilight] Cannot resolve WLED host \"{Host}\": {Message}. If Jellyfin runs in Docker, use the device IP address (e.g. 192.168.1.x) instead of a hostname.", host, ex.Message);
                    throw;
                }
            }

            if (targetIp == null)
            {
                _logger.LogError("[Ambilight] No IP address for WLED host \"{Host}\". Use an IP address in plugin settings.", host);
                return;
            }

            using var udp = new UdpClient();
            udp.Connect(targetIp, port);

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Connected to WLED at {Host}:{Port}", host, port);
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
            string ledOrder = _config.AmbilightOrder ?? "RGB";
            int inputPosition = _config.AmbilightInputPosition;

            int rotLeds = totalTgt > 0 ? Math.Abs(inputPosition) % totalTgt : 0;

            TimeSpan elapsedBase = TimeSpan.Zero;
            bool lastPaused = false;

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
                    (byte rM, byte gM, byte bM) = RemapOrder(
                        (byte)Math.Clamp((int)Math.Round(rOut), 0, 255),
                        (byte)Math.Clamp((int)Math.Round(gOut), 0, 255),
                        (byte)Math.Clamp((int)Math.Round(bOut), 0, 255),
                        ledOrder);

                    outFrame[@base] = rM;
                    outFrame[@base + 1] = gM;
                    outFrame[@base + 2] = bM;

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

    private static (byte r, byte g, byte b) RemapOrder(byte r, byte g, byte b, string order)
    {
        return order switch
        {
            "GRB" => (g, r, b),
            "BRG" => (b, r, g),
            "BGR" => (b, g, r),
            "GBR" => (g, b, r),
            _ => (r, g, b)
        };
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
}

