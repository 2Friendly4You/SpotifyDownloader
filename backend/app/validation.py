import re
from urllib.parse import urlparse

from app.config import VALID_AUDIO_PROVIDERS, VALID_LYRICS_PROVIDERS, VALID_OUTPUT_FORMATS


def is_valid_url(input_url):
    try:
        result = urlparse(input_url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def validate_spotify_url(input_url):
    parsed_url = urlparse(input_url)
    return parsed_url.scheme in ['http', 'https'] and parsed_url.netloc == 'open.spotify.com'


def is_youtube_url(url):
    youtube_regex = r'^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$'
    return bool(re.match(youtube_regex, url))


def validate_song_title(title):
    return bool(re.match(r"^[\w\s\-'.,!&?=-]+$", title, re.UNICODE))


def validate_input(input_string):
    if is_valid_url(input_string):
        return validate_spotify_url(input_string) or is_youtube_url(input_string)
    return validate_song_title(input_string)


def validate_format_options(audio_format, lyrics_format, output_format):
    return (
        audio_format in VALID_AUDIO_PROVIDERS and
        lyrics_format in VALID_LYRICS_PROVIDERS and
        output_format in VALID_OUTPUT_FORMATS
    )
