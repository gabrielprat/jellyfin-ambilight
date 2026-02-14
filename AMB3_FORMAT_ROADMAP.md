# AMb3 Format - Future Improvements Roadmap

This document outlines planned improvements for a next-generation AMb3 binary format to replace the current AMb2 format. The goals are to reduce file size, improve sync accuracy, and enhance playback performance.

---

## 🎯 Primary Goals

### 1. Frame Deduplication & Run-Length Encoding (RLE)
**Problem**: Static scenes (credits, paused action) store identical frames repeatedly, wasting space and network bandwidth.

**Solution**:
- Detect consecutive identical frames (or within a similarity threshold, e.g., 95%)
- Store frame once with duration/frame count instead of repeating data
- Example: 5 seconds of black credits = 1 frame entry instead of 120 frames (24fps)

**Expected Savings**: 
- 50-80% for content with static scenes
- 10-20% for typical movies with moderate motion

---

### 2. Delta/Differential Encoding
**Problem**: Adjacent frames are often very similar (gradual color transitions), leading to redundant data storage.

**Solution**:
- Store keyframes (full LED data) every N frames (e.g., every 2 seconds or 48 frames at 24fps)
- Store deltas (differences) between keyframes
- Delta format: only encode LEDs that changed by more than a threshold (e.g., 10 RGB units)
- Each delta references the last keyframe

**Expected Savings**: 
- 40-60% typical
- Excellent for slow-paced, dialogue-heavy content

---

### 3. Compression Layer
**Problem**: Raw RGB data is highly compressible but currently stored uncompressed.

**Solution**:
- Add LZ4 or Zstandard compression to frame data blocks
- Compress in chunks (e.g., 5-second segments) to maintain seekability
- Header flag indicates compression algorithm used
- Player decompresses chunks on-the-fly

**Expected Savings**: 
- 30-50% additional reduction on top of other optimizations

---

### 4. Improved Timing & Sync
**Problem**: Calculated timestamps based on frame index can drift over time, especially with Variable Frame Rate (VFR) videos.

**Solution**:
- Store actual PTS (Presentation TimeStamps) from video decoder instead of calculated values
- Include video duration + total frame count in header for validation
- Add file integrity checksum/hash
- Flag whether video is CFR (Constant Frame Rate) or VFR in header
- Support explicit frame durations for VFR content

**Benefits**: 
- Perfect sync even with VFR content
- No drift in multi-hour videos
- Validation of file integrity

---

## 🔧 Secondary Goals

### 5. Adaptive Color Precision
**Rationale**: Dark scenes don't require full 8-bit precision per channel; human eyes can't distinguish subtle differences in low light.

**Solution**:
- Detect overall scene brightness during extraction
- Use 6-bit (64 levels) or 7-bit for dark scenes, full 8-bit for bright scenes
- Store bit depth per frame block/chunk
- Dynamically adjust based on content

**Expected Savings**: 
- 20-25% for dark content (noir films, space scenes, horror movies)

---

### 6. Perceptual Color Encoding
**Rationale**: Human vision can't distinguish small color differences, especially in peripheral vision (where ambilight appears).

**Solution**:
- Quantize colors based on perceptual difference (CIE ΔE < 2.0)
- Provide configurable quality levels:
  - High: imperceptible loss (ΔE < 1.0)
  - Medium: barely noticeable (ΔE < 2.0)
  - Low: noticeable but acceptable (ΔE < 5.0)
- Use color palettes or reduced bit depth per quality level

**Expected Savings**: 
- 15-30% depending on quality setting
- Minimal perceived quality loss

---

### 7. Seeking Index
**Problem**: Large binary files require linear scanning to find specific timestamps, causing slow seek operations.

**Solution**:
- Add index structure at end of file
- Index format: `[timestamp → file byte offset]` map
- Create index entry every 5-10 seconds
- Player reads index first, then jumps directly to required offset
- Optional: store index at beginning for streaming scenarios

**Benefits**: 
- Instant seeking in multi-hour movies
- No need to read entire file into memory
- Better user experience with large libraries

---

### 8. Scene Change Markers
**Problem**: Scene cuts require instant LED updates for responsive ambilight, but current format treats all frames equally.

**Solution**:
- Detect scene changes during extraction (threshold: >40% color delta between frames)
- Flag these frames as "priority" or "instant update" in the binary format
- Player recognizes flags and force-sends these frames immediately to WLED
- Bypass smoothing/interpolation for scene cut frames

