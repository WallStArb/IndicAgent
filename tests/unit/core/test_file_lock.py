"""exclusive_file_lock: one holder at a time, a waiter named the holder, a dead holder is free."""

import subprocess
import sys
import threading
import time

import pytest

from src.core.file_lock import exclusive_file_lock


def test_a_second_holder_times_out_naming_the_first(tmp_path):
    lock = tmp_path / "x" / "t.lock"
    with exclusive_file_lock(lock, "first", timeout=5, poll=0.05, label="test lock"):
        with pytest.raises(TimeoutError, match=r"test lock still held .* by: first pid"):
            with exclusive_file_lock(lock, "second", timeout=0.2, poll=0.05, label="test lock"):
                pass
    with exclusive_file_lock(lock, "third", timeout=1, poll=0.05):  # released on exit
        pass


def test_a_waiter_gets_the_lock_after_the_holder_leaves(tmp_path):
    lock = tmp_path / "t.lock"
    order = []

    def hold():
        with exclusive_file_lock(lock, "holder", timeout=5, poll=0.05):
            order.append("held")
            time.sleep(0.4)
        order.append("released")

    thread = threading.Thread(target=hold)
    thread.start()
    while "held" not in order:
        time.sleep(0.02)
    with exclusive_file_lock(lock, "waiter", timeout=5, poll=0.05):
        order.append("waiter")
    thread.join()
    assert order == ["held", "released", "waiter"]


def test_a_holder_killed_hard_leaves_no_stale_lock(tmp_path):
    lock = tmp_path / "t.lock"
    code = (
        "import sys, time; from pathlib import Path; "
        "from src.core.file_lock import exclusive_file_lock; "
        "ctx = exclusive_file_lock(Path(sys.argv[1]), 'doomed', timeout=5, poll=0.05); ctx.__enter__(); "
        "print('held', flush=True); time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(lock)], stdout=subprocess.PIPE)
    try:
        assert proc.stdout.readline().strip() == b"held"
        with pytest.raises(TimeoutError, match="doomed"):
            with exclusive_file_lock(lock, "me", timeout=0.2, poll=0.05):
                pass
    finally:
        proc.kill()
        proc.wait()
    with exclusive_file_lock(lock, "me", timeout=2, poll=0.05):
        pass
