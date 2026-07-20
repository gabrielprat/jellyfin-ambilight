// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;
using System.Buffers.Binary;
using System.IO;
using System.Text;

namespace Jellyfin.Plugin.Ambilight.Services;

/// <summary>
/// AMb3 binary format definition: header, chunk, index structures and helpers.
/// </summary>
public static class Amb3Format
{
    public const int HeaderSize = 85;
    public const int ChunkHeaderSize = 32;
    public const int IndexHeaderSize = 8;
    public const int IndexEntrySize = 20;
    public const byte CurrentVersion = 1;
    public const int DefaultChapterFrames = 48; // ~2s at 24fps

    // Header flag bits
    public const uint FlagCompression = 1u << 0;
    public const uint FlagVfr = 1u << 1;
    public const uint FlagMultiResolution = 1u << 2;
    public const uint FlagHdr = 1u << 3;
    public const uint FlagSceneChangeMarkers = 1u << 4;
    public const uint FlagPerceptualEncoding = 1u << 5;
    public const uint FlagDeltaEncoding = 1u << 6;
    public const uint FlagRle = 1u << 7;

    // Compression algorithms
    public const byte CompressionNone = 0;
    public const byte CompressionDeflate = 1;

    // Chunk types
    public const byte ChunkTypeKeyframe = 0;
    public const byte ChunkTypeDelta = 1;
    public const byte ChunkTypeRle = 2;

    // Color formats
    public const byte ColorFormatRgb = 0;
    public const byte ColorFormatRgbw = 1;

    // Color space
    public const byte ColorSpaceSdrRec709 = 0;
    public const byte ColorSpaceHdr10Rec2020 = 1;

    // Quality levels
    public const byte QualityHigh = 0;
    public const byte QualityMedium = 1;
    public const byte QualityLow = 2;

    // Index magic
    public static readonly byte[] IndexMagic = Encoding.ASCII.GetBytes("IDX3");

    public static bool IsAm3Magic(ReadOnlySpan<byte> magic) =>
        magic.Length >= 4 &&
        magic[0] == (byte)'A' && magic[1] == (byte)'M' &&
        magic[2] == (byte)'b' && magic[3] == (byte)'3';

    public static bool IsAm2Magic(ReadOnlySpan<byte> magic) =>
        magic.Length >= 4 &&
        magic[0] == (byte)'A' && magic[1] == (byte)'M' &&
        magic[2] == (byte)'b' && magic[3] == (byte)'2';

    // ── Header ──────────────────────────────────────────────────────────
    public static void WriteHeader(
        BinaryWriter w,
        uint flags,
        ulong durationUs,
        ulong totalFrames,
        float fps,
        ushort topLeds,
        ushort bottomLeds,
        ushort leftLeds,
        ushort rightLeds,
        byte colorFormat,
        byte compression,
        byte qualityLevel,
        ulong indexOffset,
        uint chunkCount)
    {
        // magic
        w.Write((byte)'A');
        w.Write((byte)'M');
        w.Write((byte)'b');
        w.Write((byte)'3');
        // version
        w.Write(CurrentVersion);
        // flags (4 bytes)
        w.Write(flags);
        // duration_us (8 bytes)
        w.Write(durationUs);
        // total_frames (8 bytes)
        w.Write(totalFrames);
        // base_fps (4 bytes)
        w.Write(fps);
        // led_counts[4] (8 bytes)
        w.Write(topLeds);
        w.Write(bottomLeds);
        w.Write(leftLeds);
        w.Write(rightLeds);
        // color_format (1 byte)
        w.Write(colorFormat);
        // compression (1 byte)
        w.Write(compression);
        // quality_level (1 byte)
        w.Write(qualityLevel);
        // color_space (1 byte) — reserved for now
        w.Write((byte)0);
        // index_offset (8 bytes)
        w.Write(indexOffset);
        // chunk_count (4 bytes)
        w.Write(chunkCount);
        // reserved (32 bytes)
        w.Write(new byte[32]);
    }

