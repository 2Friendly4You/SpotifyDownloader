from app.validation import is_youtube_url, validate_format_options, validate_input


def test_spotify_and_youtube_urls_are_accepted():
    assert validate_input("https://open.spotify.com/track/abc") is True
    assert validate_input("https://youtu.be/dQw4w9WgXcQ") is True
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_other_urls_are_rejected():
    assert validate_input("https://example.com/song") is False


def test_plain_song_titles_are_accepted():
    assert validate_input("Daft Punk - One More Time") is True


def test_titles_with_disallowed_characters_are_rejected():
    assert validate_input("$$$") is False


def test_format_options_must_be_known_providers():
    assert validate_format_options("youtube", "genius", "mp3") is True
    assert validate_format_options("nope", "genius", "mp3") is False
    assert validate_format_options("youtube", "nope", "mp3") is False
    assert validate_format_options("youtube", "genius", "aiff") is False
