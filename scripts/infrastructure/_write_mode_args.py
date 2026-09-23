"""Shared --dry-run / --commit flags for scripts whose writes are opt-in."""

from __future__ import annotations

import argparse


def add_write_mode_args(parser: argparse.ArgumentParser, *, dry_run: str, commit: str) -> None:
    """Add mutually exclusive --dry-run (the default) and --commit flags.

    Callers branch on `args.commit` only. Mutual exclusion makes "--dry-run --commit" a
    usage error rather than a silent commit (174 review IN-02). `dry_run` and `commit` are
    the script-specific help texts.
    """
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help=dry_run)
    mode.add_argument("--commit", action="store_true", default=False, help=commit)