    public static void BackpatchHeaderIndexOffset(Stream stream, ulong indexOffset)
    {
        // index_offset is at byte 41: magic(4) + version(1) + flags(4) + duration(8) + frames(8) + fps(4) + leds(8) + color_fmt(1) + compression(1) + quality(1) + colorspace(1) = 41
        const long offset = 41;
        var pos = stream.Position;
        stream.Seek(offset, SeekOrigin.Begin);
        stream.Write(BitConverter.GetBytes(indexOffset), 0, 8);
        stream.Seek(pos, SeekOrigin.Begin);
    }

    public static (uint flags, ulong durationUs, ulong totalFrames, float fps,
        ushort topLeds, ushort bottomLeds, ushort leftLeds, ushort rightLeds,
        byte colorFormat, byte compression, byte qualityLevel,
        ulong indexOffset, uint chunkCount) ReadHeader(BinaryReader r)
    {
        var magic = r.ReadBytes(4);
        if (!IsAm3Magic(magic))
            throw new InvalidDataException("Not an AMb3 file");

        var version = r.ReadByte();
        if (version > CurrentVersion)
            throw new InvalidDataException($"Unsupported AMb3 version {version}");

        var flags = r.ReadUInt32();
        var durationUs = r.ReadUInt64();
        var totalFrames = r.ReadUInt64();
        var fps = r.ReadSingle();
        var topLeds = r.ReadUInt16();
        var bottomLeds = r.ReadUInt16();
        var leftLeds = r.ReadUInt16();
        var rightLeds = r.ReadUInt16();
        var colorFormat = r.ReadByte();
        var compression = r.ReadByte();
        var qualityLevel = r.ReadByte();
        _ = r.ReadByte(); // color_space (reserved)
        var indexOffset = r.ReadUInt64();
        var chunkCount = r.ReadUInt32();
        _ = r.ReadBytes(32); // reserved

        return (flags, durationUs, totalFrames, fps,
            topLeds, bottomLeds, leftLeds, rightLeds,
            colorFormat, compression, qualityLevel,
            indexOffset, chunkCount);
    }

    // ── Chunk Header ────────────────────────────────────────────────────
    public static void WriteChunkHeader(
        BinaryWriter w,
        ulong timestampUs,
        byte chunkType,
        uint compressedSize,
        uint uncompressedSize,
        ushort frameCount,
        byte brightnessAvg,
        byte flags,
        uint checksum)
    {
        w.Write(timestampUs);
        w.Write(chunkType);
        w.Write(compressedSize);
        w.Write(uncompressedSize);
        w.Write(frameCount);
        w.Write(brightnessAvg);
        w.Write(flags);
        w.Write(checksum);
    }

    public static (ulong timestampUs, byte chunkType, uint compressedSize,
        uint uncompressedSize, ushort frameCount, byte brightnessAvg,
        byte flags, uint checksum) ReadChunkHeader(BinaryReader r)
    {
        var timestampUs = r.ReadUInt64();
        var chunkType = r.ReadByte();
        var compressedSize = r.ReadUInt32();
        var uncompressedSize = r.ReadUInt32();
        var frameCount = r.ReadUInt16();
        var brightnessAvg = r.ReadByte();
        var flags = r.ReadByte();
        var checksum = r.ReadUInt32();

        return (timestampUs, chunkType, compressedSize,
            uncompressedSize, frameCount, brightnessAvg,
            flags, checksum);
    }

    // ── Index ───────────────────────────────────────────────────────────
    public static void WriteIndex(BinaryWriter w, (ulong timestampUs, ulong fileOffset, uint chunkIndex)[] entries)
    {
        w.Write(IndexMagic);
        w.Write((uint)entries.Length);
        foreach (var e in entries)
        {
            w.Write(e.timestampUs);
            w.Write(e.fileOffset);
            w.Write(e.chunkIndex);
        }
    }

    public static (ulong timestampUs, ulong fileOffset, uint chunkIndex)[] ReadIndex(BinaryReader r)
    {
        var magic = r.ReadBytes(4);
        if (magic.Length != 4 || magic[0] != IndexMagic[0] || magic[1] != IndexMagic[1] ||
            magic[2] != IndexMagic[2] || magic[3] != IndexMagic[3])
            throw new InvalidDataException("Invalid AMb3 index magic");

        var count = r.ReadUInt32();
        var entries = new (ulong, ulong, uint)[count];
        for (int i = 0; i < count; i++)
        {
            entries[i] = (r.ReadUInt64(), r.ReadUInt64(), r.ReadUInt32());
        }
        return entries;
    }

