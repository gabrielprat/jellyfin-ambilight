use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::exit;

use byteorder::{LittleEndian, WriteBytesExt};
use clap::Parser;
use chrono::Local;
use ffmpeg_next as ffmpeg;
use image::{GrayImage, Rgb, RgbImage};
use imageproc::edges::canny;

#[derive(Parser, Debug)]
#[command(name = "ambilight-extractor", about = "Extract ambilight data from video files")]
struct Cli {
    #[arg(long, help = "Path to input video file")]
    input: String,

    #[arg(long, help = "Path to output binary file")]
    output: String,

    #[arg(long, default_value_t = 150, help = "Number of top LEDs")]
    top: u16,

    #[arg(long, default_value_t = 150, help = "Number of bottom LEDs")]
    bottom: u16,

    #[arg(long, help = "Number of left LEDs (auto-calculated if not provided)")]
    left: Option<u16>,

    #[arg(long, help = "Number of right LEDs (auto-calculated if not provided)")]
    right: Option<u16>,

    #[arg(long, help = "Enable RGBW output (4 bytes per LED instead of 3)")]
    rgbw: bool,
}

#[inline]
fn clamp(v: i32, lo: i32, hi: i32) -> i32 {
    v.max(lo).min(hi)
}

fn check_disk_space(_output_path: &Path, _required_gb: f64) -> bool {
    // Simplified: always return true for now
    // Can be enhanced with sysinfo crate if needed
    true
}

fn compute_led_zones(width: u32, height: u32, counts: (u16, u16, u16, u16)) -> Vec<(i32, i32, i32, i32)> {
    let w = width as i32;
    let h = height as i32;
    let (top_count, bottom_count, left_count, right_count) = counts;

    // Calculate LED spacing
    let top_spacing = if top_count > 0 { w as f64 / top_count as f64 } else { w as f64 };
    let bottom_spacing = if bottom_count > 0 { w as f64 / bottom_count as f64 } else { w as f64 };
    let left_spacing = if left_count > 0 { h as f64 / left_count as f64 } else { h as f64 };
    let right_spacing = if right_count > 0 { h as f64 / right_count as f64 } else { h as f64 };

    // Calculate band sizes (2x LED spacing, clamped)
    let top_h = clamp((top_spacing * 2.0).round() as i32, 12, (h as f64 * 0.12) as i32);
    let bottom_h = clamp((bottom_spacing * 2.0).round() as i32, 12, (h as f64 * 0.12) as i32);
    let left_w = clamp((left_spacing * 2.0).round() as i32, 12, (w as f64 * 0.12) as i32);
    let right_w = clamp((right_spacing * 2.0).round() as i32, 12, (w as f64 * 0.12) as i32);

    let mut zones = Vec::new();

    // Top: left → right
    for i in 0..top_count {
        let x1 = (i as f64 * w as f64 / top_count as f64) as i32;
        let x2 = ((i + 1) as f64 * w as f64 / top_count as f64) as i32;
        zones.push((x1, 0, x2, top_h));
    }

    // Right: top → bottom
    for i in 0..right_count {
        let y1 = (i as f64 * h as f64 / right_count as f64) as i32;
        let y2 = ((i + 1) as f64 * h as f64 / right_count as f64) as i32;
        zones.push((w - right_w, y1, w, y2));
    }

    // Bottom: right → left
    for i in 0..bottom_count {
        let x2 = (w as f64 - i as f64 * w as f64 / bottom_count as f64) as i32;
        let x1 = (w as f64 - (i + 1) as f64 * w as f64 / bottom_count as f64) as i32;
        zones.push((x1, h - bottom_h, x2, h));
    }

    // Left: bottom → top
    for i in 0..left_count {
        let y2 = (h as f64 - i as f64 * h as f64 / left_count as f64) as i32;
        let y1 = (h as f64 - (i + 1) as f64 * h as f64 / left_count as f64) as i32;
        zones.push((0, y1, left_w, y2));
    }

    zones
}

