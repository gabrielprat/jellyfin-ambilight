// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Jellyfin Ambilight Contributors
// This file is part of Jellyfin Ambilight Plugin.
// Jellyfin Ambilight Plugin is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

using System;

namespace Jellyfin.Plugin.Ambilight.Services.Extraction;

/// <summary>
/// Picks each zone color with Sobel edge detection combined with Gaussian center weighting
/// (matching the Rust extractor), then rescales every zone's brightness relative to the frame's
/// average luminance. This biases each zone toward high-contrast pixels and lifts dark zones,
/// which keeps the strip lively but makes dark scenes read brighter than the picture.
/// This is the historical default behaviour.
/// </summary>
public sealed class EdgeWeightedExtractionLogic : IExtractionLogic
{
    public void ComputeFrameColors(
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

            float rawScale = zoneLuminances[i] / globalAvgLum;
            float scale = (float)Math.Clamp(MathF.Pow(rawScale, 0.45f), 0.25f, 3.0f);
            float maxCh = Math.Max(zoneColors[i].r, Math.Max(zoneColors[i].g, zoneColors[i].b));
            float finalScale = maxCh > 0 ? Math.Min(scale, 255f / maxCh) : scale;
            output[outBase] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].r * finalScale), 0, 255);
            output[outBase + 1] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].g * finalScale), 0, 255);
            output[outBase + 2] = (byte)Math.Clamp((int)Math.Round(zoneColors[i].b * finalScale), 0, 255);
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
