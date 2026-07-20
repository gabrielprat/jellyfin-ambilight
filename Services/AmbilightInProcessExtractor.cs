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
using System.IO.Compression;
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

    private PluginConfiguration Config => Plugin.Instance?.Configuration ?? _config;

    public (int top, int right, int bottom, int left, string hardwareAcceleration) GetRuntimeExtractionSettings()
    {
        var cfg = Config;
        return (
            Math.Max(0, cfg.AmbilightTopLedCount),
            Math.Max(0, cfg.AmbilightRightLedCount),
            Math.Max(0, cfg.AmbilightBottomLedCount),
            Math.Max(0, cfg.AmbilightLeftLedCount),
            cfg.HardwareAcceleration ?? "auto");
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
        var hwaccel = Config.HardwareAcceleration ?? "auto";
        var baseArgs = "-hide_banner -loglevel error";
        
        // Hardware acceleration options
        // Note: For most modes we keep it simple - just enable hwaccel for decoding
        // and let ffmpeg handle the format conversion automatically
        string hwaccelArgs = hwaccel.ToLower() switch
        {
            "vaapi" => "-hwaccel vaapi -hwaccel_device /dev/dri/renderD128",
            "qsv" => "-hwaccel qsv",
            "cuda" => "-hwaccel cuda",
            "videotoolbox" => "-hwaccel videotoolbox",
            "none" => "",
            _ => "" // "auto" - let ffmpeg auto-detect, but don't force it
        };
        
        // Use simple software filter chain - hardware acceleration is only for decoding
        // ffmpeg will automatically transfer frames to system memory for filtering
        // Keep pixel format explicit in the filter graph to avoid driver-dependent
        // color conversion quirks before writing rawvideo bytes.
        string filterChain = $"scale={ExtractWidth}:{ExtractHeight},format=rgb24";
        
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
            var cfg = Config;
            // Probe video to get actual FPS and duration
            float fps = await ProbeVideoFps(videoPath, cancellationToken).ConfigureAwait(false);
            float duration = await ProbeVideoDuration(videoPath, cancellationToken).ConfigureAwait(false);
            ulong estimatedFrames = (ulong)(duration * fps);
            
            if (cfg.Debug)
            {
                _logger.LogInformation("[Ambilight] Extractor: video FPS: {Fps:F3}, duration: {Duration:F1}s, estimated frames: {Frames}", fps, duration, estimatedFrames);
            }

            // Prepare header values
            ushort topCount = (ushort)Math.Max(0, cfg.AmbilightTopLedCount);
            ushort bottomCount = (ushort)Math.Max(0, cfg.AmbilightBottomLedCount);
            ushort leftCount = (ushort)Math.Max(0, cfg.AmbilightLeftLedCount);
            ushort rightCount = (ushort)Math.Max(0, cfg.AmbilightRightLedCount);
            int bytesPerLed = 3;
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
                if (cfg.Debug)
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

            using var ms = new MemoryStream();
            using var writer = new BinaryWriter(ms);

            // Write AMb3 header with placeholder index_offset (backpatched later)
            uint headerFlags = Amb3Format.FlagCompression;
            Amb3Format.WriteHeader(
                writer,
                flags: headerFlags,
                durationUs: (ulong)(duration * 1_000_000.0),
                totalFrames: estimatedFrames,
                fps: fps,
                topLeds: topCount,
                bottomLeds: bottomCount,
                leftLeds: leftCount,
                rightLeds: rightCount,
                colorFormat: Amb3Format.ColorFormatRgb,
                compression: Amb3Format.CompressionDeflate,
                qualityLevel: Amb3Format.QualityHigh,
                indexOffset: 0, // backpatched after index is written
                chunkCount: 0); // backpatched after all chunks written

            ulong frameIndex = 0;
            var zoning = zones.ToArray();
            var zoneColors = new byte[ledsPerFrame * bytesPerLed];
            int ledsBytes = ledsPerFrame * bytesPerLed;
            int chapterSize = cfg.Amb3ChapterSizeFrames > 0 ? cfg.Amb3ChapterSizeFrames : Amb3Format.DefaultChapterFrames;
            int deltaThreshold = cfg.Amb3DeltaThreshold > 0 ? cfg.Amb3DeltaThreshold : 10;
            bool deltaFallback = cfg.Amb3DeltaFallbackToKeyframe;
            int sceneChangeThreshold = cfg.Amb3SceneChangeThreshold; // % of LEDs that must change to trigger scene cut

            // Chapter buffer: list of LED frame byte arrays
            var chapterFrames = new List<byte[]>();
            var chapterTimestamps = new List<ulong>();
            var chunkOffsets = new List<(ulong timestampUs, ulong fileOffset, uint chunkIndex)>();
            uint chunkIndex = 0;
            byte[]? lastKeyframeData = null;
            byte[]? lastFrameColors = null; // for scene change detection

            // Helpers for compressing chapter data
            byte[] CompressData(byte[] raw)
            {
                using var compressed = new MemoryStream();
                using (var deflate = new DeflateStream(compressed, CompressionLevel.Fastest, leaveOpen: true))
                {
                    deflate.Write(raw, 0, raw.Length);
                }
                return compressed.ToArray();
            }

            void FlushChapter()
            {
                if (chapterFrames.Count == 0) return;

                // Decide chapter type: keyframe or delta
                bool useDelta = lastKeyframeData != null && chapterFrames.Count > 0;
                if (useDelta && deltaFallback)
                {
                    // Check how many LEDs changed across all frames vs keyframe
                    int totalChanged = 0;
                    foreach (var frame in chapterFrames)
                    {
                        totalChanged += Amb3Format.CountChangedLeds(lastKeyframeData, frame, bytesPerLed, deltaThreshold);
                    }
                    int avgChanged = totalChanged / chapterFrames.Count;
                    // If >50% of LEDs changed on average, fall back to keyframe
                    if (avgChanged > ledsPerFrame / 2)
                        useDelta = false;
                }

                // Serialize chapter frame data
                byte[] chapterData;
                byte chunkType;
                byte brightnessAvg = Amb3Format.ComputeAverageBrightness(chapterFrames[0]);

                if (useDelta)
                {
                    chunkType = Amb3Format.ChunkTypeDelta;
                    using var chMs = new MemoryStream();
                    using var chW = new BinaryWriter(chMs);
                    foreach (var frame in chapterFrames)
                    {
                        chW.Write(chapterTimestamps[chapterFrames.IndexOf(frame)]);
                        var delta = Amb3Format.EncodeDelta(lastKeyframeData!, frame, bytesPerLed, deltaThreshold);
                        chW.Write(delta);
                    }
                    chapterData = chMs.ToArray();
                }
                else
                {
                    chunkType = Amb3Format.ChunkTypeKeyframe;
                    // Apply RLE dedup: group consecutive identical frames
                    using var chMs = new MemoryStream();
                    using var chW = new BinaryWriter(chMs);
                    int i = 0;
                    while (i < chapterFrames.Count)
                    {
                        int runLength = 1;
                        while (i + runLength < chapterFrames.Count &&
                               Amb3Format.FramesEqual(chapterFrames[i], chapterFrames[i + runLength]))
                        {
                            runLength++;
                        }

                        chW.Write(chapterTimestamps[i]);
                        chW.Write(chapterFrames[i]);
                        chW.Write(runLength); // RLE repeat count (always written for uniformity)

                        i += runLength;
                    }
                    chapterData = chMs.ToArray();
                    lastKeyframeData = chapterFrames[^1]; // last frame becomes reference for next delta
                }

                // Compress chapter data
                byte[] compressedData = CompressData(chapterData);

                // Write chunk
                ulong chunkTimestamp = chapterTimestamps[0];
                chunkOffsets.Add((chunkTimestamp, (ulong)ms.Position, chunkIndex));

                Amb3Format.WriteChunkHeader(
                    writer,
                    timestampUs: chunkTimestamp,
                    chunkType: chunkType,
                    compressedSize: (uint)compressedData.Length,
                    uncompressedSize: (uint)chapterData.Length,
                    frameCount: (ushort)chapterFrames.Count,
                    brightnessAvg: brightnessAvg,
                    flags: 0,
                    checksum: 0);

                writer.Write(compressedData);
                chunkIndex++;

                chapterFrames.Clear();
                chapterTimestamps.Clear();
            }

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

                ulong tsUs = (ulong)(frameIndex * 1_000_000.0 / fps);

                // Compute colors for each zone
                ComputeFrameColors(frameBuffer, ExtractWidth, ExtractHeight, zoning, zoneColors);

                // Copy zone colors ( BinaryWriter writes from the array reference,
                // and we reuse zoneColors, so we need our own copy per frame)
                var frameCopy = new byte[ledsBytes];
                Buffer.BlockCopy(zoneColors, 0, frameCopy, 0, ledsBytes);

                // Scene change detection: if >threshold% of LEDs changed vs previous frame, flush chapter
                if (sceneChangeThreshold > 0 && lastFrameColors != null && chapterFrames.Count > 0)
                {
                    int changedLeds = Amb3Format.CountChangedLeds(lastFrameColors, frameCopy, bytesPerLed, deltaThreshold);
                    int sceneChangePercent = (changedLeds * 100) / ledsPerFrame;
                    if (sceneChangePercent >= sceneChangeThreshold)
                    {
                        FlushChapter();
                        lastKeyframeData = null; // force next chapter to be a keyframe
                    }
                }

                chapterFrames.Add(frameCopy);
                chapterTimestamps.Add(tsUs);
                lastFrameColors = frameCopy;

                // Flush chapter when buffer is full
                if (chapterFrames.Count >= chapterSize)
                {
                    FlushChapter();
                }

                frameIndex++;

                if (progress != null && frameIndex % 200 == 0)
                {
                    progress.Report((frameIndex, estimatedFrames));
                }

                if (cfg.Debug && frameIndex % 200 == 0)
                {
                    _logger.LogInformation("[Ambilight] Extractor: processed {Frames} frames for {Path}", frameIndex, videoPath);
                }
            }

            // Flush remaining frames in the last chapter
            FlushChapter();

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

            // Write seeking index at end of file
            ulong indexOffset = (ulong)ms.Position;
            Amb3Format.WriteIndex(writer, chunkOffsets.ToArray());

            // Backpatch header: index_offset and chunk_count
            Amb3Format.BackpatchHeaderIndexOffset(ms, indexOffset);
            // chunk_count is at offset 49: magic(4) + version(1) + flags(4) + duration(8) + frames(8) + fps(4) + leds(8) + color_fmt(1) + compression(1) + quality(1) + colorspace(1) + index_offset(8) = 49
            long chunkCountPos = 49;
            var savedPos = ms.Position;
            ms.Seek(chunkCountPos, SeekOrigin.Begin);
            writer.Write(chunkIndex);
            ms.Seek(savedPos, SeekOrigin.Begin);

            // Atomic write to target path
            var outDir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(outDir))
            {
                Directory.CreateDirectory(outDir);
            }

            var tempPath = outputPath + ".tmp";
            await File.WriteAllBytesAsync(tempPath, ms.ToArray(), cancellationToken).ConfigureAwait(false);
            File.Move(tempPath, outputPath, overwrite: true);

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

            if (cfg.Debug)
            {
                _logger.LogInformation("[Ambilight] Extractor: wrote AMb3 file {Output} with {Frames} frames in {Chunks} chunks", outputPath, frameIndex, chunkIndex);
            }
            if (cfg.Debug)
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
        byte[] output)
    {
        const int bytesPerLed = 3;

        // First pass: extract colors and luminances
        var zoneColors = new (byte r, byte g, byte b)[zones.Length];
        var zoneLuminances = new float[zones.Length];
        double totalLuminance = 0.0;
        int validZones = 0;

        for (int i = 0; i < zones.Length; i++)
        {
            var (x1, y1, x2, y2) = zones[i];
            x1 = Math.Clamp(x1, 0, width);
            x2 = Math.Clamp(x2, 0, width);
            y1 = Math.Clamp(y1, 0, height);
            y2 = Math.Clamp(y2, 0, height);
            if (x2 <= x1 || y2 <= y1)
            {
                zoneColors[i] = (0, 0, 0);
                zoneLuminances[i] = 0f;
                continue;
            }

            var (rOut, gOut, bOut, lum) = ExtractEdgeDominantColor(frame, width, height, x1, y1, x2, y2);
            zoneColors[i] = (rOut, gOut, bOut);
            zoneLuminances[i] = lum;
            totalLuminance += lum;
            validZones++;
        }

        // Compute global average luminance
        float globalAvgLum = validZones > 0 ? (float)(totalLuminance / validZones) : 0f;

        // Second pass: scale RGB by zone luminance relative to global average
        for (int i = 0; i < zones.Length; i++)
        {
            int outBase = i * bytesPerLed;

            if (globalAvgLum <= 0.01f || zoneLuminances[i] <= 0.01f)
            {
                // Dark frame or dark zone — keep original color (will be dim anyway)
                output[outBase] = zoneColors[i].r;
                output[outBase + 1] = zoneColors[i].g;
                output[outBase + 2] = zoneColors[i].b;
                continue;
            }

            float scale = zoneLuminances[i] / globalAvgLum;
            output[outBase] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].r * scale), 0, 255);
            output[outBase + 1] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].g * scale), 0, 255);
            output[outBase + 2] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].b * scale), 0, 255);
        }
    }

    /// <summary>
    /// Extract color from a zone using edge detection + center weighting, matching the Rust extractor.
    /// Uses Sobel edge detection (simpler than Canny but similar results) combined with Gaussian center weighting.
    /// </summary>
    private static (byte r, byte g, byte b, float luminance) ExtractEdgeDominantColor(
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
            return (0, 0, 0, 0f);
        }

        // Compute grayscale and Sobel edge strength for the ROI
        var edgeStrength = new float[h, w];
        float maxEdge = 0.0f;
        double lumSum = 0.0;
        int pixelCount = 0;

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

                // Accumulate luminance for zone brightness
                int centerIdx = (fy * frameWidth + fx) * 3;
                lumSum += frame[centerIdx] * 0.2126 + frame[centerIdx + 1] * 0.7152 + frame[centerIdx + 2] * 0.0722;
                pixelCount++;
            }
        }

        float zoneLuminance = pixelCount > 0 ? (float)(lumSum / pixelCount) : 0f;

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
                (byte)Math.Clamp((int)Math.Round(bSum / totalWeight), 0, 255),
                zoneLuminance
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
                (byte)(bAvg / count),
                zoneLuminance
            );
        }

        return (0, 0, 0, 0f);
    }
}

