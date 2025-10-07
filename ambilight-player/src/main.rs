use std::env;
use std::fs::File;
use std::io::{self, Read, BufRead};
use std::net::UdpSocket;
use std::thread::sleep;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use std::process::exit;
use std::sync::{Arc, Mutex};

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
    let mut has_ref_epoch: bool = false;

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

    // ---- Read binary file ----
    let mut file = File::open(&filepath).expect("Failed to open binary file");

    let mut header = [0u8; 9];
    file.read_exact(&mut header).expect("Failed to read header");

    if &header[0..4] != b"AMBI" {
        eprintln!("Invalid file header");
        exit(1);
    }

    let fps = u16::from_le_bytes([header[4], header[5]]) as f64;
    let led_count = u16::from_le_bytes([header[6], header[7]]);
    let fmt = header[8];
    let rgbw = fmt == 1;

    let mut offset_buf = [0u8; 2];
    file.read_exact(&mut offset_buf).expect("Failed to read offset");
    let offset = u16::from_le_bytes(offset_buf);

    println!(
        "🎬 Playing {} → {} LEDs @ {:.2} FPS (offset={}, rgbw={})",
        filepath, led_count, fps, offset, rgbw
    );

    // ---- Setup UDP socket ----
    let socket = UdpSocket::bind("0.0.0.0:0").expect("Failed to bind UDP socket");
    socket.connect(format!("{}:{}", host, port))
        .expect("Failed to connect to WLED");

    let bytes_per_led = if rgbw { 4 } else { 3 };
    let frame_size = (led_count as usize) * bytes_per_led;
    let frame_duration = Duration::from_secs_f64(1.0 / fps);

    // ---- Load all frames into memory (timestamp + payload per frame) ----
    let mut frames: Vec<Vec<u8>> = Vec::new();
    let mut timestamps_us: Vec<u64> = Vec::new();
    let mut ts_buf = [0u8; 8];
    let mut payload_buf = vec![0u8; frame_size];

    loop {
        match file.read_exact(&mut ts_buf) {
            Ok(()) => {
                let ts_us = u64::from_le_bytes(ts_buf);
                timestamps_us.push(ts_us);
                if let Err(_) = file.read_exact(&mut payload_buf) {
                    // Incomplete payload at EOF; drop the timestamp we just read
                    timestamps_us.pop();
                    break;
                }
                frames.push(payload_buf.clone());
            }
            Err(_) => {
                break;
            }
        }
    }

    println!("📦 Loaded {} frames (with timestamps)", frames.len());

    // ---- Handle start offset with optional wall-clock synchronization ----
    let launch_delta = if has_ref_epoch {
        let now_epoch = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_else(|_| Duration::from_secs(0)).as_secs_f64();
        (now_epoch - ref_epoch).max(0.0)
    } else {
        0.0
    };

    let effective_start_time = (start_time + launch_delta).max(0.0);
    // Find first frame whose timestamp >= effective_start_time
    let start_ts_us = (effective_start_time * 1_000_000.0) as u64;
    let mut start_frame: usize = 0;
    if !timestamps_us.is_empty() {
        // Linear scan is fine for now; data volume is moderate. Could be binary search later.
        while start_frame < timestamps_us.len() && timestamps_us[start_frame] < start_ts_us {
            start_frame += 1;
        }
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
                let read = reader.read_line(&mut line);
                if read.is_err() {
                    break;
                }
                if read.unwrap() == 0 {
                    // EOF
                    break;
                }
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                // Commands: SEEK <seconds> | PAUSE | RESUME
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() == 2 && (parts[0] == "SEEK" || parts[0] == "seek") {
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

    if has_ref_epoch {
        println!("▶️ Starting playback from frame {} (start={:.3}s, delta={:.3}s)", frame_index, start_time, launch_delta);
    } else {
        println!("▶️ Starting playback from frame {}", frame_index);
    }

    // ---- Main playback loop ----
    while frame_index < frames.len() {
        // Handle pending seek requests
        if let Ok(mut tgt) = seek_target_s.lock() {
            if let Some(sec) = *tgt {
                // Compute target frame by timestamp
                let target_us = if sec <= 0.0 { 0u64 } else { (sec * 1_000_000.0) as u64 };
                let mut target_frame: usize = 0;
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

        // Observe pause/resume state transitions
        let paused_now = if let Ok(p) = paused_flag.lock() { *p } else { false };
        if paused_now != last_paused {
            if paused_now {
                // entering paused: accumulate elapsed so far
                elapsed_base += start_instant.elapsed();
            } else {
                // resuming: reset start instant
                start_instant = Instant::now();
            }
            last_paused = paused_now;
        }

        // Use per-frame timestamps for pacing
        let target_time = if frame_index < timestamps_us.len() && start_frame < timestamps_us.len() {
            let rel_us = timestamps_us[frame_index].saturating_sub(timestamps_us[start_frame]);
            Duration::from_micros(rel_us as u64)
        } else {
            // Fallback to fps-based pacing if timestamps missing
            frame_duration.mul_f64((frame_index - start_frame) as f64)
        };
        let elapsed = if paused_now { elapsed_base } else { elapsed_base + start_instant.elapsed() };

        // Sync to maintain real-time playback
        if elapsed < target_time {
            let wait = target_time - elapsed;
            // When paused, avoid long sleeps; tick periodically
            if paused_now {
                let tick = Duration::from_millis(10);
                sleep(if wait > tick { tick } else { wait });
                continue;
            } else {
                sleep(wait);
            }
        }

        if paused_now {
            // While paused, do not send or advance frames
            sleep(Duration::from_millis(10));
            continue;
        }

        let frame = &frames[frame_index];
        if socket.send(frame).is_err() {
            eprintln!("⚠️ UDP send failed at frame {}", frame_index);
        }

        frame_index += 1;
    }

    println!("🏁 Playback complete.");
}
