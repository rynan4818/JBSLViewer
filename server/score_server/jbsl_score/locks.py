"""OS-backed locks: threads and processes share the same local data directory."""

import hashlib
import asyncio
import os
import time
from pathlib import Path

from .errors import ApiProblem

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class FileLock:
    def __init__(self, directory: Path, key: str):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
        self.stream = None

    def acquire(self, timeout=25):
        stream = self.path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        until = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.stream = stream
                return self
            except OSError:
                if time.monotonic() >= until:
                    stream.close()
                    raise ApiProblem(503, "server_busy", "This operation is busy; retry with the same key.")
                time.sleep(0.02)

    def release(self):
        if self.stream:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None

    async def acquire_async(self, timeout=25):
        # Waiting uploads must not occupy every worker-pool thread while the lock
        # owner needs one of those threads to validate/commit its result.
        until = time.monotonic() + timeout
        while True:
            try:
                return self.acquire(timeout=0)
            except ApiProblem:
                if time.monotonic() >= until:
                    raise
                await asyncio.sleep(0.02)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()
