"""Human-readable names for download jobs.

Storage stays keyed by the job's UUID (``music/<uuid>/`` and ``<uuid>.zip``),
so two playlists with the same name never collide and odd characters never
reach a server path. The title is only used for display and for the file
name the browser saves the zip under.
"""
import re
import unicodedata
import zipfile
from urllib.parse import quote, urlparse

MAX_TITLE_LENGTH = 200
# Bytes, not characters: many filesystems limit a name to 255 bytes, and
# the browser appends " (1)" or similar when the name already exists.
MAX_FILENAME_BYTES = 150
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_SPACES = re.compile(r'\s+')
_WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def is_job_id(value):
    return bool(_UUID.match(value or ''))


def spotify_kind(search_query):
    """'playlist', 'album', 'artist', 'track' for open.spotify.com links, else None."""
    try:
        url = urlparse(search_query.strip())
    except ValueError:
        return None
    if url.scheme not in ('http', 'https') or url.netloc.lower() not in ('open.spotify.com', 'www.open.spotify.com'):
        return None
    parts = [part for part in url.path.split('/') if part]
    if parts and parts[0].lower().startswith('intl-'):
        parts = parts[1:]
    kind = parts[0].lower() if parts else ''
    return kind if kind in ('playlist', 'album', 'artist', 'track') else None


def clean_title(title):
    """One line of plain text, or None."""
    if not title:
        return None
    title = _SPACES.sub(' ', unicodedata.normalize('NFC', str(title))).strip()
    return title[:MAX_TITLE_LENGTH] or None


def title_from_songs(search_query, songs):
    """The name a user would recognise: the playlist or album, or 'Artist - Song'."""
    kind = spotify_kind(search_query)
    if kind is None and not re.match(r'^https?://', search_query.strip(), re.IGNORECASE):
        # Free-text search: the user's own words are the clearest name.
        return clean_title(search_query)
    if not songs:
        return None
    first = songs[0]
    list_name = getattr(first, 'list_name', None)
    if kind == 'album' and list_name:
        artist = getattr(first, 'album_artist', None) or getattr(first, 'artist', None)
        return clean_title(f'{artist} - {list_name}' if artist else list_name)
    if list_name:
        return clean_title(list_name)
    if kind == 'track' or len(songs) == 1:
        artist = getattr(first, 'artist', None)
        name = getattr(first, 'name', None)
        if name:
            return clean_title(f'{artist} - {name}' if artist else name)
    return None


def _truncate_utf8(text, max_bytes):
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode('utf-8', errors='ignore')


def safe_filename_stem(title):
    """A file name stem that is safe on Windows, macOS and Linux, or None."""
    title = clean_title(title)
    if not title:
        return None
    stem = _UNSAFE.sub('_', title)
    stem = _SPACES.sub(' ', stem).strip(' .')
    stem = _truncate_utf8(stem, MAX_FILENAME_BYTES).strip(' .')
    if not stem:
        return None
    if stem.split('.')[0].upper() in _WINDOWS_RESERVED:
        stem = f'{stem}_'
    return stem


def zip_download_name(title, unique_id):
    return f'{safe_filename_stem(title) or unique_id}.zip'


def content_disposition(filename, fallback):
    """``attachment`` header with an ASCII name plus the full name per RFC 5987/6266."""
    ascii_name = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    ascii_name = re.sub(r'[^A-Za-z0-9 ._()\[\]&+,;=!#$%\'@^`{}~-]', '_', ascii_name)
    stem = _SPACES.sub(' ', ascii_name.removesuffix('.zip')).strip(' .')
    # A dropped emoji at the end must not leave "Name .zip".
    ascii_name = f'{stem}.zip' if stem.strip(' ._') else fallback
    header = f'attachment; filename="{ascii_name}"'
    if ascii_name != filename:
        header += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return header


def write_zip_title(zip_path, title):
    """Keep the title in the zip comment so it survives a server restart."""
    title = clean_title(title)
    if not title:
        return
    with zipfile.ZipFile(zip_path, 'a') as archive:
        archive.comment = title.encode('utf-8')[:65535]


def read_zip_title(zip_path):
    try:
        with zipfile.ZipFile(zip_path) as archive:
            return clean_title(archive.comment.decode('utf-8', errors='ignore'))
    except (OSError, zipfile.BadZipFile):
        return None
