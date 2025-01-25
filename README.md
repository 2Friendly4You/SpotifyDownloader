# Spotify Downloader

A web-based application for downloading songs and playlists from Spotify and YouTube. Features a modern, responsive interface with multiple download options and format selections.

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
  - slider.kz
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
- Rate limiting to prevent abuse
- Mobile-responsive design

## Installation

### Prerequisites

- Docker
- Docker Compose
- Git (optional)

### Quick Start

1. Clone the repository (or download and extract the ZIP):
```bash
git clone https://github.com/2Friendly4You/SpotifyDownloader.git
cd SpotifyDownloader
```

2. Start the application:
```bash
docker-compose up -d
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
      - FLASK_ENV=production              # Change to development if needed
```

#### File Cleanup Configuration
```yaml
  spotifydownloader-cleanup:
    environment:
      - RETENTION_DAYS=14        # Number of days to keep files
      - CLEANUP_INTERVAL=86400   # Cleanup check interval in seconds
```

### Volume Mounts
The application uses several volume mounts:
- `./music:/var/www/SpotifyDownloader` - Downloaded music files
- `./images:/var/www/images` - Image assets
- `./static:/var/www/static` - Static files
- `./searches.json:/app/searches.json` - Download statistics

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
5. Monitor the download progress in the "Requests" section
6. Click "Download" when the file is ready

## Docker Commands

### Start the Application
```bash
docker-compose up -d        # Start in detached mode
docker-compose up --build   # Rebuild and start
```

### Stop the Application
```bash
docker-compose down         # Stop containers
docker-compose down -v      # Stop and remove volumes
```

### View Logs
```bash
docker-compose logs -f                         # All services
docker-compose logs -f spotifydownloader-app   # Just the app service
```

### Container Management
```bash
docker-compose ps          # List containers
docker-compose restart     # Restart all services
docker-compose pull        # Update container images
```

## Architecture

The application consists of several Docker containers:

- **spotifydownloader-app**: Main Flask application
- **spotifydownloader-nginx**: Nginx reverse proxy
- **spotifydownloader-data**: Shared volume container
- **spotifydownloader-redis**: Redis for request tracking
- **spotifydownloader-cleanup**: Automatic file cleanup service

## Security Considerations

- Files are automatically deleted after the retention period (default: 14 days)
- Rate limiting is enabled (1 request per 5 seconds, 10 requests per minute)
- Validate all input URLs and search queries
- Environment variables for sensitive configuration
- Redis for secure session management

## Troubleshooting

1. **Downloads stuck at pending**
   - Check the application logs
   - Verify the audio provider is accessible
   - For Spotify downloads: Try a different audio provider
   - For YouTube downloads: Check if the video is available in your region

2. **File not found after download**
   - Check the retention period hasn't expired
   - Verify the cleanup service is running correctly
   - Check disk space availability
   - For YouTube: Video might have been removed or made private

3. **Rate limiting errors**
   - Wait for the rate limit to reset
   - Default limits: 1 request/5s, 10 requests/minute
   - Limits apply to both Spotify and YouTube downloads

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request