**Benefits**: 
- More responsive ambilight on hard cuts
- Better user experience during action sequences
- Maintains smooth transitions for gradual changes

---

### 9. Multi-Resolution / Multi-Quality Storage
**Rationale**: Users have different LED strip configurations (50, 100, 150, 200+ LEDs). Currently requires re-extraction for each setup.

**Solution**:
- Store multiple LED count versions in same file
  - Example: 150 LEDs (full detail), 100 LEDs, 50 LEDs (lower detail)
- Player selects appropriate version based on actual LED strip configuration
- Shared keyframes reduce redundancy
- Optional: store only highest resolution, player downsamples on-the-fly

**Benefits**: 
- One extraction works for multiple LED setups
- Easy to switch LED configurations without re-extraction
- Library sharing between users with different hardware

---

### 10. Color Space Metadata
**Problem**: HDR/SDR, Rec.709/Rec.2020 videos have different color characteristics; current format ignores this.

**Solution**:
- Store source video color space metadata in header:
  - Dynamic range: SDR, HDR10, HDR10+, Dolby Vision, HLG
  - Color primaries: Rec.709 (HD), Rec.2020 (UHD), DCI-P3 (cinema)
  - Transfer function: sRGB, PQ (ST.2084), HLG
  - Gamma curve information
- Player applies appropriate tone mapping for target display
- Preserve wider color gamut for RGBW LEDs

**Benefits**: 
- Accurate colors for HDR content
- Better handling of wide color gamut sources
- Future-proof for new HDR standards

---

### 11. Smooth Transition Hints
**Problem**: Temporal smoothing currently happens during playback with fixed parameters; not optimal for all content.

**Solution**:
- Pre-calculate optimal interpolation paths during extraction (more time available)
- Store transition type hints per frame:
  - `instant`: Scene cut, no interpolation
  - `fast`: Quick transition (0.1-0.3s)
  - `normal`: Standard fade (0.3-1.0s)
  - `slow`: Gradual fade (1.0s+)
- Include recommended smoothing window per segment
- Player uses hints for better temporal smoothing decisions

**Benefits**: 
- Superior temporal smoothing with less player CPU
- Content-aware interpolation
- Sharper cuts, smoother fades

---

### 12. Brightness/Adaptive Optimization
**Rationale**: Very dark scenes use less WLED network bandwidth and can be optimized differently.

**Solution**:
- Store overall scene brightness level (0-255) per chunk
- Store brightness histogram for each chunk
- Player can:
  - Apply adaptive brightness without re-reading full data
  - Skip network updates for very dark frames (brightness < threshold)
  - Optimize UDP packet size based on brightness
- Allow brightness boost settings without file modification

**Benefits**: 
- Better WLED performance in dark content
- Reduced network traffic during dark scenes
- More responsive brightness adaptation

---

### 13. Streaming-Friendly Chunks
**Problem**: Current format requires loading entire file into memory; impractical for embedded players or very long videos.

**Solution**:
- Break file into independent, self-contained chunks (5-10 second duration each)
- Each chunk structure:
  - Mini-header: timestamp, type, size, frame count
  - Compressed or uncompressed data
  - Optional checksum
- Player can stream/buffer chunks on-demand
- Implement chunk prefetching for smooth playback

**Benefits**: 
- Lower memory usage (only current + next chunk in RAM)
- Better for embedded/low-memory players
- Enables true streaming playback
- Parallel chunk decompression possible

---

### 14. Error Correction / Resilience
**Problem**: File corruption from disk errors, incomplete writes, or network transfers breaks entire playback.

**Solution**:
- Add CRC32 or xxHash checksums per chunk
- Detect corrupted chunks during playback
- Allow graceful degradation:
  - Skip corrupted chunks (brief LED glitch vs. complete failure)
  - Interpolate between good chunks if possible
- Optional: Reed-Solomon error correction for critical sections (header, index)
- Store redundant header at end of file

**Benefits**: 
- Robust playback despite storage errors
- Recoverable from partial file downloads
- Better reliability on network storage (NAS, cloud)

---

### 15. Variable Frame Rate (VFR) Explicit Support
**Problem**: VFR videos are common in screen recordings, anime, some streaming content. Current constant frame rate assumption causes sync drift.

