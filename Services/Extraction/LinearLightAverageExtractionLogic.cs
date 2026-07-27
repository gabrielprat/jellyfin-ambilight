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
/// Computes each zone as a plain, unweighted mean of every pixel in the zone, taken in linear
/// light. This is the picture-extending behaviour: a dark zone averages dark, and a black frame
/// produces black LEDs. There is no edge weighting and no cross-zone brightness rescaling.
/// </summary>
public sealed class LinearLightAverageExtractionLogic : IExtractionLogic
{
    // sRGB transfer function tables. Averaging must happen in linear light: because the sRGB
    // encoding is concave, the mean of encoded values always decodes brighter than the true mean,
    // and the error peaks on zones mixing dark pixels with highlights.
    private static readonly float[] SrgbToLinear = BuildSrgbToLinear();

    private static float[] BuildSrgbToLinear()
    {
        var lut = new float[256];
        for (int i = 0; i < 256; i++)
        {
            float v = i / 255.0f;
            lut[i] = v <= 0.04045f ? v / 12.92f : MathF.Pow((v + 0.055f) / 1.055f, 2.4f);
        }
        return lut;
    }

    private static byte LinearToSrgbByte(float linear)
    {
        linear = Math.Clamp(linear, 0.0f, 1.0f);
        float encoded = linear <= 0.0031308f
            ? linear * 12.92f
            : 1.055f * MathF.Pow(linear, 1.0f / 2.4f) - 0.055f;
        return (byte)Math.Clamp((int)MathF.Round(encoded * 255.0f), 0, 255);
    }

    public void ComputeFrameColors(
        byte[] frame,
        int width,
        int height,
        (int x1, int y1, int x2, int y2)[] zones,
        byte[] output)
    {
        const int bytesPerLed = 3;

        for (int i = 0; i < zones.Length; i++)
        {
            var (x1, y1, x2, y2) = zones[i];
            x1 = Math.Clamp(x1, 0, width);
            x2 = Math.Clamp(x2, 0, width);
            y1 = Math.Clamp(y1, 0, height);
            y2 = Math.Clamp(y2, 0, height);

            int outBase = i * bytesPerLed;
            if (x2 <= x1 || y2 <= y1)
            {
                output[outBase] = 0;
                output[outBase + 1] = 0;
                output[outBase + 2] = 0;
                continue;
            }

            var (rOut, gOut, bOut) = ExtractLinearMeanColor(frame, width, x1, y1, x2, y2);
            output[outBase] = rOut;
            output[outBase + 1] = gOut;
            output[outBase + 2] = bOut;
        }
    }

    /// <summary>
    /// Unweighted mean of every pixel in the zone, taken in linear light.
    /// </summary>
    private static (byte r, byte g, byte b) ExtractLinearMeanColor(
        byte[] frame,
        int frameWidth,
        int x1,
        int y1,
        int x2,
        int y2)
    {
        double rSum = 0.0, gSum = 0.0, bSum = 0.0;
        int count = 0;

        for (int yy = y1; yy < y2; yy++)
        {
            int rowBase = yy * frameWidth * 3;
            for (int xx = x1; xx < x2; xx++)
            {
                int idx = rowBase + xx * 3;
                rSum += SrgbToLinear[frame[idx]];
                gSum += SrgbToLinear[frame[idx + 1]];
                bSum += SrgbToLinear[frame[idx + 2]];
                count++;
            }
        }

        if (count == 0)
        {
            return (0, 0, 0);
        }

        return (
            LinearToSrgbByte((float)(rSum / count)),
            LinearToSrgbByte((float)(gSum / count)),
            LinearToSrgbByte((float)(bSum / count))
        );
    }
}
