#!/bin/bash

echo "=== Jellyfin Ambilight Library Management Examples ==="
echo

echo "1. Build the Docker image:"
echo "docker-compose build"
echo

echo "2. Perform initial full library scan:"
echo "docker-compose run --rm jellyfin-ambilight python jellyfin-library-api.py --full-scan"
echo

echo "3. Perform incremental update (after initial scan):"
echo "docker-compose run --rm jellyfin-ambilight python jellyfin-library-api.py --update"
echo

echo "4. Start playback monitoring service:"
echo "docker-compose up -d"
echo

echo "5. View logs from playback monitoring:"
echo "docker-compose logs -f"
echo

echo "6. Stop the service:"
echo "docker-compose down"
echo

echo "=== Frame Extraction ==="
echo "7. List all video items:"
echo "docker-compose run --rm jellyfin-ambilight python frame-extractor.py --list"
echo

echo "8. Extract frames from all videos (recommended: in-memory):"
echo "docker-compose run --rm jellyfin-ambilight python frame-extractor.py --all --memory-only"
echo

echo "9. Extract frames from specific video (recommended: in-memory):"
echo "docker-compose run --rm jellyfin-ambilight python frame-extractor.py --video <item_id> --memory-only"
echo

echo "10. Test extraction with file path (recommended: in-memory):"
echo "docker-compose run --rm jellyfin-ambilight python frame-extractor.py --test-path /movies/example.mp4 --memory-only"
echo

echo "=== Ambilight Control ==="
echo "11. Show LED configuration:"
echo "docker-compose run --rm jellyfin-ambilight python ambilight-service.py --show-config"
echo

echo "12. Test ambilight with single frame:"
echo "docker-compose run --rm jellyfin-ambilight python ambilight-service.py --test-frame /app/data/frames/<item_id>/frame_000010.000s.jpg"
echo

echo "13. Simulate ambilight playback:"
echo "docker-compose run --rm jellyfin-ambilight python ambilight-service.py --simulate <item_id>"
echo

echo "14. Benchmark performance (precomputed vs real-time):"
echo "docker-compose run --rm jellyfin-ambilight python ambilight-service.py --benchmark <item_id>"
echo

echo "=== Command Line Options ==="
echo "Library Scanner:"
echo "  --full-scan : Complete library scan (use for initial setup)"
echo "  --update    : Incremental update since last scan (default)"
echo "  --help      : Show help message"
echo
echo "Frame Extractor:"
echo "  --list       : List all video items in database"
echo "  --all        : Extract frames from all library videos"
echo "  --video      : Extract frames from specific video by ID"
echo "  --test-path  : Test extraction with specific file path"
echo "  --memory-only: Use in-memory processing (96% less storage, recommended)"
echo
echo "Ambilight Service:"
echo "  --show-config : Show LED configuration and mapping"
echo "  --test-frame  : Test ambilight with single frame"
echo "  --simulate    : Simulate playbook with extracted frames"
echo "  --benchmark   : Benchmark precomputed vs real-time performance"
echo "  --duration    : Simulation duration in seconds"
echo

echo "=== Video File Testing ==="
echo "20. Test WLED connection:"
echo "./test-sonic.sh"
echo
echo "21. Test with specific video file:"
echo "docker-compose run --rm jellyfin-ambilight python test-video-ambilight.py --file /app/test/video.mkv --duration 30"
echo
echo "22. Test with custom parameters:"
echo "docker-compose run --rm jellyfin-ambilight python test-video-ambilight.py --file /app/test/video.mkv --start 60 --duration 30 --interval 0.5"
echo
echo "=== Typical Workflow ==="
echo "1. Run full scan once: docker-compose run --rm jellyfin-ambilight python jellyfin-library-api.py --full-scan"
echo "2. Extract frames for ambilight (in-memory): docker-compose run --rm jellyfin-ambilight python frame-extractor.py --all --memory-only"
echo "3. Test ambilight setup: docker-compose run --rm jellyfin-ambilight python ambilight-service.py --show-config"
echo "4. Set up cron job for regular updates: */30 * * * * docker-compose run --rm jellyfin-ambilight python jellyfin-library-api.py --update"
echo "5. Start monitoring: docker-compose up -d"
