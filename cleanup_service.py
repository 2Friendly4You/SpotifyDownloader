import os
import time
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

MUSIC_DIR = "/var/www/SpotifyDownloader/"
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', 14))
CLEANUP_INTERVAL = int(os.getenv('CLEANUP_INTERVAL', 86400))

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

def main():
    logging.info(f"Cleanup service started. Retention period: {RETENTION_DAYS} days")
    logging.info(f"Cleanup interval: {CLEANUP_INTERVAL} seconds")
    
    while True:
        cleanup_old_files()
        time.sleep(CLEANUP_INTERVAL)

if __name__ == "__main__":
    main()
