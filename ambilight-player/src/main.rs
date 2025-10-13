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

#[inline]
fn clamp_f(v: f32, lo: f32, hi: f32) -> f32 {
    if v.is_nan() { return lo; }
    if v < lo { lo } else if v > hi { hi } else { v }
}

// Convert RGB -> HSV (expects components in 0..1)
#[inline]
fn rgb_to_hsv(r: f32, g: f32, b: f32) -> (f32, f32, f32) {
    let max = r.max(g.max(b));
    let min = r.min(g.min(b));
    let d = max - min;
    let v = max;
    let s = if max == 0.0 { 0.0 } else { d / max };
    let mut h = if d == 0.0 {
        0.0
    } else if max == r {
        ((g - b) / d) % 6.0
    } else if max == g {
        ((b - r) / d) + 2.0
    } else {
        ((r - g) / d) + 4.0
    };
    h = h * 60.0;
    if h < 0.0 { h += 360.0; }
    (h, s, v)
}

// Convert HSV -> RGB (returns 0..1)
#[inline]
fn hsv_to_rgb(mut h: f32, s: f32, v: f32) -> (f32, f32, f32) {
    h = ((h % 360.0) + 360.0) % 360.0;
    let c = v * s;
    let x = c * (1.0 - ((h / 60.0) % 2.0 - 1.0).abs());
    let m = v - c;
    let (r1, g1, b1) = match h {
        h if h < 60.0 => (c, x, 0.0),
        h if h < 120.0 => (x, c, 0.0),
        h if h < 180.0 => (0.0, c, x),
        h if h < 240.0 => (0.0, x, c),
        h if h < 300.0 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    (r1 + m, g1 + m, b1 + m)
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

fn main() -> std::io::Result<()> {
    // ---- graceful shutdown flags ----
    let running = Arc::new(AtomicBool::new(true));

    // 1️⃣  SIGINT/SIGTERM handler
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

    // NOTE: Do not start another stdin consumer here; the command thread below reads stdin.

    // ---- Arguments parsing
    let args: Vec<String> = env::args().collect();
    if args.len() < 9 {
        eprintln!(
            "Usage: {} --file <path> --host <host> --port <port> --start <start_time> [--ref-epoch <unix_seconds>]",
            args[0]
        );
        exit(1);
    }

    let mut filepath = String::new();
    let mut host = String::new();
    let mut port: u16 = 0;
    let mut start_time: f64 = 0.0;
    let mut ref_epoch: f64 = 0.0;
    let mut has_ref_epoch = false;

    let sync_lead = env::var("AMBILIGHT_SYNC_LEAD_SECONDS").unwrap_or_else(|_| "0.2".to_string())
        .parse::<f64>().unwrap_or(0.2);

    // Runtime tunables (env)
    let smooth_seconds: f32 = env::var("AMBILIGHT_SMOOTH_SECONDS").unwrap_or_else(|_| "0.12".to_string()).parse().unwrap_or(0.12);
    let gamma_base: f32 = env::var("AMBILIGHT_GAMMA").unwrap_or_else(|_| "2.2".to_string()).parse().unwrap_or(2.2);
    let saturation: f32 = env::var("AMBILIGHT_SATURATION").unwrap_or_else(|_| "1.0".to_string()).parse().unwrap_or(1.0);
    let brightness_target: f32 = env::var("AMBILIGHT_BRIGHTNESS_TARGET").unwrap_or_else(|_| "60.0".to_string()).parse().unwrap_or(60.0);
    let led_order = env::var("AMBILIGHT_ORDER").unwrap_or_else(|_| "RGB".to_string());
    // NEW: minimum LED brightness in 0..255
    let min_led_brightness: f32 = env::var("AMBILIGHT_MIN_LED_BRIGHTNESS").unwrap_or_else(|_| "0.0".to_string()).parse().unwrap_or(0.0);
    // simple time correction (disabled for now)
    let mut time_correction_s = 0.0;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--file" => filepath = args[i + 1].clone(),
            "--host" => host = args[i + 1].clone(),
            "--port" => port = args[i + 1].parse().unwrap_or(19446),
            "--start" => start_time = args[i + 1].parse().unwrap_or(0.0),
            "--ref-epoch" => { ref_epoch = args[i + 1].parse().unwrap_or(0.0); has_ref_epoch = true; },
            _ => {}
        }
        i += 2;
    }

    // ---- Open file & parse header
    let f = File::open(&filepath).expect("Failed to open binary file");
    let mut reader = BufReader::new(f);

    let mut magic = [0u8; 4];
    reader.read_exact(&mut magic).expect("Failed to read magic");
    if &magic != b"AMBI" {
        eprintln!("Invalid magic header");
        exit(1);
    }

    let fps_f = reader.read_f32::<LittleEndian>().unwrap_or(0.0) as f64;
    let mut fps = fps_f;
    if !fps_f.is_finite() || fps_f <= 0.001 || fps_f > 300.0 {
        eprintln!("⚠️ Invalid FPS in header, will rely on timestamps or fallback");
        fps = 0.0;
    }

    let led_count = reader.read_u16::<LittleEndian>().expect("Failed to read led_count") as usize;
    let fmt_u = reader.read_u16::<LittleEndian>().expect("Failed to read fmt");
    let offset = reader.read_u16::<LittleEndian>().expect("Failed to read offset");
    let rgbw = fmt_u == 1;

    let bytes_per_led = if rgbw { 4 } else { 3 };
    let frame_size = led_count * bytes_per_led;

    println!("🎬 Playing {} → {} LEDs @ {:.3} FPS (offset={}, rgbw={}, smooth={:.3}s, gamma={:.3}, sat={:.3}, min_led_brightness={:.1})",
        filepath, led_count, if fps>0.0 { fps } else { 0.0 }, offset, rgbw, smooth_seconds, gamma_base, saturation, min_led_brightness);

    // ---- Load frames into memory
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

    let socket = UdpSocket::bind("0.0.0.0:0").expect("Failed to bind UDP socket");
    socket.connect(format!("{}:{}", host, port)).expect("Failed to connect to WLED");
    // print socket status and remote address
    println!("🔍 Socket status: {:?}", socket.local_addr());
    println!("🔍 Remote address: {:?}", socket.peer_addr());
    let launch_delta = if has_ref_epoch {
        let now_epoch = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_else(|_| Duration::from_secs(0)).as_secs_f64();
        (now_epoch - ref_epoch).max(0.0)
    } else { 0.0 };

    let effective_start = (start_time + launch_delta + sync_lead).max(0.0);
    let start_ts_us = (effective_start * 1_000_000.0) as u64;
    let mut start_frame = 0usize;
    while start_frame < timestamps_us.len() && timestamps_us[start_frame] < start_ts_us { start_frame += 1; }

    let mut frame_index = start_frame.min(frames.len());
    let mut start_instant = Instant::now();
    let mut elapsed_base = Duration::from_millis(0);
    let mut last_paused = false;

    // New: time correction from first-frame calibration (seconds, can be negative — allows leading)
    let mut time_correction_s: f64 = 0.0;
    let mut first_calibrated = false;

    let mut ema_acc: Option<Vec<f32>> = None;
    let smooth_tau = clamp_f(smooth_seconds, 0.001, 5.0);

    let seek_target: Arc<Mutex<Option<f64>>> = Arc::new(Mutex::new(None));
    let paused_flag: Arc<Mutex<bool>> = Arc::new(Mutex::new(false));
    let running_cmd: Arc<AtomicBool> = running.clone();
    {
        let seek_clone = Arc::clone(&seek_target);
        let paused_clone = Arc::clone(&paused_flag);
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
                } else if parts.len() == 1 && parts[0].eq_ignore_ascii_case("STOP") {
                    eprintln!("🟥 STOP received, clearing LEDs and exiting...");
                    let zeroes = vec![0u8; frame_size];
                    let _ = UdpSocket::bind("0.0.0.0:0")
                        .and_then(|s| s.send_to(&zeroes, format!("{}:{}", host, port)));
                    std::process::exit(0);
                }
            }
        });
    }

    println!("▶️ Starting playback from frame {} (lead={:.3}s)", frame_index, sync_lead);
    while running.load(Ordering::SeqCst) && frame_index < frames.len() {
        while running.load(Ordering::SeqCst) && frame_index < frames.len() {
            if let Ok(mut tgt) = seek_target.lock() {
                if let Some(sec) = *tgt {
                    let target_us = ((sec + sync_lead) * 1_000_000.0) as u64;
                    let mut target_frame = 0usize;
                    while target_frame < timestamps_us.len() && timestamps_us[target_frame] < target_us { target_frame += 1; }
                    frame_index = target_frame.min(frames.len());
                    start_frame = frame_index.min(frames.len());
                    start_instant = Instant::now();
                    elapsed_base = Duration::from_millis(0);
                    // reset calibration on manual seek (we'll recalibrate on next frames)
                    first_calibrated = false;
                    time_correction_s = 0.0;
                    eprintln!("🔄 SEEK to {:.3}s → frame {}", sec, frame_index);
                    *tgt = None;
                }
            }

            let paused_now = if let Ok(p) = paused_flag.lock() { *p } else { false };
            // --- Handle pause / resume logic ---
            if paused_now && !last_paused {
                // Just entered pause
                elapsed_base += start_instant.elapsed();
                eprintln!("⏸️  Paused playback");
            }
            if !paused_now && last_paused {
                // Just resumed
                start_instant = Instant::now();
                eprintln!("▶️  Resumed playback");
            }
            last_paused = paused_now;

            // While paused, don't advance frames; send one zero frame when pause is entered
            if paused_now {
                static mut SENT_BLANK_ON_PAUSE: bool = false;
                unsafe {
                    if !SENT_BLANK_ON_PAUSE {
                        let zeroes = vec![0u8; frame_size];
                        let _ = socket.send(&zeroes);
                        SENT_BLANK_ON_PAUSE = true;
                        eprintln!("🕳️  Sent blank frame on pause");
                    }
                }
                sleep(Duration::from_millis(80));
                continue;
            } else {
                // reset blank flag on resume
                unsafe { /* scoped reset */ }
            }

            // compute ideal target_time relative to start_frame (seconds)
            let rel_us = if frame_index < timestamps_us.len() && start_frame < timestamps_us.len() {
                timestamps_us[frame_index].saturating_sub(timestamps_us[start_frame])
            } else {
                // fallback using fps spacing
                ((frame_index - start_frame) as f64 * (1.0 / fps) * 1_000_000.0) as u64
            };
            let rel_s = (rel_us as f64) / 1_000_000.0;

            // target relative seconds after applying correction and lead (can be negative)
            let target_rel_s = rel_s - time_correction_s - sync_lead;
            // convert to Duration for sleeping; if negative, we don't sleep (we lead/send immediately)
            let target_time = if target_rel_s > 0.0 {
                Duration::from_secs_f64(target_rel_s)
            } else {
                Duration::from_millis(0)
            };

            let elapsed = elapsed_base + start_instant.elapsed();
            if elapsed < target_time { sleep(target_time - elapsed); }

            let raw = &frames[frame_index];

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
                let mut init_acc = vec![0.0f32; raw.len()];
                let mut ib = 0usize;
                while ib + 2 < raw.len() {
                    init_acc[ib] = raw[ib] as f32;
                    init_acc[ib + 1] = raw[ib + 1] as f32;
                    init_acc[ib + 2] = raw[ib + 2] as f32;
                    if bytes_per_led == 4 { init_acc[ib + 3] = raw[ib + 3] as f32; }
                    ib += bytes_per_led;
                }
                ema_acc = Some(init_acc);
            }

            let acc = ema_acc.as_mut().unwrap();
            let mut out_frame = vec![0u8; raw.len()];

            let s_user = clamp_f(saturation, 0.0, 5.0);
            let g_user = gamma_base.max(0.01);
            let b_target = brightness_target.max(1.0);
            let min_b = min_led_brightness.max(0.0);

            let brightness_factor = if avg_lum > 1.0 {
                let factor = (b_target / avg_lum) * 0.7 + 0.3;
                clamp_f(factor, 0.05, 2.5)
            } else { 1.0 };

            let mut ib = 0usize;
            while ib + 2 < raw.len() {
                let r_u = raw[ib] as f32;
                let g_u = raw[ib + 1] as f32;
                let b_u = raw[ib + 2] as f32;

                let r_n = (r_u / 255.0).max(0.0).min(1.0);
                let g_n = (g_u / 255.0).max(0.0).min(1.0);
                let b_n = (b_u / 255.0).max(0.0).min(1.0);

                let r_lin = r_n.powf(g_user);
                let g_lin = g_n.powf(g_user);
                let b_lin = b_n.powf(g_user);

                let (h, s, v) = rgb_to_hsv(r_lin, g_lin, b_lin);
                let s_new = clamp_f(s * s_user, 0.0, 1.0);
                let (r_s, g_s, b_s) = hsv_to_rgb(h, s_new, v);

                let r_g = clamp_f(r_s.powf(inv_gamma), 0.0, 1.0);
                let g_g = clamp_f(g_s.powf(inv_gamma), 0.0, 1.0);
                let b_g = clamp_f(b_s.powf(inv_gamma), 0.0, 1.0);

                let r_f = r_g * brightness_factor * 255.0;
                let g_f = g_g * brightness_factor * 255.0;
                let b_f = b_g * brightness_factor * 255.0;

                acc[ib]     = acc[ib]     * (1.0 - k) + r_f * k;
                acc[ib + 1] = acc[ib + 1] * (1.0 - k) + g_f * k;
                acc[ib + 2] = acc[ib + 2] * (1.0 - k) + b_f * k;

                let mut r_out = acc[ib].round();
                let mut g_out = acc[ib + 1].round();
                let mut b_out = acc[ib + 2].round();

                // --- APPLY TRUE MIN LED BRIGHTNESS ---
                let lum = 0.2126*r_out + 0.7152*g_out + 0.0722*b_out;
                if lum < min_b {
                    r_out = 0.0;
                    g_out = 0.0;
                    b_out = 0.0;
                }

                let (r_m, g_m, b_m) = remap_order(r_out as u8, g_out as u8, b_out as u8, &led_order);

                out_frame[ib]     = r_m;
                out_frame[ib + 1] = g_m;
                out_frame[ib + 2] = b_m;

                if bytes_per_led == 4 {
                    let w_idx = ib + 3;
                    acc[w_idx] = acc[w_idx] * (1.0 - k) + (raw[w_idx] as f32) * k;
                    out_frame[w_idx] = acc[w_idx].round().min(255.0).max(0.0) as u8;
                }

                ib += bytes_per_led;
            }
            // (PLL-based sync correction removed due to instability)

            let _ = socket.send(&out_frame);

            frame_index += 1;
        }
    }
    println!("🏁 Playback complete or stopped.");
    Ok(())
}
