import json
import logging
import os
import threading

from app.config import SEARCHES_FILE

logger = logging.getLogger(__name__)

_searches_file_lock = threading.Lock()


def read_searches_file():
    """Return the counter document.

    None means the file exists but could not be read. Callers must not replace
    it, or a bad read would wipe a stored concurrent_limit.
    """
    if os.path.isdir(SEARCHES_FILE):
        logger.error("searches.json path is a directory: %s", SEARCHES_FILE)
        return None
    if not os.path.isfile(SEARCHES_FILE):
        return {'total': 0}
    try:
        with open(SEARCHES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.error("searches.json is not a JSON object")
            return None
        return data
    except Exception as e:
        logger.error(f"Error reading searches.json: {e}")
        return None


def write_searches_file(data):
    if os.path.isdir(SEARCHES_FILE):
        raise IsADirectoryError(SEARCHES_FILE)
    directory = os.path.dirname(os.path.abspath(SEARCHES_FILE))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(SEARCHES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def load_initial_concurrent_limit():
    data = read_searches_file()
    if not data:
        return int(os.environ.get('MAX_PENDING_REQUESTS', 5))
    limit = data.get('concurrent_limit')
    if limit is not None:
        try:
            parsed = int(limit)
            if parsed >= 1:
                return parsed
        except (TypeError, ValueError):
            pass
    return int(os.environ.get('MAX_PENDING_REQUESTS', 5))


def persist_concurrent_limit(limit):
    with _searches_file_lock:
        data = read_searches_file()
        if data is None:
            logger.error("Refusing to save concurrent_limit because searches.json could not be read")
            return False
        data['concurrent_limit'] = limit
        write_searches_file(data)
        return True


def record_search():
    try:
        with _searches_file_lock:
            searches = read_searches_file()
            if searches is None:
                logger.error("Skipped download counter update because searches.json could not be read")
                return
            searches['total'] = int(searches.get('total', 0)) + 1
            write_searches_file(searches)
    except Exception as e:
        logger.error(f"Failed to update searches.json: {e}")


def get_download_total():
    try:
        with _searches_file_lock:
            data = read_searches_file()
        if data is None:
            return 0
        return int(data.get('total', 0))
    except Exception as e:
        logger.error(f"Failed to read searches.json in download_counter: {e}")
        return 0
