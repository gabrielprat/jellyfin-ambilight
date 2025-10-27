use std::env;
use std::fs::File;
use std::io::{self, BufReader, Read, BufRead};
use std::net::UdpSocket;
use std::process::exit;
use std::sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}};
use std::thread::{self, sleep};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use byteorder::{LittleEndian, ReadBytesExt};
use signal_hook::consts::signal::*;
use signal_hook::iterator::Signals;
use clap::Parser;

#[inline]
fn clamp_f(v: f32, lo: f32, hi: f32) -> f32 {
    if v.is_nan() { return lo; }
    if v < lo { lo } else if v > hi { hi } else { v }
}

// Remap byte order for LED strip (interpreting inputs as R,G,B)
#[inline]
fn remap_order(r: u8, g: u8, b: u8, order: &str) -> (u8, u8, u8) {
    match order {
        "GRB" => (g, r, b),
        "BRG" => (b, r, g),
        "BGR" => (b, g, r),
        "GBR" => (g, b, r),
        _ => (r, g, b),
    }
}

// Rotate LED frame data by the specified number of LEDs
fn rotate_led_frame(frame: &[u8], rotation_leds: usize, total_leds: usize, bytes_per_led: usize) -> Vec<u8> {
    if rotation_leds == 0 || total_leds == 0 {
        return frame.to_vec();
    }

    let mut rotated = vec![0u8; frame.len()];

    for i in 0..total_leds {
        let dst_start = i * bytes_per_led;
        // Rotate clockwise from user's screen view: LED i gets color from position (i + rotation_leds)
        let src_led = (i + rotation_leds) % total_leds;
        let src_start = src_led * bytes_per_led;

        for b in 0..bytes_per_led {
            rotated[dst_start + b] = frame[src_start + b];
        }
    }

    rotated
}

#[derive(Parser, Debug)]
#[command(name = "ambilight-player", about = "Play ambilight binary to WLED over UDP")]
struct Cli {
    #[arg(long, help = "Path to AMb2 binary file")]
    file: String,

    #[arg(long, help = "WLED host or IP")]
    host: String,

    #[arg(long, default_value_t = 21324, help = "WLED UDP port")]
    port: u16,

    #[arg(long, default_value_t = 0.0, help = "Start time in seconds")]
    start: f64,

    #[arg(long, help = "Reference epoch seconds for launch delay compensation")]
    ref_epoch: Option<f64>,
}

