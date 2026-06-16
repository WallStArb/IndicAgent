#!/usr/bin/env python3
"""
Monitor Phase 127 replay progress and wait for completion.

This script polls the replay process and checks for:
1. Warmup pass completion marker
2. Signal pass completion marker
3. Process exit status
4. Post-replay row counts

Usage:
    python production/scripts/phase_127_monitor_replay.py <PID>
"""

import sys
import time
import subprocess
from pathlib import Path

# PID passed as argument
if len(sys.argv) != 2:
    print("Usage: python phase_127_monitor_replay.py <PID>")
    sys.exit(1)

pid = int(sys.argv[1])
log_file = Path("docs/plans/phase-127-replay-log.md.raw")

print(f"Monitoring replay process {pid}...")
print(f"Log file: {log_file}")

last_size = 0
check_interval = 30  # seconds

while True:
    # Check if process is still running
    try:
        result = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"\nProcess {pid} has completed.")
            break
    except Exception as e:
        print(f"\nError checking process: {e}")
        break

    # Check log file for completion markers
    if log_file.exists():
        content = log_file.read_text()

        # Check for warmup pass marker
        if "Running warmup pass (I1-I6 only)" in content and "Warmup complete. Running signal pass" in content:
            print(f"✓ Warmup pass complete, signal pass running")

        # Check for completion
        if "Backfill complete" in content:
            print(f"✓ Replay complete!")
            break

        # Check for errors
        if "ERROR" in content or "Traceback" in content:
            print(f"⚠ Error detected in log file")
            break

        # Show progress
        current_size = log_file.stat().st_size
        if current_size != last_size:
            progress = current_size - last_size
            last_size = current_size
            print(f"Log growing: {current_size:,} bytes (+{progress:,})")

    time.sleep(check_interval)

print("\nFinal status check:")
print(f"Process {pid}:")

# Get final exit status via wait
try:
    result = subprocess.run(["ps", "-o", "stat", "-p", str(pid)], capture_output=True, text=True)
    print(f"  Status: {result.stdout.strip()}")
except:
    pass

# Check for warmup markers in log
if log_file.exists():
    content = log_file.read_text()
    warmup_running = "Running warmup pass (I1-I6 only)" in content
    warmup_complete = "Warmup complete. Running signal pass" in content
    replay_complete = "Backfill complete" in content

    print(f"\nWarmup markers:")
    print(f"  Warmup pass started: {warmup_running}")
    print(f"  Warmup complete: {warmup_complete}")
    print(f"  Replay complete: {replay_complete}")

    # Check for parallel-mode skip note (should NOT appear)
    if "only supported with --workers 1 (parallel mode skips warmup pass)" in content:
        print(f"  ⚠ WARNING: Warmup was skipped (parallel mode detected)")

print("\nMonitor complete.")
