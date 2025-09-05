FROM ghcr.io/astral-sh/uv:python3.11-bookworm AS base

# Install system dependencies needed by yt-dlp/ffmpeg/spotdl and build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache dependencies layer by using only lock/config first
COPY pyproject.toml ./
# If a lock exists, copy it to enable reproducible installs
COPY uv.lock ./

# Sync dependencies into a virtualenv at .venv (uv default)
RUN uv sync --frozen --no-install-project || uv sync --no-install-project

# Copy application code
COPY . .

# Ensure the downloads directory exists
RUN mkdir -p /var/www/SpotifyDownloader/

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py \
    UV_PROJECT_ENV=.venv

EXPOSE 5000

# Use uv run to launch gunicorn with eventlet worker
CMD ["uv", "run", "gunicorn", "--worker-class", "eventlet", "--workers", "1", "--bind", "0.0.0.0:5000", "wsgi:app"]
