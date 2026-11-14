# Spotify Downloader

A web-based application for downloading songs and playlists from Spotify and YouTube. Features a React frontend, a Flask API, and multiple download options and format selections.

## Features

- Download individual songs from Spotify URLs
- Download entire playlists from Spotify URLs
- Search and download songs by name
- Download from multiple sources:
  - Spotify songs and playlists
  - YouTube videos and playlists
  - Search by song name
- Multiple audio source providers:
  - YouTube Music (recommended)
  - YouTube
  - SoundCloud
  - Bandcamp
  - Piped
- Multiple lyrics providers:
  - Musixmatch
  - Genius
  - AZLyrics
  - Synced lyrics
- Multiple output formats:
  - MP3
  - M4A
  - WAV
  - FLAC
  - OGG
  - OPUS
- Automatic file cleanup after 14 days (configurable)
- Real-time download status updates
- Download history with persistent storage
- Dark/Light theme support
- English and German translations
- A cap on how many downloads can run at once
- Mobile-responsive design

## Project layout

```
backend/     Flask API, Socket.IO, download workers, in-process cleanup
frontend/    React + Vite UI
music/       downloaded zip files (runtime, not committed)
nginx.conf   reverse proxy in front of the API and the built UI
```

## Installation

### Prerequisites

- Docker
- Docker Compose
- Python 3.14 and pip for local backend development
- ffmpeg and [Deno](https://deno.land/) (yt-dlp needs a JavaScript runtime for many YouTube downloads)
- pnpm for local frontend development
- Git (optional)

### Quick Start

1. Clone the repository (or download and extract the ZIP):
```bash
git clone https://github.com/2Friendly4You/SpotifyDownloader.git
cd SpotifyDownloader
```

2. Copy `.env.example` to `.env` and set `FLASK_SECRET_KEY` and `ADMIN_PASSWORD`.

3. Start the application:
```bash
docker compose up --build -d
```

The application will be available at `http://localhost:8900`

## Configuration

### Docker Compose Configuration

The `docker-compose.yml` file contains several services that can be configured:

#### Port Configuration
To change the exposed port (default: 8900), modify the ports section in `docker-compose.yml`:
```yaml
  spotifydownloader-nginx:
    ports:
      - "YOUR_PORT:80"  # Change YOUR_PORT to desired port
```

#### Environment Variables
```yaml
  spotifydownloader-app:
    environment:
      - FLASK_SECRET_KEY=your_secret_key  # Add a secure secret key
      - ADMIN_PASSWORD=your_admin_password
```

#### File Cleanup Configuration
```yaml
  spotifydownloader-app:
    environment:
      - CLEANUP_RETENTION_DAYS=14        # Number of days to keep files
      - AGE_CLEANUP_INTERVAL=86400
```

### Volume Mounts
- `./music` is mounted read-write into the app container and read-only into nginx, which serves the zip files
- `./data` is mounted into the app container. The download counter is `data/searches.json`, which the app creates on startup
- `./nginx.conf` is mounted into nginx, so proxy changes apply after a restart

## Usage

1. Open your browser and navigate to `http://localhost:8900` (or your configured port)
2. Enter either:
   - A Spotify song URL
   - A Spotify playlist URL
   - A YouTube video URL
   - A YouTube playlist URL
   - A song name to search
3. Select your preferred:
   - Audio provider (only for Spotify/search, YouTube URLs use direct download)
   - Lyrics provider (only for Spotify/search)
   - Output format
4. Click "Search" to start the download
5. Monitor the download progress in the "Requests" section. While spotDL looks up a playlist or album, the card shows how many songs it has resolved, and a rough time remaining appears once it can be estimated
6. Click "Download" when the file is ready

Admin panel: `http://localhost:8900/admin`, with the `ADMIN_PASSWORD` login. It shows:

- running and queued jobs, with their names and progress; you can cancel them
- recent downloads, with name, size, duration, status and failed songs; you can download or delete a file
- statistics for 24 hours, 7 days and 30 days, and a 14-day chart
- the disk usage of the music folder and the partition; you can clean up old ZIPs and leftover folders
- the parallel-download limit, which you can change
- server health

The job history is kept in `data/jobs.json` (newest 500 jobs; `JOB_HISTORY_FILE` changes the path).

## Local development

You can run the API and UI separately.

Backend (from `backend/`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:MUSIC_DIR="..\music"
$env:ADMIN_PASSWORD="your_admin_password"
# Keep --workers 1 so download state and cleanup stay in one process.
# Docker / Linux:
gunicorn --worker-class gthread --workers 1 --threads 8 --bind 127.0.0.1:5000 wsgi:app
# Windows:
python run.py
```

Frontend (from `frontend/`):

```powershell
pnpm install
pnpm dev
```

Vite proxies `/api`, `/socket.io`, and `/music` to `http://127.0.0.1:5000`.

## Docker Commands

### Start the Application
```bash
docker compose up -d        # Start in detached mode
docker compose up --build   # Rebuild and start
```

### Stop the Application
```bash
docker compose down         # Stop containers
docker compose down -v      # Stop and remove volumes
```

### View Logs
```bash
docker compose logs -f                         # All services
docker compose logs -f spotifydownloader-app   # Just the app service
```

### Container Management
```bash
docker compose ps          # List containers
docker compose restart     # Restart all services
docker compose pull        # Update container images
```

## Architecture

The application consists of two Docker containers:

- **spotifydownloader-app**: Flask JSON API, Socket.IO server, download state, and file cleanup
- **spotifydownloader-nginx**: Serves the React build, proxies `/api` and `/socket.io`, and serves files from `music/`

## Songs that fail to download

spotDL alone gives up quickly on a song. yt-dlp retries a broken HTTP transfer, but a song whose download fails is not tried again, and the app passes only the selected audio provider. So the app does this for every failed song:

1. It waits `RETRY_DELAY_SECONDS` (default 3) and tries again with the same provider.
2. It tries each provider in `AUDIO_PROVIDER_FALLBACKS` (default `youtube-music,soundcloud,youtube`, skipping the selected one). An empty value turns the fallbacks off. Only the first `FALLBACK_SONG_LIMIT` (default 30) failed songs get these attempts, so a mostly broken playlist does not hit the one-hour job timeout.
3. Songs that still fail are listed on the download card under "N songs failed" with a short reason, and in `failed-songs.txt` inside the zip.

Bandcamp is not a default fallback because its search fails in spotDL 4.6.0. SoundCloud cannot download DRM-protected tracks, which covers many major-label songs.

## Security Considerations

- Files are automatically deleted after the retention period (default: 14 days)
- Concurrent downloads are capped (default: 5, adjustable in the admin panel)
- Extra requests wait in a FIFO queue (default cap: 20, `MAX_QUEUED_REQUESTS`)
- Validate all input URLs and search queries
- Environment variables for sensitive configuration
- In-progress downloads are tracked in the app process; the admin concurrency override is stored in `data/searches.json`

## Troubleshooting

1. **Downloads stuck at pending**
   - Check the application logs
   - Verify the audio provider is accessible
   - For Spotify downloads: Try a different audio provider
   - For YouTube downloads: Check if the video is available in your region

2. **File not found after download**
   - Check the retention period hasn't expired
   - Verify the app process is running so the cleanup thread can delete old files
   - Check disk space availability
   - For YouTube: Video might have been removed or made private

3. **Downloads stay queued**
   - Extra songs wait until a running download finishes
   - The default is 5 downloads at once (admin panel) and 20 waiting requests (`MAX_QUEUED_REQUESTS`)

4. **Download queue is full**
   - Wait until a queued download starts, then try again
   - Raise the concurrent limit in the admin panel so waiting jobs start sooner
   - Raise `MAX_QUEUED_REQUESTS` if you want more songs to wait

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request
