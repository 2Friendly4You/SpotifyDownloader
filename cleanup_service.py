import os
import time
from datetime import datetime, timedelta
import logging
import shutil # Add shutil for disk_usage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

MUSIC_DIR = "/var/www/SpotifyDownloader/"
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', 14))
AGE_CLEANUP_INTERVAL = int(os.getenv('AGE_CLEANUP_INTERVAL', 86400)) # Renamed from CLEANUP_INTERVAL
MAX_MUSIC_DIR_SIZE_MB = float(os.getenv('MAX_MUSIC_DIR_SIZE_MB', 0)) # 0 means no limit
CLEANUP_TARGET_PERCENTAGE = float(os.getenv('CLEANUP_TARGET_PERCENTAGE', 90)) # Target 90% of max size
SIZE_CHECK_INTERVAL = int(os.getenv('SIZE_CHECK_INTERVAL', 3600)) # New: Check size every hour by default

def get_directory_size(directory):
    """Calculate the total size of a directory in bytes."""
    total_size = 0
    try:
        # More robust way to get directory size, especially for large directories
        # For Python 3.3+
        if hasattr(shutil, 'disk_usage'):
            total, used, free = shutil.disk_usage(directory)
            # We are interested in the size of the files within the directory,
            # not the disk usage of the partition.
            # So, we'll iterate through files.
            for dirpath, dirnames, filenames in os.walk(directory):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    # skip if it is symbolic link
                    if not os.path.islink(fp):
                        total_size += os.path.getsize(fp)
        else: # Fallback for older Python versions or if shutil.disk_usage is not appropriate
            for dirpath, dirnames, filenames in os.walk(directory):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total_size += os.path.getsize(fp)
    except Exception as e:
        logging.error(f"Error calculating directory size for {directory}: {e}")
    return total_size

def cleanup_old_files():
    """Delete files older than RETENTION_DAYS"""
    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
    files_removed = 0
    
    try:
        for filename in os.listdir(MUSIC_DIR):
            filepath = os.path.join(MUSIC_DIR, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            
            if file_modified < cutoff_date:
                try:
                    os.remove(filepath)
                    files_removed += 1
                    logging.info(f"Removed old file: {filename}")
                except OSError as e:
                    logging.error(f"Error removing file {filename}: {e}")
        
        logging.info(f"Cleanup completed. Removed {files_removed} files.")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

def cleanup_by_size():
    """Delete oldest ZIP files if music directory exceeds MAX_MUSIC_DIR_SIZE_MB."""
    if MAX_MUSIC_DIR_SIZE_MB <= 0: # If limit is not set or invalid, skip
        return

    max_size_bytes = MAX_MUSIC_DIR_SIZE_MB * 1024 * 1024
    target_size_bytes = max_size_bytes * (CLEANUP_TARGET_PERCENTAGE / 100)
    
    current_size_bytes = get_directory_size(MUSIC_DIR)
    
    if current_size_bytes > max_size_bytes:
        logging.info(f"Music directory size ({current_size_bytes / (1024*1024):.2f}MB) exceeds limit ({MAX_MUSIC_DIR_SIZE_MB:.2f}MB). Starting cleanup.")
        
        # Get all .zip files with their modification times
        zip_files = []
        try:
            for filename in os.listdir(MUSIC_DIR):
                if filename.lower().endswith('.zip'):
                    filepath = os.path.join(MUSIC_DIR, filename)
                    try:
                        mtime = os.path.getmtime(filepath)
                        fsize = os.path.getsize(filepath)
                        zip_files.append({'path': filepath, 'mtime': mtime, 'size': fsize})
                    except OSError as e:
                        logging.warning(f"Could not access file {filepath} for size cleanup: {e}")
        except Exception as e:
            logging.error(f"Error listing zip files in {MUSIC_DIR}: {e}")
            return

        # Sort by modification time (oldest first)
        zip_files.sort(key=lambda x: x['mtime'])
        
        files_removed_count = 0
        space_freed_bytes = 0

        for file_info in zip_files:
            if current_size_bytes <= target_size_bytes:
                break # Target size reached
            
            try:
                logging.info(f"Removing old zip file: {file_info['path']} to free up space.")
                os.remove(file_info['path'])
                current_size_bytes -= file_info['size']
                space_freed_bytes += file_info['size']
                files_removed_count += 1
            except OSError as e:
                logging.error(f"Error removing zip file {file_info['path']}: {e}")
        
        if files_removed_count > 0:
            logging.info(f"Cleanup by size completed. Removed {files_removed_count} zip files. Freed {space_freed_bytes / (1024*1024):.2f}MB. Current dir size: {current_size_bytes / (1024*1024):.2f}MB")
        else:
            logging.info(f"Cleanup by size: No zip files were removed. Current dir size: {current_size_bytes / (1024*1024):.2f}MB. Target size: {target_size_bytes / (1024*1024):.2f}MB")
    else:
        logging.debug(f"Music directory size ({current_size_bytes / (1024*1024):.2f}MB) is within the limit ({MAX_MUSIC_DIR_SIZE_MB:.2f}MB).")


def main():
    logging.info(f"Cleanup service started.")
    logging.info(f"Age-based cleanup: Retention period: {RETENTION_DAYS} days, Interval: {AGE_CLEANUP_INTERVAL} seconds.")
    if MAX_MUSIC_DIR_SIZE_MB > 0:
        logging.info(f"Size-based cleanup: Max music directory size: {MAX_MUSIC_DIR_SIZE_MB} MB, Target: {CLEANUP_TARGET_PERCENTAGE}%, Interval: {SIZE_CHECK_INTERVAL} seconds.")
    else:
        logging.info("Size-based cleanup: Music directory size limit is not set (MAX_MUSIC_DIR_SIZE_MB is 0 or not defined).")

    last_age_cleanup_time = time.time()
    last_size_check_time = time.time()

    while True:
        current_time = time.time()

        # Check for age-based cleanup
        if current_time - last_age_cleanup_time >= AGE_CLEANUP_INTERVAL:
            logging.info("Running age-based cleanup...")
            cleanup_old_files()
            last_age_cleanup_time = time.time()
            logging.info("Age-based cleanup finished.")

        # Check for size-based cleanup
        if MAX_MUSIC_DIR_SIZE_MB > 0 and (current_time - last_size_check_time >= SIZE_CHECK_INTERVAL):
            logging.info("Running size-based cleanup check...")
            cleanup_by_size()
            last_size_check_time = time.time()
            logging.info("Size-based cleanup check finished.")
        
        # Sleep for a short interval to avoid busy-waiting, e.g., 1 minute
        # The actual check interval is determined by AGE_CLEANUP_INTERVAL and SIZE_CHECK_INTERVAL
        # This sleep is just to make the loop non-blocking for the CPU
        time.sleep(60) 

if __name__ == "__main__":
    main()
