use std::env;
use std::fs::File;
use std::io::{self, BufReader, Read, BufRead};
use std::net::UdpSocket;
use std::process::exit;
use std::sync::{Arc, Mutex};
use std::thread::sleep;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use byteorder::{LittleEndian, ReadBytesExt};

fn main() {
    // ---- Parse arguments ----
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

    let sync_lead = env::var("AMBILIGHT_SYNC_LEAD_SECONDS")
        .unwrap_or_else(|_| "0.2".to_string())
        .parse::<f64>()
        .unwrap_or(0.2);

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--file" => filepath = args[i + 1].clone(),
            "--host" => host = args[i + 1].clone(),
            "--port" => port = args[i + 1].parse().unwrap_or(19446),
            "--start" => start_time = args[i + 1].parse().unwrap_or(0.0),
            "--ref-epoch" => {
                ref_epoch = args[i + 1].parse().unwrap_or(0.0);
                has_ref_epoch = true;
            }
            _ => {}
        }
        i += 2;
    }

    // ---- Open binary file ----
    let file = File::open(&filepath).expect("Failed to open binary file");
    let mut reader = BufReader::new(file);

    // ---- Read header ----
    let mut magic = [0u8; 4];
    reader.read_exact(&mut magic).expect("Failed to read magic");
    if &magic != b"AMBI" {
        eprintln!("Invalid file header");
        exit(1);
    }

    let mut fps = reader.read_f32::<LittleEndian>().expect("Failed to read FPS");
    if !fps.is_finite() || fps <= 0.1 || fps > 300.0 {
        eprintln!("⚠️ Invalid FPS in header, falling back to 24");
        fps = 24.0;
    }

    let led_count = reader.read_u16::<LittleEndian>().expect("Failed to read LED count");
    let fmt_u16 = reader.read_u16::<LittleEndian>().expect("Failed to read format");
    let offset = reader.read_u16::<LittleEndian>().expect("Failed to read offset");
    let rgbw = fmt_u16 == 1;

    println!(
        "🎬 Playing {} → {} LEDs @ {:.3} FPS (offset={}, rgbw={})",
        filepath, led_count, fps, offset, rgbw
    );

    let bytes_per_led = if rgbw { 4 } else { 3 };
    let frame_size = (led_count as usize) * bytes_per_led;

    // ---- Load all frames into memory (timestamps + payloads) ----
    let mut frames: Vec<Vec<u8>> = Vec::new();
    let mut timestamps_us: Vec<u64> = Vec::new();
    let mut ts_buf = [0u8; 8];
    let mut payload_buf = vec![0u8; frame_size];

    loop {
        match reader.read_exact(&mut ts_buf) {
            Ok(()) => {
                let ts_us = u64::from_le_bytes(ts_buf);
                timestamps_us.push(ts_us);
                if let Err(_) = reader.read_exact(&mut payload_buf) {
                    timestamps_us.pop();
                    break;
                }
                frames.push(payload_buf.clone());
            }
            Err(_) => break,
        }
    }

    println!("📦 Loaded {} frames", frames.len());

    // ---- Setup UDP socket ----
    let socket = UdpSocket::bind("0.0.0.0:0").expect("Failed to bind UDP socket");
    socket.connect(format!("{}:{}", host, port)).expect("Failed to connect to WLED");

    // ---- Start time / wall-clock sync ----
    let launch_delta = if has_ref_epoch {
        let now_epoch = SystemTime::now().duration_since(UNIX_EPOCH)
            .unwrap_or_else(|_| Duration::from_secs(0)).as_secs_f64();
        (now_epoch - ref_epoch).max(0.0)
    } else {
        0.0
    };

    let effective_start_time = (start_time + launch_delta + sync_lead).max(0.0);
    let start_ts_us = (effective_start_time * 1_000_000.0) as u64;
    let mut start_frame = 0;
    while start_frame < timestamps_us.len() && timestamps_us[start_frame] < start_ts_us {
        start_frame += 1;
    }

    let mut frame_index = start_frame.min(frames.len());
    let mut start_instant = Instant::now();
    let mut elapsed_base = Duration::from_millis(0);
    let mut last_paused = false;

    // ---- Command channel (stdin) for live resync ----
    let seek_target_s: Arc<Mutex<Option<f64>>> = Arc::new(Mutex::new(None));
    let paused_flag: Arc<Mutex<bool>> = Arc::new(Mutex::new(false));
    {
        let seek_target_s_reader = Arc::clone(&seek_target_s);
        let paused_flag_reader = Arc::clone(&paused_flag);
        std::thread::spawn(move || {
            let stdin = io::stdin();
            let mut reader = io::BufReader::new(stdin.lock());
            let mut line = String::new();
            loop {
                line.clear();
                if reader.read_line(&mut line).is_err() { break; }
                let trimmed = line.trim();
                if trimmed.is_empty() { continue; }
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() == 2 && (parts[0].eq_ignore_ascii_case("SEEK")) {
                    if let Ok(sec) = parts[1].parse::<f64>() {
                        if let Ok(mut tgt) = seek_target_s_reader.lock() {
                            *tgt = Some(sec);
                        }
                    }
                } else if parts.len() == 1 && (parts[0].eq_ignore_ascii_case("PAUSE")) {
                    if let Ok(mut p) = paused_flag_reader.lock() { *p = true; }
                } else if parts.len() == 1 && (parts[0].eq_ignore_ascii_case("RESUME")) {
                    if let Ok(mut p) = paused_flag_reader.lock() { *p = false; }
                }
            }
        });
    }

    println!(
        "▶️ Starting playback from frame {} (lead={:.3}s)",
        frame_index, sync_lead
    );

    // ---- Playback loop with smoothing ----
    let base_smooth: f32 = 0.3; // 150ms smoothing
    let mut prev_frame: Option<Vec<u8>> = None;

    while frame_index < frames.len() {
        // Handle seeks
        if let Ok(mut tgt) = seek_target_s.lock() {
            if let Some(sec) = *tgt {
                let target_us = ((sec + sync_lead) * 1_000_000.0) as u64;
                let mut target_frame = 0;
                while target_frame < timestamps_us.len() && timestamps_us[target_frame] < target_us {
                    target_frame += 1;
                }
                frame_index = target_frame.min(frames.len());
                start_frame = frame_index.min(frames.len());
                start_instant = Instant::now();
                elapsed_base = Duration::from_millis(0);
                eprintln!("🔄 SEEK to {:.3}s → frame {}", sec, frame_index);
                *tgt = None;
            }
        }

        // Pause/resume
        let paused_now = if let Ok(p) = paused_flag.lock() { *p } else { false };
        if paused_now != last_paused {
            if paused_now { elapsed_base += start_instant.elapsed(); }
            else { start_instant = Instant::now(); }
            last_paused = paused_now;
        }

        if paused_now {
            sleep(Duration::from_millis(10));
            continue;
        }

        // Compute target frame timestamp
        let target_time = if frame_index < timestamps_us.len() && start_frame < timestamps_us.len() {
            let rel_us = timestamps_us[frame_index].saturating_sub(timestamps_us[start_frame]);
            Duration::from_micros(rel_us as u64)
        } else {
            Duration::from_secs_f64((frame_index - start_frame) as f64 / fps as f64)
        };

        let elapsed = elapsed_base + start_instant.elapsed();
        if elapsed < target_time {
            sleep(target_time - elapsed);
        }

        let mut frame = frames[frame_index].clone();

        // --- Smooth blending with previous frame ---
        if let Some(prev) = &prev_frame {
            let alpha = base_smooth.min(1.0);
            for i in 0..frame.len() {
                let blended = (frame[i] as f32 * alpha + prev[i] as f32 * (1.0 - alpha)).round();
                frame[i] = blended.min(255.0) as u8;
            }
        }

        prev_frame = Some(frame.clone());

        // Apply offset rotation
        if offset > 0 {
            let n = (offset as usize * bytes_per_led) % frame.len();
            frame.rotate_right(n);
        }

        if socket.send(&frame).is_err() {
            eprintln!("⚠️ UDP send failed at frame {}", frame_index);
        }

        frame_index += 1;
    }

    println!("🏁 Playback complete.");
}
