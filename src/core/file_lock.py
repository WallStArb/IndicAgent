"""Cross-process exclusive file lock (Ring 0, portable infrastructure).

One process at a time holds a named lock file. The lock is an `fcntl.flock` on the open file, so a
holder that dies (even by SIGKILL) releases it when the kernel closes its descriptor; there is no
stale lock to clean up. The holder writes a one-line note into the file so a waiter, or a timeout
message, can say who holds it. The note is advisory; the flock is the lock.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path


def _holder(fd: int) -> str:
    return os.pread(fd, 400, 0).decode(errors="replace").strip()


@contextlib.contextmanager
def exclusive_file_lock(
    path: Path,
    note: str,
    *,
    timeout: float,
    poll: float,
    label: str = "lock",
) -> Iterator[None]:
    """Hold an exclusive lock on `path`, waiting up to `timeout` seconds and saying who holds it.
    Raises TimeoutError naming the holder's note when the wait runs out."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    waited = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"{label} still held after {timeout:.0f}s by: {_holder(fd)}"
                    ) from error
                if not waited:
                    print(
                        f"  waiting for the {label}, held by: {_holder(fd) or 'unknown'}",
                        flush=True,
                    )
                    waited = True
                time.sleep(poll)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{note} pid {os.getpid()} since {datetime.now(UTC).isoformat()}".encode(), 0)
        yield
    finally:
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
        os.close(fd)  # closing releases the flock
