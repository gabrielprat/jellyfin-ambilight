use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::exit;

use byteorder::{LittleEndian, WriteBytesExt};
use clap::Parser;
use chrono::Local;
use opencv::core::{Mat, Size, Vec3b};
use opencv::imgproc::{canny, cvt_color, COLOR_BGR2GRAY};
use opencv::prelude::*;
use opencv::videoio::{VideoCapture, CAP_PROP_FPS, CAP_PROP_POS_FRAMES};

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

fn compute_led_zones(frame_size: Size, counts: (u16, u16, u16, u16)) -> Vec<(i32, i32, i32, i32)> {
    let h = frame_size.height;
    let w = frame_size.width;
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

fn extract_edge_dominant_color(frame: &Mat, x1: i32, y1: i32, x2: i32, y2: i32) -> Result<(u8, u8, u8), opencv::Error> {
    let width = x2 - x1;
    let height = y2 - y1;
    if width <= 0 || height <= 0 {
        return Ok((0, 0, 0));
    }

    // Extract ROI using Mat::roi
    let rect = opencv::core::Rect::new(x1, y1, width, height);
    let roi = Mat::roi(frame, rect)?;

    if roi.rows() == 0 || roi.cols() == 0 {
        return Ok((0, 0, 0));
    }

    // Convert to grayscale for edge detection
    let mut gray = Mat::default();
    cvt_color(&roi, &mut gray, COLOR_BGR2GRAY, 0)?;

    // Adaptive Canny thresholds
    let min_size = roi.rows().min(roi.cols());
    let (low_thresh, high_thresh) = if min_size < 20 {
        (30.0, 100.0)
    } else if min_size < 50 {
        (40.0, 120.0)
    } else {
        (50.0, 150.0)
    };

    let mut edges = Mat::default();
    canny(&gray, &mut edges, low_thresh, high_thresh, 3, false)?;

    // Calculate weighted mean using edge mask and center weighting
    let h = roi.rows();
    let w = roi.cols();
    let center_y = h / 2;
    let center_x = w / 2;
    let sigma = (min_size as f64 / 4.0).max(1.0);
    let sigma_sq = 2.0 * sigma * sigma;

    let mut b_sum = 0.0f64;
    let mut g_sum = 0.0f64;
    let mut r_sum = 0.0f64;
    let mut total_weight = 0.0f64;

    for y in 0..h {
        for x in 0..w {
            // Edge weight (0-1)
            let edge_val = unsafe { *edges.at_2d::<u8>(y, x)? } as f64 / 255.0;

            // Center weight (Gaussian)
            let dx = (x - center_x) as f64;
            let dy = (y - center_y) as f64;
            let dist_sq = dx * dx + dy * dy;
            let center_weight = (-dist_sq / sigma_sq).exp();

            // Combined: 70% edge, 30% center
            let weight = (edge_val * 0.7 + center_weight * 0.3).max(0.01);

            // Get BGR pixel
            let bgr = unsafe { *roi.at_2d::<Vec3b>(y, x)? };

            b_sum += bgr[0] as f64 * weight;
            g_sum += bgr[1] as f64 * weight;
            r_sum += bgr[2] as f64 * weight;
            total_weight += weight;
        }
    }

    if total_weight > 0.0 {
        Ok((
            (b_sum / total_weight) as u8,
            (g_sum / total_weight) as u8,
            (r_sum / total_weight) as u8,
        ))
    } else {
        // Fallback: simple mean (no mask)
        let mask = Mat::default();
        let mean = opencv::core::mean(&roi, &mask)?;
        Ok((mean[0] as u8, mean[1] as u8, mean[2] as u8))
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
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

    // Open video
    let mut cap = VideoCapture::from_file(&cli.input, opencv::videoio::CAP_ANY)?;
    if !cap.is_opened()? {
        eprintln!("❌ Cannot open video: {}", cli.input);
        exit(1);
    }

    // Get FPS
    let fps = cap.get(CAP_PROP_FPS)?;
    let fps = if fps > 0.0 && fps <= 300.0 { fps } else { 24.0 };
    let now = Local::now();
    if fps <= 0.0 {
        eprintln!(
            "{} ⚠️  Video FPS not found, defaulting to 24.0",
            now.format("%Y-%m-%d %H:%M:%S")
        );
    }
    eprintln!(
        "{} Video FPS source: {:.3}",
        now.format("%Y-%m-%d %H:%M:%S"),
        fps
    );

    // Read first frame to get dimensions
    let mut first_frame = Mat::default();
    cap.read(&mut first_frame)?;
    if first_frame.empty() {
        eprintln!("❌ Cannot read first frame");
        exit(1);
    }

    let h = first_frame.rows();
    let w = first_frame.cols();

    // Calculate left/right if not provided
    let (left, right) = if cli.left.is_none() || cli.right.is_none() {
        let vertical_perimeter_share = (2.0 * h as f64) / (2.0 * (h + w) as f64);
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

    let frame_size = Size::new(w, h);
    let zones = compute_led_zones(frame_size, counts);
    let fmt_word = if cli.rgbw { 1u8 } else { 0u8 };

    // Prepare in-memory output buffer - all processing happens in memory,
    // and we only write to disk once at the end for efficiency
    let mut data = Vec::new();

    // Write header: "AMb2" + f32 fps + u16 top + u16 bottom + u16 left + u16 right + u8 fmt
    data.write_all(b"AMb2")?;
    data.write_f32::<LittleEndian>(fps as f32)?;
    data.write_u16::<LittleEndian>(cli.top)?;
    data.write_u16::<LittleEndian>(cli.bottom)?;
    data.write_u16::<LittleEndian>(left)?;
    data.write_u16::<LittleEndian>(right)?;
    data.write_u8(fmt_word)?;

    // Reset to beginning
    cap.set(CAP_PROP_POS_FRAMES, 0.0)?;

    let mut frame_idx = 0u64;
    let mut total_frames_written = 0u64;

    loop {
        let mut frame = Mat::default();
        if !cap.read(&mut frame)? || frame.empty() {
            break;
        }

        // Calculate timestamp in microseconds
        let ts_us = ((frame_idx as f64 / fps) * 1_000_000.0) as u64;
        data.write_u64::<LittleEndian>(ts_us)?;

        // Extract colors for each zone
        for zone in &zones {
            let (b, g, r) = extract_edge_dominant_color(&frame, zone.0, zone.1, zone.2, zone.3)?;
            if cli.rgbw {
                data.write_all(&[r, g, b, 0])?;
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
        fps,
        elapsed
    );

    Ok(())
}