**Solution**:
- Detect VFR during extraction (check frame PTS deltas)
- Store actual frame durations instead of assuming constant spacing
- Flag VFR mode in header
- Include frame rate changes throughout video
- Support discontinuous timestamps (dropped frames in source)

**Benefits**: 
- Perfect sync for VFR content
- No drift in anime or screen captures
- Handles frame drops in source video

---

## 📦 Proposed AMb3 Format Structure

### File Layout
```
┌─────────────────────────────────────┐
│  AMb3 Header (extended)             │
├─────────────────────────────────────┤
│  Chunk 1 (0:00 - 0:10)              │
│    ├─ Chunk Header                  │
│    └─ Compressed Frame Data         │
├─────────────────────────────────────┤
│  Chunk 2 (0:10 - 0:20)              │
│    ├─ Chunk Header                  │
│    └─ Compressed Frame Data         │
├─────────────────────────────────────┤
│  ... (more chunks)                  │
├─────────────────────────────────────┤
│  Seeking Index                      │
│    ├─ Index Header                  │
│    └─ Timestamp → Offset Entries    │
├─────────────────────────────────────┤
│  Footer (checksum, redundant header)│
└─────────────────────────────────────┘
```

### Header Structure (64-96 bytes)
```c
struct AMb3Header {
    char magic[4];              // "AMb3"
    uint8_t version;            // Format version (e.g., 1)
    uint32_t flags;             // Bit flags (compression, VFR, multi-res, HDR, etc.)
    uint64_t video_duration_us; // Total duration in microseconds
    uint64_t total_frames;      // Total frame count
    float base_fps;             // Base FPS (CFR) or 0.0 (VFR)
    uint16_t led_counts[4];     // top, bottom, left, right
    uint8_t color_format;       // 0=RGB, 1=RGBW, 2=RGBWW, etc.
    uint8_t color_space;        // 0=SDR/Rec.709, 1=HDR10/Rec.2020, etc.
    uint8_t compression;        // 0=none, 1=LZ4, 2=Zstd, etc.
    uint8_t quality_level;      // 0=high, 1=medium, 2=low (perceptual encoding)
    uint64_t index_offset;      // Byte offset to seeking index
    uint32_t chunk_count;       // Number of chunks in file
    uint8_t reserved[32];       // Future expansion
};
```

### Chunk Structure (variable size)
```c
struct AMb3Chunk {
    uint64_t timestamp_us;      // Start timestamp (microseconds)
    uint8_t chunk_type;         // 0=keyframe, 1=delta, 2=duplicate, 3=compressed
    uint32_t compressed_size;   // Size of data (compressed if applicable)
    uint32_t uncompressed_size; // Original size (for validation)
    uint16_t frame_count;       // Number of frames in this chunk
    uint8_t brightness_avg;     // Average brightness (0-255)
    uint8_t flags;              // Chunk-specific flags
    uint32_t checksum;          // CRC32 or xxHash
    // Followed by actual frame data (compressed or not)
};
```

### Index Structure (at end of file)
```c
struct AMb3Index {
    uint32_t magic;             // "IDX3" or similar
    uint32_t entry_count;       // Number of index entries
    // Followed by entries:
    struct {
        uint64_t timestamp_us;  // Timestamp
        uint64_t file_offset;   // Byte offset in file
        uint32_t chunk_index;   // Chunk number
    } entries[];
};
```

### Flag Bits (header.flags)
```
Bit 0:    Compression enabled
Bit 1:    VFR mode
Bit 2:    Multi-resolution data present
Bit 3:    HDR color space
Bit 4:    Scene change markers present
Bit 5:    Perceptual encoding used
Bit 6:    Delta encoding used
Bit 7:    RLE (run-length encoding) used
Bits 8-31: Reserved for future use
```

---

## 📊 Expected Performance Improvements

### File Size Reduction
| Content Type              | Current AMb2 | AMb3 (optimized) | Reduction |
|---------------------------|--------------|------------------|-----------|
| Typical movie (2h)        | 850 MB       | 200-350 MB       | 60-75%    |
| Action movie (high motion)| 950 MB       | 400-550 MB       | 40-60%    |
| Dialogue/slow (low motion)| 850 MB       | 150-250 MB       | 70-85%    |
| Anime (limited animation) | 850 MB       | 100-200 MB       | 75-90%    |
| Credits/static scenes     | 300 MB       | 15-50 MB         | 85-95%    |

