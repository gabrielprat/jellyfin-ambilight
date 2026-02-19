// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// In-process implementation of the ambilight-extractor logic in C#.
/// Produces AMb2 binary files compatible with the Rust player/C# player.
/// </summary>
public sealed class AmbilightInProcessExtractor
{
    private readonly ILogger<AmbilightInProcessExtractor> _logger;
    private readonly PluginConfiguration _config;
    private readonly string _ffmpegPath;

    // Modest working resolution – we don't need full 4K to compute edge colors.
    private const int ExtractWidth = 320;
    private const int ExtractHeight = 180;

    public AmbilightInProcessExtractor(ILogger<AmbilightInProcessExtractor> logger, PluginConfiguration config)
    {
        _logger = logger;
        _config = config;
        _ffmpegPath = ResolveFfmpegPath();
    }

    private string ResolveFfmpegPath()
    {
        // 1) Try ffmpeg from PATH – this covers most native installs and some containers.
        var candidates = new List<string>();
        candidates.Add("ffmpeg");

        // 2) Common Jellyfin container locations
        candidates.Add("/usr/lib/jellyfin-ffmpeg/ffmpeg");
        candidates.Add("/usr/bin/ffmpeg");

        foreach (var candidate in candidates)
        {
            try
            {
                if (!Path.IsPathRooted(candidate))
                {
                    // Non-absolute: just try to start; if it fails, move on.
                    using var probe = Process.Start(new ProcessStartInfo
                    {
                        FileName = candidate,
                        Arguments = "-version",
                        UseShellExecute = false,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        CreateNoWindow = true
                    });

                    if (probe != null)
                    {
                        // Give it a very short time, then kill; existence is all we care about.
                        if (!probe.WaitForExit(1000))
                        {
                            try { probe.Kill(); } catch { /* ignore */ }
                        }

                        _logger.LogInformation("[Ambilight] Extractor: using ffmpeg from PATH: {Path}", candidate);
                        return candidate;
                    }
                }
                else
                {
                    if (File.Exists(candidate))
                    {
                        _logger.LogInformation("[Ambilight] Extractor: using ffmpeg at {Path}", candidate);
                        return candidate;
                    }
                }
            }
            catch
            {
                // Ignore and try next candidate.
            }
        }

        _logger.LogWarning("[Ambilight] Extractor: could not auto-detect ffmpeg; falling back to 'ffmpeg'. Ensure it is installed in PATH or at /usr/lib/jellyfin-ffmpeg/ffmpeg.");
        return "ffmpeg";
    }

    /// <summary>
    /// Probe video file to get the actual FPS (frames per second).
    /// Uses ffprobe to read the avg_frame_rate from the video stream.
    /// </summary>
    private async Task<float> ProbeVideoFps(string videoPath, CancellationToken cancellationToken)
    {
        const float fallbackFps = 24.0f;

        try
        {
            // Construct ffprobe path from ffmpeg path (usually in same directory)
            string ffprobePath;
            if (Path.IsPathRooted(_ffmpegPath))
            {
                // Absolute path: replace filename only, keep directory
                var dir = Path.GetDirectoryName(_ffmpegPath);
                ffprobePath = Path.Combine(dir ?? "/", "ffprobe");
            }
            else
            {
                // Relative or PATH: just use "ffprobe"
                ffprobePath = "ffprobe";
            }
            
            // ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=noprint_wrappers=1:nokey=1 "video.mp4"
            var ffprobe = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = ffprobePath,
                    Arguments = $"-v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=noprint_wrappers=1:nokey=1 \"{videoPath}\"",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                }
            };

            ffprobe.Start();
            var output = await ffprobe.StandardOutput.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
            await ffprobe.WaitForExitAsync(cancellationToken).ConfigureAwait(false);

