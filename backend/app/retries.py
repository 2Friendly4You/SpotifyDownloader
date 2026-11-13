"""Retry spotDL tracks that failed and describe the ones that still fail.

spotDL already does a little on its own: yt-dlp retries a broken HTTP
download up to 5 times, and spotDL tries each configured audio provider in
turn when a *search* finds nothing. It does not retry a track whose
download failed, and the app only passes one provider. So each failed
track gets one more attempt with the same provider and then one attempt
per fallback provider.
"""
import os

from spotdl.download.downloader import AUDIO_PROVIDERS

# youtube-music first because it matches songs best. soundcloud is a
# different source entirely and skips 30-second previews. youtube comes last
# because its search is slow on the server. bandcamp is left out because
# its search fails in spotDL 4.6.0 (KeyError 'view_count').
DEFAULT_FALLBACK_PROVIDERS = ('youtube-music', 'soundcloud', 'youtube')
DEFAULT_RETRY_DELAY_SECONDS = 3.0
# A fallback attempt can take about a minute per song (youtube search is
# slow on the server), so a playlist where most songs fail would run into
# the one-hour job timeout. Only this many songs get the fallback attempts.
DEFAULT_FALLBACK_SONG_LIMIT = 30
MAX_FAILED_TRACKS = 500
FAILED_TRACKS_FILE = 'failed-songs.txt'

REASON_TEXT = {
    'not_found': 'Not found',
    'download_failed': 'Download failed',
    'conversion_failed': 'Conversion failed',
    'metadata_failed': 'Metadata unavailable',
}


def fallback_providers(primary, env=None):
    """Fallback providers from AUDIO_PROVIDER_FALLBACKS (comma-separated).

    An empty value turns the fallbacks off. Unknown names and the primary
    provider are skipped.
    """
    env = os.environ if env is None else env
    raw = env.get('AUDIO_PROVIDER_FALLBACKS')
    names = DEFAULT_FALLBACK_PROVIDERS if raw is None else [name.strip() for name in raw.split(',')]
    chain = []
    for name in names:
        if name in AUDIO_PROVIDERS and name != primary and name not in chain:
            chain.append(name)
    return chain


def retry_plan(primary, env=None):
    """The providers to try, in order, for tracks that failed the first time."""
    plan = [primary] if primary in AUDIO_PROVIDERS else []
    return plan + fallback_providers(primary, env)


def retry_delay(env=None):
    env = os.environ if env is None else env
    try:
        return max(0.0, float(env.get('RETRY_DELAY_SECONDS', DEFAULT_RETRY_DELAY_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_DELAY_SECONDS


def fallback_song_limit(env=None):
    env = os.environ if env is None else env
    try:
        return max(0, int(env.get('FALLBACK_SONG_LIMIT', DEFAULT_FALLBACK_SONG_LIMIT)))
    except (TypeError, ValueError):
        return DEFAULT_FALLBACK_SONG_LIMIT


def classify_error(text):
    """Map one of spotDL's error strings to a short reason code for the UI."""
    text = text or ''
    if 'LookupError' in text or 'No results found' in text:
        return 'not_found'
    if 'FFmpegError' in text:
        return 'conversion_failed'
    if 'MetadataError' in text or 'reinitializ' in text or 'missing required fields' in text:
        return 'metadata_failed'
    return 'download_failed'


def reasons_by_url(errors, songs):
    """Reason codes for the songs that the given spotDL errors belong to.

    spotDL formats download errors as "<song url> - <Exception>: <message>".
    """
    reasons = {}
    for song in songs:
        if not song.url:
            continue
        prefix = f"{song.url} - "
        for error in errors:
            if error.startswith(prefix):
                reasons[song.url] = classify_error(error)
    return reasons


def track_label(song):
    artists = getattr(song, 'artists', None) or ([song.artist] if getattr(song, 'artist', None) else [])
    name = getattr(song, 'name', None)
    if name and artists:
        return f"{', '.join(artists)} - {name}"
    return getattr(song, 'display_name', None) or name or getattr(song, 'url', None) or 'Unknown song'


def failure_entry(song, reason):
    return {'title': track_label(song), 'reason': reason, 'url': getattr(song, 'url', None)}


def use_provider(downloader, name):
    """Point an existing Downloader at a different audio provider.

    This reuses the downloader's event loop, thread limit and settings, and
    only swaps the provider that spotDL's search and download step use.
    """
    settings = downloader.settings
    settings['audio_providers'] = [name]
    downloader.audio_providers = [
        AUDIO_PROVIDERS[name](
            output_format=settings['format'],
            cookie_file=settings['cookie_file'],
            search_query=settings['search_query'],
            filter_results=settings['filter_results'],
            yt_dlp_args=settings['yt_dlp_args'],
        )
    ]


def failed_tracks_text(failed_tracks):
    lines = [f"These {len(failed_tracks)} songs could not be downloaded:", '']
    for track in failed_tracks:
        reason = REASON_TEXT.get(track['reason'], track['reason'])
        line = f"{track['title']} ({reason})"
        if track.get('url'):
            line += f" {track['url']}"
        lines.append(line)
    return '\n'.join(lines) + '\n'