    // ── Helpers ─────────────────────────────────────────────────────────
    public static byte ComputeAverageBrightness(ReadOnlySpan<byte> rgbFrame)
    {
        if (rgbFrame.Length < 3) return 0;
        long sum = 0;
        int count = 0;
        for (int i = 0; i + 2 < rgbFrame.Length; i += 3)
        {
            sum += rgbFrame[i] + rgbFrame[i + 1] + rgbFrame[i + 2];
            count++;
        }
        return count > 0 ? (byte)(sum / (count * 3)) : (byte)0;
    }

    public static bool FramesEqual(ReadOnlySpan<byte> a, ReadOnlySpan<byte> b)
    {
        return a.SequenceEqual(b);
    }

    public static int CountChangedLeds(ReadOnlySpan<byte> prev, ReadOnlySpan<byte> cur, int bytesPerLed, int threshold)
    {
        int changed = 0;
        int totalLeds = prev.Length / bytesPerLed;
        for (int i = 0; i < totalLeds; i++)
        {
            int off = i * bytesPerLed;
            int diffR = Math.Abs(prev[off] - cur[off]);
            int diffG = Math.Abs(prev[off + 1] - cur[off + 1]);
            int diffB = Math.Abs(prev[off + 2] - cur[off + 2]);
            if (diffR > threshold || diffG > threshold || diffB > threshold)
                changed++;
        }
        return changed;
    }

    public static byte[] EncodeDelta(ReadOnlySpan<byte> prevFrame, ReadOnlySpan<byte> curFrame, int bytesPerLed, int threshold)
    {
        int totalLeds = curFrame.Length / bytesPerLed;
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);

        int changedCount = 0;
        // First pass: count changed LEDs to write count header
        var changed = new List<(int idx, byte r, byte g, byte b)>();
        for (int i = 0; i < totalLeds; i++)
        {
            int off = i * bytesPerLed;
            int diffR = Math.Abs(prevFrame[off] - curFrame[off]);
            int diffG = Math.Abs(prevFrame[off + 1] - curFrame[off + 1]);
            int diffB = Math.Abs(prevFrame[off + 2] - curFrame[off + 2]);
            if (diffR > threshold || diffG > threshold || diffB > threshold)
            {
                changed.Add((i, curFrame[off], curFrame[off + 1], curFrame[off + 2]));
                changedCount++;
            }
        }

        w.Write((ushort)changedCount);
        foreach (var (idx, r, g, b) in changed)
        {
            w.Write((ushort)idx);
            w.Write(r);
            w.Write(g);
            w.Write(b);
        }

        return ms.ToArray();
    }

    public static byte[] DecodeDelta(ReadOnlySpan<byte> keyframe, ReadOnlySpan<byte> deltaData, int bytesPerLed)
    {
        var result = new byte[keyframe.Length];
        keyframe.CopyTo(result);

        int offset = 0;
        if (deltaData.Length < 2) return result;
        ushort changedCount = BinaryPrimitives.ReadUInt16LittleEndian(deltaData);
        offset += 2;

        for (int i = 0; i < changedCount; i++)
        {
            if (offset + 4 > deltaData.Length) break;
            ushort ledIdx = BinaryPrimitives.ReadUInt16LittleEndian(deltaData.Slice(offset));
            offset += 2;
            byte r = deltaData[offset++];
            byte g = deltaData[offset++];
            byte b = deltaData[offset++];
            int off = ledIdx * bytesPerLed;
            if (off + 2 < result.Length)
            {
                result[off] = r;
                result[off + 1] = g;
                result[off + 2] = b;
            }
        }

        return result;
    }

    public static (byte[] frame, int repeatCount) DecodeRleFrame(ReadOnlySpan<byte> data, int frameSize)
    {
        if (data.Length < frameSize + 4)
            return (data.Length >= frameSize ? data.Slice(0, frameSize).ToArray() : data.ToArray(), 1);

        var frame = data.Slice(0, frameSize).ToArray();
        int repeat = BitConverter.ToInt32(data.Slice(frameSize).ToArray(), 0);
        return (frame, Math.Max(1, repeat));
    }
}