            if (ffprobe.ExitCode == 0 && !string.IsNullOrWhiteSpace(output))
            {
                // Parse fraction like "24000/1001" or "30/1"
                var parts = output.Trim().Split('/');
                if (parts.Length == 2 && 
                    int.TryParse(parts[0], out var numerator) && 
                    int.TryParse(parts[1], out var denominator) &&
                    denominator > 0)
                {
                    var fps = (float)numerator / denominator;
                    if (fps > 0.0f && fps < 200.0f) // Sanity check
                    {
                        return fps;
                    }
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[Ambilight] Extractor: failed to probe FPS with ffprobe, falling back to {Fps}", fallbackFps);
        }

        _logger.LogWarning("[Ambilight] Extractor: using fallback FPS of {Fps}", fallbackFps);
        return fallbackFps;
    }

    private string BuildFfmpegArguments(string videoPath)
    {
        var hwaccel = _config.HardwareAcceleration ?? "auto";
        var baseArgs = "-hide_banner -loglevel error";
        
        // Hardware acceleration options
        string hwaccelArgs = hwaccel.ToLower() switch
        {
            "vaapi" => "-hwaccel vaapi -hwaccel_device /dev/dri/renderD128",
            "qsv" => "-hwaccel qsv",
            "cuda" => "-hwaccel cuda",
            "videotoolbox" => "-hwaccel videotoolbox",
            "none" => "",
            _ => "" // "auto" - let ffmpeg auto-detect, but don't force it
        };
        
        // Build filter chain based on acceleration type
        // For hardware acceleration, we need to explicitly download frames from GPU to CPU
        // before applying software filters like scale
        string filterChain = hwaccel.ToLower() switch
        {
            "qsv" => $"hwdownload,format=yuv420p,scale={ExtractWidth}:{ExtractHeight}",
            "cuda" => $"hwdownload,format=yuv420p,scale={ExtractWidth}:{ExtractHeight}",
            "videotoolbox" => $"hwdownload,format=yuv420p,scale={ExtractWidth}:{ExtractHeight}",
            "vaapi" => $"hwdownload,format=yuv420p,scale={ExtractWidth}:{ExtractHeight}",
            _ => $"scale={ExtractWidth}:{ExtractHeight}" // auto or none - use simple software path
        };
        
        return $"{baseArgs} {hwaccelArgs} -i \"{videoPath}\" -vf {filterChain} -pix_fmt rgb24 -f rawvideo pipe:1".Trim();
    }

    private async Task<float> ProbeVideoDuration(string videoPath, CancellationToken cancellationToken)
    {
        const float fallbackDuration = 60.0f; // 1 minute fallback

        try
        {
            // Construct ffprobe path from ffmpeg path
            string ffprobePath;
            if (Path.IsPathRooted(_ffmpegPath))
            {
                var dir = Path.GetDirectoryName(_ffmpegPath);
                ffprobePath = Path.Combine(dir ?? "/", "ffprobe");
            }
            else
            {
                ffprobePath = "ffprobe";
            }
            
            // ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "video.mp4"
            var ffprobe = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = ffprobePath,
                    Arguments = $"-v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{videoPath}\"",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                }
            };

            ffprobe.Start();
            var output = await ffprobe.StandardOutput.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
            await ffprobe.WaitForExitAsync(cancellationToken).ConfigureAwait(false);

            if (ffprobe.ExitCode == 0 && !string.IsNullOrWhiteSpace(output))
            {
                if (float.TryParse(output.Trim(), out var duration) && duration > 0.0f)
                {
                    return duration;
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[Ambilight] Extractor: Failed to probe video duration for {Path}", videoPath);
        }

        return fallbackDuration;
    }

