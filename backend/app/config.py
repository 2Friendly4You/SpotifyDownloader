import os
import platform
import secrets

SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("WARNING: Using randomly generated secret key. Set FLASK_SECRET_KEY environment variable for persistence.")

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    print("WARNING: ADMIN_PASSWORD environment variable not set. Admin panel will be inaccessible.")
    ADMIN_PASSWORD = secrets.token_hex(32)

MUSIC_DIR = os.environ.get(
    'MUSIC_DIR',
    "C:/SpotifyDownloader/music/" if platform.system() == 'Windows' else "/var/www/SpotifyDownloader/"
)
SEARCHES_FILE = os.environ.get('SEARCHES_FILE', 'searches.json')

# Pending downloads used to expire via a one-hour Redis TTL. Keep that limit so a
# hung worker cannot hold a concurrency slot until the process restarts.
PENDING_TTL_SECONDS = int(os.environ.get('PENDING_TTL_SECONDS', 3600))

VALID_AUDIO_PROVIDERS = {'youtube-music', 'youtube', 'soundcloud', 'bandcamp', 'piped', 'yt-dlp'}
VALID_LYRICS_PROVIDERS = {'musixmatch', 'genius', 'azlyrics', 'synced'}
VALID_OUTPUT_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'}


def retention_seconds():
    return int(os.getenv('CLEANUP_RETENTION_DAYS', '14')) * 86400


def load_queue_limit():
    try:
        parsed = int(os.environ.get('MAX_QUEUED_REQUESTS', 20))
    except (TypeError, ValueError):
        return 20
    return max(0, parsed)
