FROM python:3.14-slim-bookworm

# curl and unzip are only needed to install Deno. ffmpeg stays for spotdl and yt-dlp.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg curl unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && apt-get purge -y --auto-remove curl unzip \
    && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py cleanup_service.py wsgi.py ./

RUN mkdir -p /var/www/SpotifyDownloader

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

# Keep --workers 1 so download state and cleanup stay in one process.
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:5000", "wsgi:app"]