### Network Traffic to WLED
- **50-70% reduction** from frame deduplication (no updates for identical frames)
- Additional savings from brightness-adaptive updates
- Scene change markers reduce latency for cuts

### Sync Quality
- **Near-perfect sync** with PTS-based timing (no drift)
- VFR support eliminates sync issues in variable frame rate content
- File integrity checks prevent corrupted data playback

### Playback Performance
- **5-20x faster seeking** with index (instant jump vs. linear scan)
- **50-70% lower memory usage** with chunk streaming
- Better WLED responsiveness with scene change markers
- Parallel chunk decompression possible

---

## 🔄 Implementation Phases

### Phase 1: Core Improvements (Highest Impact)
1. ✅ Implement AMb3 header structure
2. ✅ Add PTS-based timing (replace calculated timestamps)
3. ✅ Implement LZ4 compression per chunk
4. ✅ Add seeking index
5. ✅ Backward compatibility (detect and read AMb2 files)

### Phase 2: Advanced Optimizations
1. ⏳ Implement frame deduplication / RLE
2. ⏳ Add delta encoding with keyframes
3. ⏳ Scene change detection and markers
4. ⏳ VFR support
5. ⏳ Error correction (CRC per chunk)

### Phase 3: Quality & Features
1. ⏳ Perceptual color encoding
2. ⏳ Adaptive color precision (bit depth variation)
3. ⏳ Multi-resolution storage
4. ⏳ Color space metadata (HDR support)
5. ⏳ Smooth transition hints

### Phase 4: Polish & Optimization
1. ⏳ Brightness/adaptive optimization
2. ⏳ Streaming-friendly chunk prefetching
3. ⏳ Performance tuning (compression ratios, chunk sizes)
4. ⏳ Migration tools (AMb2 → AMb3 converter)
5. ⏳ Documentation and examples

---

## 🔙 Backward Compatibility Strategy

### Reading Old Files
- AMb3 reader detects magic bytes ("AMb2" vs "AMb3")
- Automatically falls back to AMb2 parser for old files
- No re-extraction required for existing library

### Migration Path
- Optional: Provide `ambilight-converter` tool (AMb2 → AMb3)
  - Can be run as background task
  - Preserves original files during conversion
  - Validates converted files
- Gradual migration: extract new content as AMb3, keep old as AMb2
- Player supports both formats seamlessly

### Version Detection
```rust
fn detect_format(file: &Path) -> Result<FormatVersion> {
    let mut f = File::open(file)?;
    let mut magic = [0u8; 4];
    f.read_exact(&mut magic)?;
    
    match &magic {
        b"AMb2" => Ok(FormatVersion::V2),
        b"AMb3" => Ok(FormatVersion::V3),
        _ => Err("Unknown format"),
    }
}
```

---

## 📝 Notes & Considerations

### Trade-offs
- **Extraction time**: AMb3 will take slightly longer to extract (5-15% more time) due to compression and analysis
- **Player complexity**: More complex format requires more sophisticated player code
- **Memory vs. I/O**: Streaming chunks trades memory for more I/O operations

### Open Questions
1. **Chunk size**: 5 seconds? 10 seconds? Make configurable?
2. **Compression algorithm**: LZ4 (fast) vs Zstd (better ratio)?
3. **Keyframe interval**: Every 2 seconds? Adaptive based on motion?
4. **Quality presets**: How many? (low/medium/high or more granular?)

### Future Considerations
- **AI-enhanced extraction**: Use ML to predict optimal smoothing, detect scene types
- **Adaptive LED mapping**: Store multiple zones for different TV sizes
- **Cloud optimization**: Format optimized for cloud storage (S3, etc.)
- **Real-time mode fallback**: Hybrid approach for un-extracted content

---

## 🤝 Contributing

This roadmap is a living document. Suggestions, benchmarks, and implementation PRs are welcome!

### Benchmarking
When implementing features, please benchmark:
- File size (before/after)
- Extraction time (before/after)
- Playback memory usage
- Seeking performance
- Network bandwidth to WLED

### Testing Content
Test with variety of content:
- High motion (action movies, sports)
- Low motion (dialogue, documentaries)
- Animated (anime, CG movies)
- HDR vs SDR
- Different frame rates (23.976, 24, 25, 29.97, 30, 60 fps)
- VFR content (screen recordings, live streams)

---

**Last Updated**: 2026-02-14  
**Status**: Planning / Design Phase  
**Target Version**: AMb3 v1.0
