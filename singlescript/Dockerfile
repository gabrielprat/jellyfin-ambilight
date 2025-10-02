# Minimal Python image
FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg and minimal dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install -U pip
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Create mount points for videos and binary data
RUN mkdir -p /data/movies /data/series /data/binary

# Run the script (will be mounted from host)
CMD ["python", "/app/ambilight.py"]
