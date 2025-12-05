#!/bin/bash
# Sync only production files needed for player and extractor to homelab

rsync -avzrp \
  --include="Dockerfile.player" \
  --include="Dockerfile.extractor" \
  --include="docker-compose.yml" \
  --include="ambilight-daemon-player.py" \
  --include="ambilight-daemon-extractor.py" \
  --include="requirements-player.txt" \
  --include="requirements.txt" \
  --include="simplified/" \
  --include="simplified/__init__.py" \
  --include="simplified/ambilight_play.py" \
  --include="storage/" \
  --include="storage/__init__.py" \
  --include="storage/storage.py" \
  --include="ambilight-player/" \
  --include="ambilight-player/Cargo.toml" \
  --include="ambilight-player/src/" \
  --include="ambilight-player/src/main.rs" \
  --include="ambilight-extractor/" \
  --include="ambilight-extractor/Cargo.toml" \
  --include="ambilight-extractor/src/" \
  --include="ambilight-extractor/src/main.rs" \
  --include="env.example" \
  --include="env.homelab" \
  --exclude="*" \
  --exclude=".env" \
  --exclude=".git" \
  --exclude="data" \
  --exclude="__pycache__" \
  --exclude="target" \
  --exclude="*.pyc" \
  --exclude="*.pyo" \
  --exclude="Cargo.lock" \
  --exclude=".DS_Store" \
  --exclude="*.log" \
  --exclude="README.md" \
  --exclude="list_items_with_binaries.py" \
  --exclude="sync_with_homelab.sh" \
  . gabi@galagaon:/home/gabi/docker/jellyfin-ambilight
