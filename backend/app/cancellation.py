"""Stop a running download when the user cancels it.

spotDL and yt-dlp have no cancel API, so cancelling works on three levels:

* a flag in DownloadState that every progress callback checks; raising
  JobCancelled there aborts yt-dlp downloads (it is a DownloadCancelled)
  and the spotDL step that reported progress,
* cancelling the asyncio tasks on the spotDL downloader's loop, so songs
  that wait for a free thread never start,
* killing child processes (ffmpeg) whose command line contains the job id,
  because the output path of every file of a job contains it.
"""
import asyncio
import os
import signal
import threading

from yt_dlp.utils import DownloadCancelled


class JobCancelled(DownloadCancelled):
    """Raised inside a download job after the user cancelled it."""

    def __init__(self, unique_id=''):
        super().__init__(f'Download {unique_id} was cancelled')


_lock = threading.Lock()
_stoppers = {}


def register(unique_id, stopper):
    """Remember how to interrupt a running job, e.g. cancel its event loop."""
    with _lock:
        _stoppers[unique_id] = stopper


def unregister(unique_id):
    with _lock:
        _stoppers.pop(unique_id, None)


def stop(unique_id):
    """Interrupt a running job right away, as far as possible."""
    with _lock:
        stopper = _stoppers.get(unique_id)
    if stopper is not None:
        stopper()
    return kill_job_processes(unique_id)


def loop_stopper(loop):
    """A stopper that cancels every task on a spotDL downloader's loop."""
    def cancel_tasks():
        for task in asyncio.all_tasks(loop):
            task.cancel()

    def stopper():
        if not loop.is_closed():
            loop.call_soon_threadsafe(cancel_tasks)
    return stopper


def kill_job_processes(unique_id, proc_root='/proc', kill=os.kill):
    """Kill child processes that work on this job's files. Returns their pids."""
    if not unique_id or not os.path.isdir(proc_root):
        return []
    own_pid = os.getpid()
    killed = []
    for entry in os.listdir(proc_root):
        if not entry.isdigit() or int(entry) == own_pid:
            continue
        try:
            with open(os.path.join(proc_root, entry, 'cmdline'), 'rb') as handle:
                cmdline = handle.read().replace(b'\0', b' ').decode('utf-8', 'replace')
        except OSError:
            continue
        if unique_id in cmdline:
            try:
                kill(int(entry), signal.SIGKILL)
                killed.append(int(entry))
            except OSError:
                pass
    return killed