/// Convert RGB to RGBW by extracting the white component.
/// The white component is the minimum of R, G, B (the amount of white light).
/// The RGB components are then reduced by the white amount to get pure color.
/// This preserves total brightness: R' + G' + B' + W ≈ R + G + B
#[inline]
fn rgb_to_rgbw(r: u8, g: u8, b: u8) -> (u8, u8, u8, u8) {
    let w = r.min(g).min(b);
    let r_out = r.saturating_sub(w);
    let g_out = g.saturating_sub(w);
    let b_out = b.saturating_sub(w);
    (r_out, g_out, b_out, w)
}

fn extract_edge_dominant_color(frame: &RgbImage, x1: i32, y1: i32, x2: i32, y2: i32) -> (u8, u8, u8) {
    let width = (x2 - x1) as u32;
    let height = (y2 - y1) as u32;
    if width == 0 || height == 0 {
        return (0, 0, 0);
    }

    // Extract ROI
    let x1 = x1.max(0) as u32;
    let y1 = y1.max(0) as u32;
    let x2 = x2.min(frame.width() as i32) as u32;
    let y2 = y2.min(frame.height() as i32) as u32;

    if x2 <= x1 || y2 <= y1 {
        return (0, 0, 0);
    }

    let roi_width = x2 - x1;
    let roi_height = y2 - y1;

    // Extract ROI as a new image
    let mut roi = RgbImage::new(roi_width, roi_height);
    for y in 0..roi_height {
        for x in 0..roi_width {
            let px = frame.get_pixel(x1 + x, y1 + y);
            roi.put_pixel(x, y, *px);
        }
    }

    // Convert to grayscale for edge detection
    let gray: GrayImage = image::imageops::grayscale(&roi);

    // Adaptive Canny thresholds
    let min_size = roi_width.min(roi_height);
    let (low_thresh, high_thresh) = if min_size < 20 {
        (30.0, 100.0)
    } else if min_size < 50 {
        (40.0, 120.0)
    } else {
        (50.0, 150.0)
    };

    // Apply Canny edge detection
    let edges = canny(&gray, low_thresh, high_thresh);

    // Calculate weighted mean using edge mask and center weighting
    let h = roi_height as i32;
    let w = roi_width as i32;
    let center_y = h / 2;
    let center_x = w / 2;
    let sigma = (min_size as f64 / 4.0).max(1.0);
    let sigma_sq = 2.0 * sigma * sigma;

    let mut r_sum = 0.0f64;
    let mut g_sum = 0.0f64;
    let mut b_sum = 0.0f64;
    let mut total_weight = 0.0f64;

    for y in 0..h {
        for x in 0..w {
            // Edge weight (0-1)
            let edge_val = edges.get_pixel(x as u32, y as u32)[0] as f64 / 255.0;

            // Center weight (Gaussian)
            let dx = (x - center_x) as f64;
            let dy = (y - center_y) as f64;
            let dist_sq = dx * dx + dy * dy;
            let center_weight = (-dist_sq / sigma_sq).exp();

            // Combined: 70% edge, 30% center
            let weight = (edge_val * 0.7 + center_weight * 0.3).max(0.01);

            // Get RGB pixel
            let rgb = roi.get_pixel(x as u32, y as u32);
            let Rgb([r, g, b]) = *rgb;

            r_sum += r as f64 * weight;
            g_sum += g as f64 * weight;
            b_sum += b as f64 * weight;
            total_weight += weight;
        }
    }

    if total_weight > 0.0 {
        (
            (r_sum / total_weight) as u8,
            (g_sum / total_weight) as u8,
            (b_sum / total_weight) as u8,
        )
    } else {
        // Fallback: simple mean
        let mut r_sum = 0u64;
        let mut g_sum = 0u64;
        let mut b_sum = 0u64;
        let count = (roi_width * roi_height) as u64;

        for pixel in roi.pixels() {
            let Rgb([r, g, b]) = *pixel;
            r_sum += r as u64;
            g_sum += g as u64;
            b_sum += b as u64;
        }

        (
            (r_sum / count) as u8,
            (g_sum / count) as u8,
            (b_sum / count) as u8,
        )
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    ffmpeg::init()?;

    let cli = Cli::parse();

    let output_path = Path::new(&cli.output);

    // Record start time for elapsed-time reporting
    let start_time = Local::now();
    eprintln!(
        "{} ▶️  Starting extraction for '{}' → '{}'",
        start_time.format("%Y-%m-%d %H:%M:%S"),
        cli.input,
        cli.output
    );

    // Check disk space
    if !check_disk_space(output_path, 2.0) {
        eprintln!(
            "{} ❌ Extraction aborted due to insufficient disk space",
            start_time.format("%Y-%m-%d %H:%M:%S")
        );
        exit(1);
    }

    // Open video with FFmpeg
    let mut ictx = ffmpeg::format::input(&cli.input)?;
    let video_stream = ictx
        .streams()
        .best(ffmpeg::media::Type::Video)
        .ok_or("No video stream found")?;
    let video_stream_index = video_stream.index();

    let context = ffmpeg::codec::context::Context::from_parameters(video_stream.parameters())?;
    let mut decoder = context.decoder().video()?;

    // Note: Hardware-accelerated decoding (v4l2m2m) may be used automatically by FFmpeg
    // if available and if the codec supports it. Colorspace conversion (yuv420p->rgb24)
    // is NOT hardware-accelerated on Raspberry Pi 4B - this is a known limitation.
    // The warning "No accelerated colorspace conversion found" is expected and harmless.

    // Get video properties
    let fps = video_stream.avg_frame_rate();
    let fps_value = if fps.numerator() > 0 && fps.denominator() > 0 {
        fps.numerator() as f64 / fps.denominator() as f64
    } else {
        24.0
    };

    let width = decoder.width();
    let height = decoder.height();

    let now = Local::now();
    eprintln!(
        "{} Video FPS source: {:.3} ({}x{})",
        now.format("%Y-%m-%d %H:%M:%S"),
        fps_value,
        width,
        height
    );

    // Calculate left/right if not provided
    let (left, right) = if cli.left.is_none() || cli.right.is_none() {
        let vertical_perimeter_share = (2.0 * height as f64) / (2.0 * (height + width) as f64);
        let horizontal_leds = cli.top + cli.bottom;
        let proportional_lr = (horizontal_leds as f64 * vertical_perimeter_share).round() as u16;
        (proportional_lr, proportional_lr)
    } else {
        (cli.left.unwrap(), cli.right.unwrap())
    };

    let counts = (cli.top, cli.bottom, left, right);
    let now = Local::now();
    eprintln!(
        "{} LED distribution: top={}, bottom={}, left={}, right={} (total={})",
        now.format("%Y-%m-%d %H:%M:%S"),
        cli.top,
        cli.bottom,
        left,
        right,
        cli.top + cli.bottom + left + right
    );

    let zones = compute_led_zones(width, height, counts);
    let fmt_word = if cli.rgbw { 1u8 } else { 0u8 };

    // Prepare in-memory output buffer - all processing happens in memory,
    // and we only write to disk once at the end for efficiency
    let mut data = Vec::new();

    // Write header: "AMb2" + f32 fps + u16 top + u16 bottom + u16 left + u16 right + u8 fmt
    data.write_all(b"AMb2")?;
    data.write_f32::<LittleEndian>(fps_value as f32)?;
    data.write_u16::<LittleEndian>(cli.top)?;
    data.write_u16::<LittleEndian>(cli.bottom)?;
    data.write_u16::<LittleEndian>(left)?;
    data.write_u16::<LittleEndian>(right)?;
    data.write_u8(fmt_word)?;

    // Convert frames to RGB images
    let mut frame_idx = 0u64;
    let mut total_frames_written = 0u64;
    let mut converter = ffmpeg::software::scaling::context::Context::get(
        decoder.format(),
        decoder.width(),
        decoder.height(),
        ffmpeg::format::Pixel::RGB24,
        decoder.width(),
        decoder.height(),
        ffmpeg::software::scaling::flag::Flags::BILINEAR,
    )?;

    // Seek to beginning
    ictx.seek(0, 0..i64::MAX)?;

    for (stream, packet) in ictx.packets() {
        if stream.index() == video_stream_index {
            decoder.send_packet(&packet)?;

            let mut decoded = ffmpeg::frame::Video::empty();
            while decoder.receive_frame(&mut decoded).is_ok() {
                // Convert frame to RGB
                let mut rgb_frame = ffmpeg::frame::Video::empty();
                converter.run(&decoded, &mut rgb_frame)?;

                // Convert FFmpeg frame to image::RgbImage
                let width = rgb_frame.width();
                let height = rgb_frame.height();
                let stride = rgb_frame.stride(0);
                let frame_data = rgb_frame.data(0);

                let mut img = RgbImage::new(width, height);
                for y in 0..height {
                    for x in 0..width {
                        let offset = (y as usize * stride + x as usize * 3);
                        if offset + 2 < frame_data.len() {
                            let r = frame_data[offset];
                            let g = frame_data[offset + 1];
                            let b = frame_data[offset + 2];
                            img.put_pixel(x, y, Rgb([r, g, b]));
                        }
                    }
                }

                // Calculate timestamp in microseconds
                let ts_us = ((frame_idx as f64 / fps_value) * 1_000_000.0) as u64;
                data.write_u64::<LittleEndian>(ts_us)?;

                // Extract colors for each zone
                for zone in &zones {
                    let (r, g, b) = extract_edge_dominant_color(&img, zone.0, zone.1, zone.2, zone.3);
                    if cli.rgbw {
                        // Convert RGB to RGBW by extracting white component
                        let (r_out, g_out, b_out, w) = rgb_to_rgbw(r, g, b);
                        data.write_all(&[r_out, g_out, b_out, w])?;
                    } else {
                        data.write_all(&[r, g, b])?;
                    }
                }

                total_frames_written += 1;
                frame_idx += 1;

                if frame_idx % 200 == 0 {
                    let now = Local::now();
                    eprintln!(
                        "{} Processed {} frames...",
                        now.format("%Y-%m-%d %H:%M:%S"),
                        frame_idx
                    );
                }
            }
        }
    }

    // Flush decoder
    decoder.send_eof()?;
    let mut decoded = ffmpeg::frame::Video::empty();
    while decoder.receive_frame(&mut decoded).is_ok() {
        // Process remaining frames
        let mut rgb_frame = ffmpeg::frame::Video::empty();
        converter.run(&decoded, &mut rgb_frame)?;

        let width = rgb_frame.width();
        let height = rgb_frame.height();
        let stride = rgb_frame.stride(0);
        let frame_data = rgb_frame.data(0);

        let mut img = RgbImage::new(width, height);
        for y in 0..height {
            for x in 0..width {
                let offset = (y as usize * stride + x as usize * 3);
                if offset + 2 < frame_data.len() {
                    let r = frame_data[offset];
                    let g = frame_data[offset + 1];
                    let b = frame_data[offset + 2];
                    img.put_pixel(x, y, Rgb([r, g, b]));
                }
            }
        }

        let ts_us = ((frame_idx as f64 / fps_value) * 1_000_000.0) as u64;
        data.write_u64::<LittleEndian>(ts_us)?;

        for zone in &zones {
            let (r, g, b) = extract_edge_dominant_color(&img, zone.0, zone.1, zone.2, zone.3);
            if cli.rgbw {
                // Convert RGB to RGBW by extracting white component
                let (r_out, g_out, b_out, w) = rgb_to_rgbw(r, g, b);
                data.write_all(&[r_out, g_out, b_out, w])?;
            } else {
                data.write_all(&[r, g, b])?;
            }
        }

        total_frames_written += 1;
        frame_idx += 1;
    }

    // Write atomically using temp file - this is the ONLY disk write operation
    // All frame processing was done in memory (the `data` Vec)
    let temp_path = output_path.with_extension("bin.tmp");

    // Ensure parent directory exists (only directory creation, no data write)
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)?;
    }

    // Single atomic write of all processed data to disk
    fs::write(&temp_path, &data)?;

    // Atomic rename to final location
    fs::rename(&temp_path, output_path)?;

    let end_time = Local::now();
    let elapsed = end_time
        .signed_duration_since(start_time)
        .num_milliseconds() as f64
        / 1000.0;
    eprintln!(
        "{} ✅ Done! Saved to '{}' ({} frames, fps={:.3}, elapsed {:.1}s)",
        end_time.format("%Y-%m-%d %H:%M:%S"),
        cli.output,
        total_frames_written,
        fps_value,
        elapsed
    );

    Ok(())
}
