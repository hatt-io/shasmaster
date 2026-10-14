"""Kernel-held locks for source jobs; interrupted processes release them."""
from contextlib import contextmanager
import errno
import os
import time
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
from .config import USER_DATA
from .db import digest


class SourceJobBusy(RuntimeError):
    pass


@contextmanager
def source_lock(name,blocking=True):
    folder=USER_DATA/'locks';folder.mkdir(exist_ok=True)
    with (folder/(digest(name)+'.lock')).open('a+b') as handle:
        if os.name == 'nt':
            # Windows locks a byte range; always lock the same first byte.
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'\0');handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if not blocking:
                        raise SourceJobBusy('Source job already running: '+name) from exc
                    time.sleep(.05)
            try:yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise SourceJobBusy('Source job already running: '+name) from exc
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def source_running(name):
    try:
        with source_lock(name,blocking=False):return False
    except SourceJobBusy:return True
