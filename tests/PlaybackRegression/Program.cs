// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using Jellyfin.Plugin.Ambilight;
using Jellyfin.Plugin.Ambilight.Services;
using Microsoft.Extensions.Logging.Abstractions;

// Exercise the actual public player and its wire output, without a Jellyfin server or WLED.
// Each edge has one LED, so no resampling or layout transformation is needed.
byte[] black = new byte[12];
byte[] red = [255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
byte[] green = [0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
byte[] blue = [0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 0];
byte[] greenAndBlue = [0, 255, 0, 0, 0, 0, 0, 0, 255, 0, 0, 0];
var cases = new (string Name, Chapter[] Chapters)[]
{
    ("keyframe-only playback", [Keyframes(black, red, green, blue)]),
    ("a changed first LED", [Keyframes(black), Deltas(black, red)]),
    ("a changed nonzero LED", [Keyframes(black), Deltas(black, blue)]),
    ("return to keyframe within a delta chapter", [Keyframes(black), Deltas(black, red, black)]),
    ("return to keyframe across delta chapters", [Keyframes(black), Deltas(black, red), Deltas(black, black)]),
    ("a new keyframe replaces the reference", [Keyframes(black), Deltas(black, red), Keyframes(green), Deltas(green, greenAndBlue, green)]),
    ("the last frame in a keyframe chapter is the reference", [Keyframes(black, green), Deltas(green, greenAndBlue, green)]),
};

int failures = 0;
foreach (var test in cases)
{
    try
    {
        await CheckPlayback(test.Chapters);
        Console.WriteLine($"PASS: {test.Name}");
    }
    catch (Exception ex)
    {
        failures++;
        Console.Error.WriteLine($"FAIL: {test.Name}: {ex.Message}");
    }
}
Console.WriteLine($"{cases.Length - failures} passed, {failures} failed");
return failures == 0 ? 0 : 1;

static Chapter Keyframes(params byte[][] frames) => new(Amb3Format.ChunkTypeKeyframe, null, frames);
static Chapter Deltas(byte[] reference, params byte[][] frames) => new(Amb3Format.ChunkTypeDelta, reference, frames);

static async Task CheckPlayback(Chapter[] chapters)
{
    string path = Path.Combine(Path.GetTempPath(), $"ambilight-regression-{Guid.NewGuid():N}.bin");
    try
    {
        WriteFixture(path, chapters);
        using var receiver = new UdpClient(new IPEndPoint(IPAddress.Loopback, AmbilightInProcessPlayer.WledUdpPort));
        var config = new PluginConfiguration
        {
            AmbilightSyncLeadSeconds = 0,
            AmbilightSmoothSeconds = 0,
            AmbilightGamma = 1,
            AmbilightSaturation = 1,
        };
        var mapping = new DeviceMapping
        {
            Host = IPAddress.Loopback.ToString(),
            TopLedCount = 1,
            BottomLedCount = 1,
            LeftLedCount = 1,
            RightLedCount = 1,
        };
        using var player = new AmbilightInProcessPlayer(NullLogger.Instance, config);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        player.Start("regression", path, mapping, 0);
        int index = 0;
        foreach (var expected in chapters.SelectMany(chapter => chapter.Frames))
        {
            var received = await receiver.ReceiveAsync(timeout.Token);
            if (!received.Buffer.SequenceEqual(expected))
            {
                throw new InvalidOperationException(
                    $"frame {index}: expected {Convert.ToHexString(expected)}, received {Convert.ToHexString(received.Buffer)}");
            }
            index++;
        }
    }
    finally
    {
        File.Delete(path);
    }
}

static void WriteFixture(string path, Chapter[] chapters)
{
    using var stream = File.Create(path);
    using var writer = new BinaryWriter(stream);
    int frameCount = chapters.Sum(chapter => chapter.Frames.Length);
    Amb3Format.WriteHeader(writer,
        flags: Amb3Format.FlagCompression | Amb3Format.FlagDeltaEncoding,
        durationUs: (ulong)frameCount * 20_000,
        totalFrames: (ulong)frameCount,
        fps: 50,
        topLeds: 1, bottomLeds: 1, leftLeds: 1, rightLeds: 1,
        colorFormat: Amb3Format.ColorFormatRgb,
        compression: Amb3Format.CompressionDeflate,
        qualityLevel: Amb3Format.QualityHigh,
        indexOffset: 0,
        chunkCount: (uint)chapters.Length,
        extractionLogic: Amb3Format.ExtractionLogicLinearLightAverage);
    ulong timestamp = 0;
    foreach (var chapter in chapters)
    {
        ulong firstTimestamp = timestamp;
        using var payload = new MemoryStream();
        using (var body = new BinaryWriter(payload, System.Text.Encoding.UTF8, leaveOpen: true))
        {
            foreach (var frame in chapter.Frames)
            {
                body.Write(timestamp);
                if (chapter.Type == Amb3Format.ChunkTypeKeyframe)
                {
                    body.Write(frame);
                    body.Write(1); // Each keyframe entry includes its RLE repeat count.
                }
                else
                {
                    // Same encoder and fixed reference used by FlushChapter in the extractor.
                    body.Write(Amb3Format.EncodeDelta(chapter.Reference!, frame, 3, 10));
                }
                timestamp += 20_000;
            }
        }
        using var compressed = new MemoryStream();
        using (var deflate = new DeflateStream(compressed, CompressionLevel.Fastest, leaveOpen: true))
        {
            payload.Position = 0;
            payload.CopyTo(deflate);
        }
        Amb3Format.WriteChunkHeader(writer, firstTimestamp, chapter.Type,
            (uint)compressed.Length, (uint)payload.Length, (ushort)chapter.Frames.Length,
            brightnessAvg: 0, flags: 0, checksum: 0);
        writer.Write(compressed.ToArray());
    }
}

record Chapter(byte Type, byte[]? Reference, byte[][] Frames);
