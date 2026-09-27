import logging
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_cleanup_started = False
_cleanup_start_lock = threading.Lock()


def _env_int(name, default):
    return int(os.getenv(name, default))


def _env_float(name, default):
    return float(os.getenv(name, default))


def retention_days():
    return _env_int('CLEANUP_RETENTION_DAYS', os.getenv('RETENTION_DAYS', 14))


def get_directory_size(directory):
    total_size = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(directory):
            for name in filenames:
                path = os.path.join(dirpath, name)
                if not os.path.islink(path):
                    total_size += os.path.getsize(path)
    except OSError as e:
        logger.error("Error calculating directory size for %s: %s", directory, e)
    return total_size


def cleanup_old_files(music_dir, days=None):
    if days is None:
        days = retention_days()
    if not os.path.isdir(music_dir):
        logger.warning("Music directory does not exist yet: %s", music_dir)
        return

    cutoff_date = datetime.now() - timedelta(days=days)
    files_removed = 0

    try:
        for filename in os.listdir(music_dir):
            filepath = os.path.join(music_dir, filename)
            if not os.path.isfile(filepath):
                continue
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))

            if file_modified < cutoff_date:
                try:
                    os.remove(filepath)
                    files_removed += 1
                    logger.info("Removed old file: %s", filename)
                except OSError as e:
                    logger.error("Error removing file %s: %s", filename, e)

        logger.info("Cleanup completed. Removed %s files.", files_removed)
    except Exception as e:
        logger.error("Error during cleanup: %s", e)


def cleanup_by_size(music_dir):
    max_music_dir_size_mb = _env_float('MAX_MUSIC_DIR_SIZE_MB', 0)
    if max_music_dir_size_mb <= 0:
        return
    if not os.path.isdir(music_dir):
        logger.warning("Music directory does not exist yet: %s", music_dir)
        return

    cleanup_target_percentage = _env_float('CLEANUP_TARGET_PERCENTAGE', 90)
    max_size_bytes = max_music_dir_size_mb * 1024 * 1024
    target_size_bytes = max_size_bytes * (cleanup_target_percentage / 100)
    current_size_bytes = get_directory_size(music_dir)

    if current_size_bytes <= max_size_bytes:
        logger.debug(
            "Music directory size (%.2fMB) is within the limit (%.2fMB).",
            current_size_bytes / (1024 * 1024),
            max_music_dir_size_mb,
        )
        return

    logger.info(
        "Music directory size (%.2fMB) exceeds limit (%.2fMB). Starting cleanup.",
        current_size_bytes / (1024 * 1024),
        max_music_dir_size_mb,
    )

    zip_files = []
    try:
        for filename in os.listdir(music_dir):
            if filename.lower().endswith('.zip'):
                filepath = os.path.join(music_dir, filename)
                try:
                    zip_files.append({
                        'path': filepath,
                        'mtime': os.path.getmtime(filepath),
                        'size': os.path.getsize(filepath),
                    })
                except OSError as e:
                    logger.warning("Could not access file %s for size cleanup: %s", filepath, e)
    except Exception as e:
        logger.error("Error listing zip files in %s: %s", music_dir, e)
        return

    zip_files.sort(key=lambda x: x['mtime'])

    files_removed_count = 0
    space_freed_bytes = 0

    for file_info in zip_files:
        if current_size_bytes <= target_size_bytes:
            break

        try:
            logger.info("Removing old zip file: %s to free up space.", file_info['path'])
            os.remove(file_info['path'])
            current_size_bytes -= file_info['size']
            space_freed_bytes += file_info['size']
            files_removed_count += 1
        except OSError as e:
            logger.error("Error removing zip file %s: %s", file_info['path'], e)

    if files_removed_count > 0:
        logger.info(
            "Cleanup by size completed. Removed %s zip files. Freed %.2fMB. Current dir size: %.2fMB",
            files_removed_count,
            space_freed_bytes / (1024 * 1024),
            current_size_bytes / (1024 * 1024),
        )
    else:
        logger.info(
            "Cleanup by size: No zip files were removed. Current dir size: %.2fMB. Target size: %.2fMB",
            current_size_bytes / (1024 * 1024),
            target_size_bytes / (1024 * 1024),
        )


def run_cleanup_loop(music_dir, expire_callback=None):
    days = retention_days()
    age_interval = _env_int('AGE_CLEANUP_INTERVAL', 86400)
    size_interval = _env_int('SIZE_CHECK_INTERVAL', 3600)
    max_music_dir_size_mb = _env_float('MAX_MUSIC_DIR_SIZE_MB', 0)
    cleanup_target_percentage = _env_float('CLEANUP_TARGET_PERCENTAGE', 90)

    logger.info("Cleanup thread started.")
    logger.info(
        "Age-based cleanup: Retention period: %s days, Interval: %s seconds.",
        days,
        age_interval,
    )
    if max_music_dir_size_mb > 0:
        logger.info(
            "Size-based cleanup: Max music directory size: %s MB, Target: %s%%, Interval: %s seconds.",
            max_music_dir_size_mb,
            cleanup_target_percentage,
            size_interval,
        )
    else:
        logger.info(
            "Size-based cleanup: Music directory size limit is not set (MAX_MUSIC_DIR_SIZE_MB is 0 or not defined)."
        )

    last_age_cleanup_time = time.time()
    last_size_check_time = time.time()

    while True:
        if expire_callback is not None:
            try:
                expire_callback()
            except Exception as e:
                logger.error("Error expiring in-memory download state: %s", e)

        current_time = time.time()

        if current_time - last_age_cleanup_time >= age_interval:
            logger.info("Running age-based cleanup...")
            cleanup_old_files(music_dir, days)
            last_age_cleanup_time = time.time()
            logger.info("Age-based cleanup finished.")

        if max_music_dir_size_mb > 0 and (current_time - last_size_check_time >= size_interval):
            logger.info("Running size-based cleanup check...")
            cleanup_by_size(music_dir)
            last_size_check_time = time.time()
            logger.info("Size-based cleanup check finished.")

        time.sleep(60)


def start_cleanup_thread(music_dir, expire_callback=None):
    global _cleanup_started
    with _cleanup_start_lock:
        if _cleanup_started:
            return
        _cleanup_started = True
        thread = threading.Thread(
            target=run_cleanup_loop,
            args=(music_dir, expire_callback),
            name="cleanup",
            daemon=True,
        )
        thread.start()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )
    music_dir = os.environ.get('MUSIC_DIR', '/var/www/SpotifyDownloader/')
    run_cleanup_loop(music_dir)


if __name__ == "__main__":
    main()