fn main() -> std::io::Result<()> {
    // ---- graceful shutdown flags ----
    let running = Arc::new(AtomicBool::new(true));

    // SIGINT/SIGTERM handler
    {
        let running = running.clone();
        thread::spawn(move || {
            let mut signals = Signals::new([SIGINT, SIGTERM]).unwrap();
            for sig in signals.forever() {
                eprintln!("📴 Received signal {sig}, shutting down...");
                running.store(false, Ordering::SeqCst);
                break;
            }
        });
    }

    let cli = Cli::parse();
    let filepath = cli.file;
    let host = cli.host;
    let port = cli.port;
    let start_time = cli.start;
    let ref_epoch = cli.ref_epoch;

    // runtime envs (kept most names identical)
    let base_sync_lead = env::var("AMBILIGHT_SYNC_LEAD_SECONDS").unwrap_or_else(|_| "0.0".to_string())
        .parse::<f64>().unwrap_or(0.2);
    let mut adaptive_sync_lead = base_sync_lead;
    let smooth_seconds: f32 = env::var("AMBILIGHT_SMOOTH_SECONDS").unwrap_or_else(|_| "0.12".to_string()).parse().unwrap_or(0.12);
    let gamma_base: f32 = env::var("AMBILIGHT_GAMMA").unwrap_or_else(|_| "2.2".to_string()).parse().unwrap_or(2.2);
    let saturation: f32 = env::var("AMBILIGHT_SATURATION").unwrap_or_else(|_| "1.0".to_string()).parse().unwrap_or(1.0);
    let brightness_target: f32 = env::var("AMBILIGHT_BRIGHTNESS_TARGET").unwrap_or_else(|_| "60.0".to_string()).parse().unwrap_or(60.0);
    let led_order = env::var("AMBILIGHT_ORDER").unwrap_or_else(|_| "RGB".to_string());
    let gamma_red: f32 = env::var("AMBILIGHT_GAMMA_RED").unwrap_or_else(|_| "1.0".to_string()).parse().unwrap_or(1.0);
    let gamma_green: f32 = env::var("AMBILIGHT_GAMMA_GREEN").unwrap_or_else(|_| "1.0".to_string()).parse().unwrap_or(1.0);
    let gamma_blue: f32 = env::var("AMBILIGHT_GAMMA_BLUE").unwrap_or_else(|_| "1.0".to_string()).parse().unwrap_or(1.0);
    let red_boost = std::env::var("AMBILIGHT_RED_BOOST").ok().and_then(|v| v.parse::<f32>().ok()).unwrap_or(3.0);
    let blue_boost = std::env::var("AMBILIGHT_BLUE_BOOST").ok().and_then(|v| v.parse::<f32>().ok()).unwrap_or(4.0);
    let green_boost = std::env::var("AMBILIGHT_GREEN_BOOST").ok().and_then(|v| v.parse::<f32>().ok()).unwrap_or(1.0);
    let min_led_brightness: f32 = env::var("AMBILIGHT_MIN_LED_BRIGHTNESS").unwrap_or_else(|_| "0.0".to_string()).parse().unwrap_or(0.0);
    let input_position: u16 = std::env::var("AMBILIGHT_INPUT_POSITION").ok().and_then(|v| v.parse::<u16>().ok()).unwrap_or(0);
    let debug_enabled = std::env::var("AMBILIGHT_DEBUG").ok().and_then(|v| v.parse::<u8>().ok()).unwrap_or(0) != 0;

    // open file & header
    let f = File::open(&filepath).expect("Failed to open binary file");
    let mut reader = BufReader::new(f);

    let mut magic = [0u8; 4];
    reader.read_exact(&mut magic).expect("Failed to read magic");
    let mut fps: f64 = 0.0;
    let mut top_src: usize = 0;
    let mut bottom_src: usize = 0;
    let mut left_src: usize = 0;
    let mut right_src: usize = 0;
    let mut rgbw: bool = false;
    let bytes_per_led: usize;
    let frame_size: usize;

    if &magic == b"AMb2" {
        let fps_f = reader.read_f32::<LittleEndian>().unwrap_or(0.0) as f64;
        fps = if fps_f.is_finite() && fps_f > 0.001 && fps_f <= 300.0 { fps_f } else { 0.0 };
        top_src = reader.read_u16::<LittleEndian>().expect("Failed to read top") as usize;
        bottom_src = reader.read_u16::<LittleEndian>().expect("Failed to read bottom") as usize;
        left_src = reader.read_u16::<LittleEndian>().expect("Failed to read left") as usize;
        right_src = reader.read_u16::<LittleEndian>().expect("Failed to read right") as usize;
        let fmt_u8 = reader.read_u8().expect("Failed to read fmt");
        rgbw = fmt_u8 == 1;
        bytes_per_led = if rgbw { 4 } else { 3 };
        frame_size = (top_src + right_src + bottom_src + left_src) * bytes_per_led;
    } else {
        eprintln!("Invalid magic header");
        exit(1);
    }

    // target counts from env
    let tgt_top = std::env::var("AMBILIGHT_TOP_LED_COUNT").ok().and_then(|v| v.parse::<usize>().ok()).unwrap_or(top_src.max(1));
    let tgt_bottom = std::env::var("AMBILIGHT_BOTTOM_LED_COUNT").ok().and_then(|v| v.parse::<usize>().ok()).unwrap_or(bottom_src.max(1));
    let tgt_left = std::env::var("AMBILIGHT_LEFT_LED_COUNT").ok().and_then(|v| v.parse::<usize>().ok()).unwrap_or(left_src.max(1));
    let tgt_right = std::env::var("AMBILIGHT_RIGHT_LED_COUNT").ok().and_then(|v| v.parse::<usize>().ok()).unwrap_or(right_src.max(1));

    let total_src = if top_src+bottom_src+left_src+right_src > 0 { top_src+bottom_src+left_src+right_src } else { frame_size/bytes_per_led };
    let total_tgt = tgt_top + tgt_right + tgt_bottom + tgt_left;

    println!("🎬 Playing {} → src {} LEDs → tgt {} LEDs @ {:.3} FPS (input_position={}, rgbw={}, smooth={:.3}s, gamma={:.3}, sat={:.3}, min_led_brightness={:.1})",
        filepath, total_src, total_tgt, if fps>0.0 { fps } else { 0.0 }, input_position, rgbw, smooth_seconds, gamma_base, saturation, min_led_brightness);

    // load frames
    let mut frames: Vec<Vec<u8>> = Vec::new();
    let mut timestamps_us: Vec<u64> = Vec::new();

    loop {
        let mut ts_buf = [0u8; 8];
        if let Err(_) = reader.read_exact(&mut ts_buf) { break; }
        let ts = u64::from_le_bytes(ts_buf);

        let mut payload = vec![0u8; frame_size];
        if let Err(_) = reader.read_exact(&mut payload) {
            eprintln!("Short payload at end of file; discarding trailing timestamp.");
            break;
        }
        timestamps_us.push(ts);
        frames.push(payload);
    }

    println!("📦 Loaded {} frames", frames.len());
    if frames.is_empty() { eprintln!("No frames loaded; exiting."); return Ok(()); }

    if fps <= 0.0 && timestamps_us.len() >= 2 {
        let dt_us = (timestamps_us[1] as f64 - timestamps_us[0] as f64).abs();
        if dt_us > 0.0 { fps = 1e6 / dt_us; println!("Derived FPS from timestamps: {:.3}", fps); }
        else { fps = 24.0; println!("Fallback FPS: {:.3}", fps); }
    } else if fps <= 0.0 { fps = 24.0; println!("Fallback FPS: {:.3}", fps); }

    // socket
    let socket = UdpSocket::bind("0.0.0.0:0").expect("Failed to bind UDP socket");
    socket.set_nonblocking(true).ok(); // Non-blocking for better performance
    let remote = format!("{}:{}", host, port);
    socket.connect(&remote).expect("Failed to connect to WLED");
    println!("🔍 Socket local: {:?}", socket.local_addr());
    println!("🔍 Socket peer: {:?}", socket.peer_addr());

    let launch_delta = if let Some(re) = ref_epoch {
        let now_epoch = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_else(|_| Duration::from_secs(0)).as_secs_f64();
        (now_epoch - re).max(0.0)
    } else { 0.0 };

    let effective_start = (start_time + launch_delta + adaptive_sync_lead).max(0.0);
    let start_ts_us = (effective_start * 1_000_000.0) as u64;
    let mut start_frame = 0usize;
    while start_frame < timestamps_us.len() && timestamps_us[start_frame] < start_ts_us { start_frame += 1; }

    let mut frame_index = start_frame.min(frames.len());
    let mut start_instant = Instant::now();
    let mut elapsed_base = Duration::from_millis(0);
    let mut last_paused = false;

    // Processing latency measurement with EMA
    let mut processing_latency_ema: f64 = 0.0;
    let processing_ema_alpha = 0.1; // EMA smoothing factor
    let mut first_processing_measurement = true;

    // Simplified sync - no complex epoch mapping needed

    let mut ema_acc: Option<Vec<f32>> = None;
    let smooth_tau = clamp_f(smooth_seconds, 0.001, 5.0);

    let seek_target: Arc<Mutex<Option<f64>>> = Arc::new(Mutex::new(None));
    let paused_flag: Arc<Mutex<bool>> = Arc::new(Mutex::new(false));
    // Heartbeat shared storage: (video_pos_seconds, optional_epoch_seconds, received_instant)
    let beat_shared: Arc<Mutex<Option<(f64, Option<f64>, Instant)>>> = Arc::new(Mutex::new(None));
    let running_cmd: Arc<AtomicBool> = running.clone();
    let request_blank_on_exit = Arc::new(AtomicBool::new(false));
    let request_blank_on_exit_cmd = request_blank_on_exit.clone();

    {
        let seek_clone = Arc::clone(&seek_target);
        let paused_clone = Arc::clone(&paused_flag);
        let beat_sink = Arc::clone(&beat_shared);
        std::thread::spawn(move || {
            let stdin = io::stdin();
            let mut reader = io::BufReader::new(stdin.lock());
            let mut line = String::new();
            loop {
                if !running_cmd.load(Ordering::SeqCst) { break; }
                line.clear();
                if reader.read_line(&mut line).is_err() { break; }
                let trimmed = line.trim();
                if trimmed.is_empty() { continue; }
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() == 2 && (parts[0].eq_ignore_ascii_case("SEEK")) {
                    if let Ok(s) = parts[1].parse::<f64>() {
                        if let Ok(mut t) = seek_clone.lock() { *t = Some(s); }
                    }
                } else if parts.len() == 1 && parts[0].eq_ignore_ascii_case("PAUSE") {
                    if let Ok(mut p) = paused_clone.lock() { *p = true; }
                } else if parts.len() == 1 && parts[0].eq_ignore_ascii_case("RESUME") {
                    if let Ok(mut p) = paused_clone.lock() { *p = false; }
                } else if (parts.len() == 3 || parts.len() == 2) && parts[0].eq_ignore_ascii_case("BEAT") {
                    // BEAT <video_pos_seconds> [epoch_seconds]
                    if let Ok(pos) = parts[1].parse::<f64>() {
                        let epoch = if parts.len() >= 3 { parts[2].parse::<f64>().ok() } else { None };
                        if let Ok(mut hb) = beat_sink.lock() { *hb = Some((pos, epoch, Instant::now())); }
                    }
                } else if parts.len() == 1 && parts[0].eq_ignore_ascii_case("STOP") {
                    eprintln!("🟥 STOP received — will blank and exit.");
                    request_blank_on_exit_cmd.store(true, Ordering::SeqCst);
                    running_cmd.store(false, Ordering::SeqCst);
                    break;
                }
            }
        });
    }

    println!("▶️ Starting playback from frame {} (lead={:.3}s)", frame_index, adaptive_sync_lead);

    // Simplified sync - no complex drift correction needed
    while running.load(Ordering::SeqCst) && frame_index < frames.len() {
        // seek handling
        if let Ok(mut tgt) = seek_target.lock() {
            if let Some(sec) = *tgt {
                let target_us = ((sec + adaptive_sync_lead) * 1_000_000.0) as u64;
                let mut target_frame = 0usize;
                while target_frame < timestamps_us.len() && timestamps_us[target_frame] < target_us { target_frame += 1; }
                frame_index = target_frame.min(frames.len());
                start_frame = frame_index.min(frames.len());
                start_instant = Instant::now();
                elapsed_base = Duration::from_millis(0);
                eprintln!("🔄 SEEK to {:.3}s → frame {}", sec, frame_index);
                *tgt = None;
            }
        }

        let paused_now = if let Ok(p) = paused_flag.lock() { *p } else { false };

        if paused_now && !last_paused {
            elapsed_base += start_instant.elapsed();
            eprintln!("⏸️  Paused playback");
        }
        if !paused_now && last_paused {
            start_instant = Instant::now();
            eprintln!("▶️  Resumed playback");
        }
        last_paused = paused_now;

        if paused_now {
            static mut SENT_BLANK_ON_PAUSE: bool = false;
            unsafe {
                if !SENT_BLANK_ON_PAUSE {
                    let zeroes = vec![0u8; total_tgt * bytes_per_led];
                    match socket.send(&zeroes) {
                        Ok(n) => eprintln!("🕳️ Sent blank frame on pause ({} bytes)", n),
                        Err(e) => eprintln!("🕳️ Failed to send blank on pause: {}", e),
                    }
                    SENT_BLANK_ON_PAUSE = true;
                }
            }
            sleep(Duration::from_millis(80));
            continue;
        } else {
            // reset blank flag (unsafe used above) - safe no-op here
        }

        // Simplified timing: Use frame-accurate timestamps directly
        let frame_timestamp_us = if frame_index < timestamps_us.len() {
            timestamps_us[frame_index]
        } else {
            // Fallback to calculated timestamp if we're beyond the data
            let calculated_us = ((frame_index as f64) / fps * 1_000_000.0) as u64;
            calculated_us
        };

        // Calculate when this frame should be displayed (absolute time since start)
        let frame_target_time_us = if start_frame < timestamps_us.len() {
            frame_timestamp_us.saturating_sub(timestamps_us[start_frame])
        } else {
            ((frame_index - start_frame) as f64 / fps * 1_000_000.0) as u64
        };

        let frame_target_time = Duration::from_micros(frame_target_time_us);
        let elapsed_since_start = elapsed_base + start_instant.elapsed();

        // Sleep until frame time, compensating for processing latency
        if elapsed_since_start < frame_target_time {
            let mut sleep_duration = frame_target_time - elapsed_since_start;
            // Subtract processing latency to maintain consistent timing
            let processing_compensation = Duration::from_secs_f64(processing_latency_ema);
            if sleep_duration > processing_compensation {
                sleep_duration -= processing_compensation;
            }
            sleep(sleep_duration);
        }

        // Start processing latency measurement
        let processing_start_time = Instant::now();

        let raw = &frames[frame_index];

        // Calculate rotation for target LED strip (applied after scaling and color processing)
        let rot_leds = if total_tgt > 0 { (input_position as usize) % total_tgt } else { 0usize };

        // compute avg luminance
        let mut sum_lum: f32 = 0.0;
        let mut count_pix: usize = 0;
        let mut idx = 0usize;
        while idx + 2 < raw.len() {
            let r = raw[idx] as f32;
            let g = raw[idx + 1] as f32;
            let b = raw[idx + 2] as f32;
            let lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            sum_lum += lum;
            count_pix += 1;
            idx += bytes_per_led;
        }
        let avg_lum = if count_pix > 0 { sum_lum / (count_pix as f32) } else { 0.0 };
        let gamma_adj = clamp_f(gamma_base * (1.0 - (avg_lum / 255.0) * 0.6), 1.0, 3.0);
        let inv_gamma = 1.0 / gamma_adj;

        let frame_dt_s = if frame_index == 0 {
            (1.0 / fps) as f32
        } else {
            let prev_us = timestamps_us.get(frame_index.saturating_sub(1)).cloned().unwrap_or(0) as f64;
            let cur_us = timestamps_us[frame_index] as f64;
            let dt = (cur_us - prev_us) / 1e6;
            if dt <= 0.0 { (1.0 / fps) as f32 } else { dt as f32 }
        };
        let k = 1.0 - (-frame_dt_s / smooth_tau).exp();

        if ema_acc.is_none() {
            // initialize with target length (so EMA state matches what will be sent)
            let mut init_acc = vec![0.0f32; total_tgt * bytes_per_led];
            // initialize by sampling source -> target
            for t in 0..total_tgt {
                let src_idx = if total_tgt > 0 { (t * total_src) / total_tgt } else { 0 };
                let sb = src_idx * bytes_per_led;
                for b in 0..bytes_per_led {
                    init_acc[t * bytes_per_led + b] = raw[sb + b] as f32;
                }
            }
            ema_acc = Some(init_acc);
        }

        let acc = ema_acc.as_mut().unwrap();
        let mut out_frame = vec![0u8; total_tgt * bytes_per_led];

        let s_user = clamp_f(saturation, 0.0, 5.0);
        let g_user = gamma_base.max(0.01);
        let b_target = brightness_target.max(1.0);
        let min_b = min_led_brightness.max(0.0);

        let brightness_factor = if avg_lum > 1.0 {
            let factor = (b_target / avg_lum) * 0.7 + 0.3;
            clamp_f(factor, 0.05, 2.5)
        } else { 1.0 };

        // Process each target LED with improved color accuracy
        for t in 0..total_tgt {
            let src_idx = if total_tgt > 0 { (t * total_src) / total_tgt } else { 0 };
            let sb = src_idx * bytes_per_led;

            let r_u = raw[sb] as f32;
            let g_u = raw[sb + 1] as f32;
            let b_u = raw[sb + 2] as f32;

            // Normalize to 0-1 range
            let r_n = (r_u / 255.0).max(0.0).min(1.0);
            let g_n = (g_u / 255.0).max(0.0).min(1.0);
            let b_n = (b_u / 255.0).max(0.0).min(1.0);

            // Apply individual channel gamma correction (more precise)
            let r_lin = r_n.powf(gamma_red);
            let g_lin = g_n.powf(gamma_green);
            let b_lin = b_n.powf(gamma_blue);

            // Apply saturation adjustment in RGB space (preserves color relationships better)
            let avg_intensity = (r_lin + g_lin + b_lin) / 3.0;
            let r_sat = avg_intensity + (r_lin - avg_intensity) * s_user;
            let g_sat = avg_intensity + (g_lin - avg_intensity) * s_user;
            let b_sat = avg_intensity + (b_lin - avg_intensity) * s_user;

            // Apply inverse gamma correction
            let r_g = clamp_f(r_sat.powf(inv_gamma), 0.0, 1.0);
            let g_g = clamp_f(g_sat.powf(inv_gamma), 0.0, 1.0);
            let b_g = clamp_f(b_sat.powf(inv_gamma), 0.0, 1.0);

            // Apply brightness adjustment (more conservative)
            let brightness_factor_adj = clamp_f(brightness_factor, 0.3, 1.8);
            let r_f = r_g * brightness_factor_adj * 255.0;
            let g_f = g_g * brightness_factor_adj * 255.0;
            let b_f = b_g * brightness_factor_adj * 255.0;

            let base = t * bytes_per_led;
            acc[base]     = acc[base]     * (1.0 - k) + r_f * k;
            acc[base + 1] = acc[base + 1] * (1.0 - k) + g_f * k;
            acc[base + 2] = acc[base + 2] * (1.0 - k) + b_f * k;

            let mut r_out = acc[base].round();
            let mut g_out = acc[base + 1].round();
            let mut b_out = acc[base + 2].round();

            let min_r = min_b * red_boost;
            let min_g = min_b * green_boost;
            let min_b_b = min_b * blue_boost;

            if r_out > 0.0 && r_out < min_r { r_out = min_r; }
            if g_out > 0.0 && g_out < min_g { g_out = min_g; }
            if b_out > 0.0 && b_out < min_b_b { b_out = min_b_b; }

            let lum = 0.2126*r_out + 0.7152*g_out + 0.0722*b_out;
            if lum < min_b * 0.5 {
                r_out = 0.0;
                g_out = 0.0;
                b_out = 0.0;
            }

            let (r_m, g_m, b_m) = remap_order(r_out as u8, g_out as u8, b_out as u8, &led_order);

            out_frame[base] = r_m;
            out_frame[base + 1] = g_m;
            out_frame[base + 2] = b_m;

            if bytes_per_led == 4 {
                // propagate W channel EMA from source W (if present)
                let src_w_idx = src_idx * bytes_per_led + 3;
                let w_val = raw[src_w_idx] as f32;
                acc[base + 3] = acc[base + 3] * (1.0 - k) + w_val * k;
                out_frame[base + 3] = acc[base + 3].round().min(255.0).max(0.0) as u8;
            }
        }

        // Apply input position rotation to final target frame
        if rot_leds > 0 {
            let rotated_frame = rotate_led_frame(&out_frame, rot_leds, total_tgt, bytes_per_led);
            if debug_enabled {
                eprintln!("🔄 Applied rotation: {} LEDs clockwise (LED 0 now shows color from position {})", rot_leds, rot_leds);
            }
            match socket.send(&rotated_frame) {
                Ok(n) => {
                    if debug_enabled {
                        eprintln!("➡️ Sent frame {} -> {} bytes (tgt_leds={}, rotated by {})", frame_index, n, total_tgt, rot_leds);
                    }
                }
                Err(e) => {
                    match e.kind() {
                        std::io::ErrorKind::WouldBlock => {
                            // Non-blocking socket - this is expected occasionally
                            if debug_enabled {
                                eprintln!("⚠️ Socket would block for frame {} (non-blocking)", frame_index);
                            }
                        }
                        _ => {
                            eprintln!("❌ Failed to send frame {} : {}", frame_index, e);
                        }
                    }
                }
            }
        } else {
            // send and check result
            match socket.send(&out_frame) {
                Ok(n) => {
                    if debug_enabled {
                        eprintln!("➡️ Sent frame {} -> {} bytes (tgt_leds={})", frame_index, n, total_tgt);
                    }
                }
                Err(e) => {
                    match e.kind() {
                        std::io::ErrorKind::WouldBlock => {
                            // Non-blocking socket - this is expected occasionally
                            if debug_enabled {
                                eprintln!("⚠️ Socket would block for frame {} (non-blocking)", frame_index);
                            }
                        }
                        _ => {
                            eprintln!("❌ Failed to send frame {} : {}", frame_index, e);
                        }
                    }
                }
            }
        }

        // Measure and EMA processing latency
        let processing_duration = processing_start_time.elapsed().as_secs_f64();
        if first_processing_measurement {
            processing_latency_ema = processing_duration;
            first_processing_measurement = false;
        } else {
            processing_latency_ema = processing_latency_ema * (1.0 - processing_ema_alpha) + processing_duration * processing_ema_alpha;
        }

        if debug_enabled && frame_index % 100 == 0 {
            eprintln!("📊 Processing latency EMA: {:.1}ms", processing_latency_ema * 1000.0);
        }

        // Simplified sync - no complex heartbeat corrections
        // Just clear any received heartbeat to prevent accumulation
        if beat_shared.lock().ok().map_or(false, |g| g.is_some()) {
            if let Ok(mut g) = beat_shared.lock() { *g = None; }
        }

        frame_index += 1;
    }

    // blank on exit if requested
    if request_blank_on_exit.load(Ordering::SeqCst) || !running.load(Ordering::SeqCst) {
        let zeroes = vec![0u8; total_tgt * bytes_per_led];
        for _ in 0..3 {
            match socket.send(&zeroes) {
                Ok(n) => eprintln!("🧹 Sent blank ({} bytes)", n),
                Err(e) => eprintln!("🧹 Failed blank send: {}", e),
            }
            sleep(Duration::from_millis(20));
        }
        eprintln!("🧹 Sent blank frames on exit");
    }

    println!("🏁 Playback complete or stopped.");
    Ok(())
}
