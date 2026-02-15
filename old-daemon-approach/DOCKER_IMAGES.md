# Docker Images Installation Guide

This guide explains how to build and use pre-built Docker images for the Jellyfin Ambilight extractor and player services.

## Building Images

Build both images locally:

```bash
./build-images.sh
```

This will create:
- `jellyfin-ambilight-extractor:latest`
- `jellyfin-ambilight-player:latest`

### Building with Custom Tags

```bash
DOCKER_TAG=v1.0.0 ./build-images.sh
```

### Building and Pushing to a Registry

```bash
DOCKER_REGISTRY=ghcr.io/your-username \
DOCKER_TAG=v1.0.0 \
PUSH_IMAGES=true \
./build-images.sh
```

This will:
1. Build the images with the specified tag
2. Tag them with the registry prefix
3. Push them to the registry

## Using Pre-built Images

### Option 1: Using docker-compose with override file

1. Set environment variables:
   ```bash
   export DOCKER_REGISTRY=ghcr.io/your-username
   export DOCKER_TAG=latest
   ```

2. Use the override file:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.images.yml up -d
   ```

### Option 2: Direct docker run

#### Extractor:
```bash
docker run -d \
  --name ambilight-extractor \
  --env-file .env \
  -v /path/to/data:/app/data \
  -v /path/to/movies:/media/movies:ro \
  -v /path/to/tv:/media/tv:ro \
  --device /dev/video10:/dev/video10 \
  --device /dev/video11:/dev/video11 \
  --device /dev/video12:/dev/video12 \
  your-registry/jellyfin-ambilight-extractor:latest
```

#### Player:
```bash
docker run -d \
  --name ambilight-player \
  --env-file .env \
  -v /path/to/data:/app/data \
  -v /path/to/movies:/media/movies:ro \
  -v /path/to/tv:/media/tv:ro \
  your-registry/jellyfin-ambilight-player:latest
```

## Image Contents

Both images are self-contained and include:
- Rust binaries (`ambilight-extractor` or `ambilight-player`)
- Python daemon scripts
- Required Python dependencies
- Storage and simplified modules

No code volume mounts are required - everything is baked into the image.

## Development vs Production

- **Development**: Use `docker-compose.yml` directly (builds from source, allows code changes)
- **Production**: Use pre-built images via `docker-compose.images.yml` or direct `docker run` commands