    public async Task<bool> ExtractAsync(string videoPath, string outputPath, CancellationToken cancellationToken, IProgress<(ulong current, ulong total)>? progress = null)
    {
        if (string.IsNullOrEmpty(videoPath) || !File.Exists(videoPath))
        {
            _logger.LogWarning("[Ambilight] Extractor: video file not found: {Path}", videoPath);
            return false;
        }

        try
        {
            // Probe video to get actual FPS and duration
            float fps = await ProbeVideoFps(videoPath, cancellationToken).ConfigureAwait(false);
            float duration = await ProbeVideoDuration(videoPath, cancellationToken).ConfigureAwait(false);
            ulong estimatedFrames = (ulong)(duration * fps);
            
            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Extractor: video FPS: {Fps:F3}, duration: {Duration:F1}s, estimated frames: {Frames}", fps, duration, estimatedFrames);
            }

            // Prepare header values
            ushort topCount = (ushort)Math.Max(0, _config.AmbilightTopLedCount);
            ushort bottomCount = (ushort)Math.Max(0, _config.AmbilightBottomLedCount);
            ushort leftCount = (ushort)Math.Max(0, _config.AmbilightLeftLedCount);
            ushort rightCount = (ushort)Math.Max(0, _config.AmbilightRightLedCount);
            bool rgbw = _config.AmbilightRgbw;
            byte fmt = rgbw ? (byte)1 : (byte)0;

            int bytesPerLed = rgbw ? 4 : 3;
            var zones = ComputeLedZones(ExtractWidth, ExtractHeight, topCount, bottomCount, leftCount, rightCount);
            int ledsPerFrame = zones.Count;
            if (ledsPerFrame == 0)
            {
                _logger.LogWarning("[Ambilight] Extractor: no LED zones computed – check LED counts.");
                return false;
            }

            // Build ffmpeg arguments with hardware acceleration
            string ffmpegArgs = BuildFfmpegArguments(videoPath);
            
            // Start ffmpeg to produce a scaled RGB24 raw video stream.
            var ffmpeg = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = _ffmpegPath,
                    Arguments = ffmpegArgs,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                    WorkingDirectory = Path.GetDirectoryName(videoPath) ?? "/"
                }
            };

            Task<string>? stderrTask = null;
            
            try
            {
                if (_config.Debug)
                {
                    _logger.LogInformation("[Ambilight] Extractor: starting ffmpeg for {Path}", videoPath);
                    _logger.LogInformation("[Ambilight] Extractor: ffmpeg args: {Args}", ffmpegArgs);
                }
                ffmpeg.Start();
                
                // Capture stderr asynchronously for error reporting
                stderrTask = ffmpeg.StandardError.ReadToEndAsync(cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[Ambilight] Extractor: failed to start ffmpeg. Ensure ffmpeg is installed and in PATH.");
                return false;
            }

            var stdout = ffmpeg.StandardOutput.BaseStream;
            int frameSize = ExtractWidth * ExtractHeight * 3; // rgb24
            var frameBuffer = new byte[frameSize];

            // Accumulate AMb2 data in memory as the Rust extractor does.
            using var ms = new MemoryStream();
            using var writer = new BinaryWriter(ms);

            // Write AMb2 header (magic + fps + counts + fmt)
            writer.Write(new[] { (byte)'A', (byte)'M', (byte)'b', (byte)'2' });
            writer.Write(fps);
            writer.Write(topCount);
            writer.Write(bottomCount);
            writer.Write(leftCount);
            writer.Write(rightCount);
            writer.Write(fmt);

            ulong frameIndex = 0;
            var zoning = zones.ToArray();
            var zoneColors = new byte[ledsPerFrame * bytesPerLed];

            while (!cancellationToken.IsCancellationRequested)
            {
                int readTotal = 0;
                while (readTotal < frameSize)
                {
                    int n = await stdout.ReadAsync(frameBuffer, readTotal, frameSize - readTotal, cancellationToken).ConfigureAwait(false);
                    if (n <= 0)
                    {
                        readTotal = 0;
                        break; // EOF
                    }
                    readTotal += n;
                }

                if (readTotal == 0)
                {
                    break; // no more frames
                }

                // Calculate timestamp in microseconds using actual video FPS (matching Rust implementation)
                ulong tsUs = (ulong)(frameIndex * 1_000_000.0 / fps);
                writer.Write(tsUs);

                // Compute colors for each zone
                ComputeFrameColors(frameBuffer, ExtractWidth, ExtractHeight, zoning, rgbw, zoneColors);
                writer.Write(zoneColors);

                frameIndex++;
                
                // Report progress every 200 frames to avoid overhead
                if (progress != null && frameIndex % 200 == 0)
                {
                    progress.Report((frameIndex, estimatedFrames));
                }
                
                if (_config.Debug && frameIndex % 200 == 0)
                {
                    _logger.LogInformation("[Ambilight] Extractor: processed {Frames} frames for {Path}", frameIndex, videoPath);
                }
            }

            try
            {
                await ffmpeg.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            }
            catch
            {
                // ignore cancellation / wait errors
            }

            if (frameIndex == 0)
            {
                // Try to get stderr output for better error reporting
                string stderrOutput = "";
                if (stderrTask != null)
                {
                    try
                    {
                        stderrOutput = await stderrTask.ConfigureAwait(false);
                    }
                    catch
                    {
                        // Ignore errors reading stderr
                    }
                }
                
                if (!string.IsNullOrWhiteSpace(stderrOutput))
                {
                    _logger.LogWarning("[Ambilight] Extractor: no frames decoded for {Path}. ffmpeg stderr: {Error}", videoPath, stderrOutput);
                }
                else
                {
                    _logger.LogWarning("[Ambilight] Extractor: no frames decoded for {Path}", videoPath);
                }
                return false;
            }

            // Atomic write to target path
            var outDir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(outDir))
            {
                Directory.CreateDirectory(outDir);
            }

            var tempPath = outputPath + ".tmp";
            await File.WriteAllBytesAsync(tempPath, ms.ToArray(), cancellationToken).ConfigureAwait(false);
            File.Move(tempPath, outputPath, overwrite: true);
            
            // Report 100% completion
            progress?.Report((frameIndex, estimatedFrames));

            long fileSize = 0;
            try
            {
                var fi = new FileInfo(outputPath);
                if (fi.Exists)
                {
                    fileSize = fi.Length;
                }
            }
            catch
            {
                // ignore size errors
            }

            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Extractor: wrote AMb2 file {Output} with {Frames} frames", outputPath, frameIndex);
            }
            if (_config.Debug)
            {
                _logger.LogInformation("[Ambilight] Extractor: final file {Output} size {SizeBytes} bytes (~{SizeMb:F2} MB)",
                    outputPath,
                    fileSize,
                    fileSize / 1024.0 / 1024.0);
            }
            return true;
        }
        catch (Exception ex) when (!cancellationToken.IsCancellationRequested)
        {
            _logger.LogError(ex, "[Ambilight] Extractor: exception extracting {Path}", videoPath);
            return false;
        }
    }

    private static List<(int x1, int y1, int x2, int y2)> ComputeLedZones(int width, int height, ushort top, ushort bottom, ushort left, ushort right)
    {
        int w = width;
        int h = height;

        double topSpacing = top > 0 ? (double)w / top : w;
        double bottomSpacing = bottom > 0 ? (double)w / bottom : w;
        double leftSpacing = left > 0 ? (double)h / left : h;
        double rightSpacing = right > 0 ? (double)h / right : h;

        int Clamp(int v, int lo, int hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        int topH = Clamp((int)Math.Round(topSpacing * 2.0), 12, (int)(h * 0.12));
        int bottomH = Clamp((int)Math.Round(bottomSpacing * 2.0), 12, (int)(h * 0.12));
        int leftW = Clamp((int)Math.Round(leftSpacing * 2.0), 12, (int)(w * 0.12));
        int rightW = Clamp((int)Math.Round(rightSpacing * 2.0), 12, (int)(w * 0.12));

        var zones = new List<(int, int, int, int)>();

        // Top: left → right
        for (int i = 0; i < top; i++)
        {
            int x1 = (int)(i * w / (double)top);
            int x2 = (int)((i + 1) * w / (double)top);
            zones.Add((x1, 0, x2, topH));
        }

        // Right: top → bottom
        for (int i = 0; i < right; i++)
        {
            int y1 = (int)(i * h / (double)right);
            int y2 = (int)((i + 1) * h / (double)right);
            zones.Add((w - rightW, y1, w, y2));
        }

        // Bottom: right → left
        for (int i = 0; i < bottom; i++)
        {
            int x2 = (int)(w - i * w / (double)bottom);
            int x1 = (int)(w - (i + 1) * w / (double)bottom);
            zones.Add((x1, h - bottomH, x2, h));
        }

        // Left: bottom → top
        for (int i = 0; i < left; i++)
        {
            int y2 = (int)(h - i * h / (double)left);
            int y1 = (int)(h - (i + 1) * h / (double)left);
            zones.Add((0, y1, leftW, y2));
        }

        return zones;
    }

    private static void ComputeFrameColors(
        byte[] frame,
        int width,
        int height,
        (int x1, int y1, int x2, int y2)[] zones,
        bool rgbw,
        byte[] output)
    {
        int bytesPerLed = rgbw ? 4 : 3;

        for (int i = 0; i < zones.Length; i++)
        {
            var (x1, y1, x2, y2) = zones[i];
            x1 = Math.Clamp(x1, 0, width);
            x2 = Math.Clamp(x2, 0, width);
            y1 = Math.Clamp(y1, 0, height);
            y2 = Math.Clamp(y2, 0, height);
            if (x2 <= x1 || y2 <= y1)
            {
                // No area – black
                int baseIdx = i * bytesPerLed;
                output[baseIdx] = 0;
                output[baseIdx + 1] = 0;
                output[baseIdx + 2] = 0;
                if (rgbw) output[baseIdx + 3] = 0;
                continue;
            }

            // Extract edge-dominant color (matching Rust implementation)
            var (rOut, gOut, bOut) = ExtractEdgeDominantColor(frame, width, height, x1, y1, x2, y2);
            byte wOut = 0;

            if (rgbw)
            {
                // Same logic as Rust: extract white component as min(r,g,b).
                byte wComp = Math.Min(rOut, Math.Min(gOut, bOut));
                rOut = (byte)(rOut - wComp);
                gOut = (byte)(gOut - wComp);
                bOut = (byte)(bOut - wComp);
                wOut = wComp;
            }

            int outBase = i * bytesPerLed;
            output[outBase] = rOut;
            output[outBase + 1] = gOut;
            output[outBase + 2] = bOut;
            if (rgbw)
            {
                output[outBase + 3] = wOut;
            }
        }
    }

    /// <summary>
    /// Extract color from a zone using edge detection + center weighting, matching the Rust extractor.
    /// Uses Sobel edge detection (simpler than Canny but similar results) combined with Gaussian center weighting.
    /// </summary>
    private static (byte r, byte g, byte b) ExtractEdgeDominantColor(
        byte[] frame,
        int frameWidth,
        int frameHeight,
        int x1,
        int y1,
        int x2,
        int y2)
    {
        int w = x2 - x1;
        int h = y2 - y1;

        if (w <= 0 || h <= 0)
        {
            return (0, 0, 0);
        }

        // Compute grayscale and Sobel edge strength for the ROI
        var edgeStrength = new float[h, w];
        float maxEdge = 0.0f;

        for (int yy = 0; yy < h; yy++)
        {
            for (int xx = 0; xx < w; xx++)
            {
                int fx = x1 + xx;
                int fy = y1 + yy;

                // Sobel operators for edge detection
                float gx = 0.0f;
                float gy = 0.0f;

                // 3x3 Sobel kernel (sample neighbors if available)
                for (int dy = -1; dy <= 1; dy++)
                {
                    for (int dx = -1; dx <= 1; dx++)
                    {
                        int nx = Math.Clamp(fx + dx, x1, x2 - 1);
                        int ny = Math.Clamp(fy + dy, y1, y2 - 1);
                        int idx = (ny * frameWidth + nx) * 3;

                        // Grayscale approximation: 0.299*R + 0.587*G + 0.114*B
                        float gray = frame[idx] * 0.299f + frame[idx + 1] * 0.587f + frame[idx + 2] * 0.114f;

                        // Sobel X kernel: [-1 0 1; -2 0 2; -1 0 1]
                        if (dx == -1) gx -= gray * (dy == 0 ? 2.0f : 1.0f);
                        else if (dx == 1) gx += gray * (dy == 0 ? 2.0f : 1.0f);

                        // Sobel Y kernel: [-1 -2 -1; 0 0 0; 1 2 1]
                        if (dy == -1) gy -= gray * (dx == 0 ? 2.0f : 1.0f);
                        else if (dy == 1) gy += gray * (dx == 0 ? 2.0f : 1.0f);
                    }
                }

                float magnitude = MathF.Sqrt(gx * gx + gy * gy);
                edgeStrength[yy, xx] = magnitude;
                maxEdge = Math.Max(maxEdge, magnitude);
            }
        }

        // Normalize edge strengths to 0-1 range
        if (maxEdge > 0.0f)
        {
            for (int yy = 0; yy < h; yy++)
            {
                for (int xx = 0; xx < w; xx++)
                {
                    edgeStrength[yy, xx] /= maxEdge;
                }
            }
        }

        // Compute weighted average: 70% edge weight + 30% center weight (matching Rust)
        double rSum = 0.0, gSum = 0.0, bSum = 0.0;
        double totalWeight = 0.0;

        int centerX = w / 2;
        int centerY = h / 2;
        int minSize = Math.Min(w, h);
        double sigma = Math.Max(minSize / 4.0, 1.0);
        double sigmaSq2 = 2.0 * sigma * sigma;

        for (int yy = 0; yy < h; yy++)
        {
            for (int xx = 0; xx < w; xx++)
            {
                // Edge weight (0-1)
                double edgeWeight = edgeStrength[yy, xx];

                // Center weight (Gaussian)
                double dx = xx - centerX;
                double dy = yy - centerY;
                double distSq = dx * dx + dy * dy;
                double centerWeight = Math.Exp(-distSq / sigmaSq2);

                // Combined: 70% edge, 30% center (matching Rust implementation)
                double weight = Math.Max(edgeWeight * 0.7 + centerWeight * 0.3, 0.01);

                int fx = x1 + xx;
                int fy = y1 + yy;
                int idx = (fy * frameWidth + fx) * 3;

                byte r = frame[idx];
                byte g = frame[idx + 1];
                byte b = frame[idx + 2];

                rSum += r * weight;
                gSum += g * weight;
                bSum += b * weight;
                totalWeight += weight;
            }
        }

        if (totalWeight > 0.0)
        {
            return (
                (byte)Math.Clamp((int)Math.Round(rSum / totalWeight), 0, 255),
                (byte)Math.Clamp((int)Math.Round(gSum / totalWeight), 0, 255),
                (byte)Math.Clamp((int)Math.Round(bSum / totalWeight), 0, 255)
            );
        }

        // Fallback: simple average
        double rAvg = 0.0, gAvg = 0.0, bAvg = 0.0;
        int count = 0;
        for (int yy = y1; yy < y2; yy++)
        {
            for (int xx = x1; xx < x2; xx++)
            {
                int idx = (yy * frameWidth + xx) * 3;
                rAvg += frame[idx];
                gAvg += frame[idx + 1];
                bAvg += frame[idx + 2];
                count++;
            }
        }

        if (count > 0)
        {
            return (
                (byte)(rAvg / count),
                (byte)(gAvg / count),
                (byte)(bAvg / count)
            );
        }

        return (0, 0, 0);
    }
}

