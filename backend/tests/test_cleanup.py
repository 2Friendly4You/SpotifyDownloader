import os
import time

from cleanup_service import cleanup_old_files


def test_cleanup_removes_files_older_than_the_retention_period(tmp_path):
    old_file = tmp_path / "old.zip"
    new_file = tmp_path / "new.zip"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    old_timestamp = time.time() - (10 * 86400)
    os.utime(old_file, (old_timestamp, old_timestamp))

    cleanup_old_files(str(tmp_path), days=7)

    assert not old_file.exists()
    assert new_file.read_bytes() == b"new"
