"""Float32ChunkAccumulator: bounded-memory chunk accumulation for float32 columns."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import numpy as np
import structlog

_logger = structlog.get_logger()


class Float32ChunkAccumulator:
    """Buffers rows into vstack-ready float32 chunks, freeing each chunk's Python-list
    intermediate as soon as it's converted (todo 087).

    Shared 'accumulate rows -> np.array chunk -> vstack once at the end, discarding
    intermediates' idiom behind ic_engine.py's per-symbol OOM fix (`_compute_symbol_tf`,
    a named server-side cursor streaming rows one at a time) and its cross-sectional
    OOM fix (`_compute_cross_sectional_tf`, a plain cursor re-executed per explicit
    timestamp chunk, fetching a whole batch per query). The query/cursor/pagination
    mechanics genuinely differ between those two callers and are left entirely to
    them; this owns only the buffer-to-float32-array bookkeeping both duplicated.

    Two append modes, matching the two callers' shapes:
    - append_row(): one row at a time, auto-flushed into a chunk every `flush_at` rows
      (the streaming-cursor shape).
    - append_chunk(): one pre-fetched batch at a time, converted to a chunk immediately
      (the re-executed-per-query-chunk shape). Ignores an empty batch.

    Two accumulation modes (additive, Phase 174 D-04 / todo 371 -- NOT a forked
    parallel class; migration 249 already corrected that exact mistake once for
    `_check_cell_size` and RESEARCH.md's Don't-Hand-Roll table names it again):
    - In-RAM (default, disk_backed=False): byte-for-byte the original behavior above.
      `finalize()` holds the full chunk list AND the vstacked result in RAM
      simultaneously -- roughly 2x the cell size at peak. Fine for small cells; this
      is what OOM-killed ic_engine at universe scale for the largest cross-sectional
      cells (todo 371).
    - Disk-backed (disk_backed=True): both append modes write directly into an
      `np.memmap`-backed scratch file at a running row offset instead of a Python
      list of chunks. `finalize()` returns a VIEW over the memmap -- no
      `np.vstack`, no copy -- so peak anonymous RSS is bounded by one chunk's size,
      not the whole cell's size. Requires `estimated_rows` (a conservative upper
      bound on total rows the caller's pre-flight estimate produced) and `n_cols`
      up front to pre-allocate the memmap; `finalize()` trims the returned view to
      the actual rows written. An under-estimate is crash-loud (`ValueError`) rather
      than silently truncating the cell -- per CLAUDE.md, "silent wrong answers are
      worse than loud crashes," and a silently short cell would change what the
      corpus measures.

    Memmap ownership contract (disk-backed mode only -- load-bearing for Plans 05 and
    09, both reviewers flagged this as the phase's highest-risk ambiguity):
    - `finalize()` returns a VIEW over the memmap, not a copy.
    - The caller owns `close()` and calls it only after every consumer of the
      returned view has returned: the caller's `try`/`finally` must span every
      downstream consumer, not just the accumulation loop, so the scratch file's disk
      space is reclaimed as soon as the cell is done.
    - A view that outlives `close()` is still memory-safe: `close()` unlinks the file
      but never unmaps it, so the view keeps reading this cell's own data until it is
      garbage-collected (Linux keeps an unlinked, still-mapped inode alive). Holding
      one holds the scratch file's disk pages, so it is a leak to fix, never a
      correctness hazard.
    """

    def __init__(
        self,
        flush_at: int | None = None,
        *,
        disk_backed: bool = False,
        estimated_rows: int | None = None,
        n_cols: int | None = None,
        scratch_dir: str | None = None,
    ) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []
        self._disk_backed = disk_backed
        self._write_offset = 0
        self._estimated_rows: int | None = None
        self._memmap: np.memmap | None = None
        self._tmpfile: Any = None
        if disk_backed:
            missing = [
                name
                for name, val in (("estimated_rows", estimated_rows), ("n_cols", n_cols))
                if not val
            ]
            if missing:
                raise ValueError(
                    "Float32ChunkAccumulator(disk_backed=True) requires "
                    f"{' and '.join(missing)} to be set"
                )
            self._estimated_rows = estimated_rows
            if scratch_dir:
                os.makedirs(scratch_dir, exist_ok=True)
            self._tmpfile = tempfile.NamedTemporaryFile(
                dir=scratch_dir, suffix=".memmap", delete=False
            )
            self._memmap = np.memmap(
                self._tmpfile.name,
                dtype=np.float32,
                mode="w+",
                shape=(estimated_rows, n_cols),
            )

    def append_row(self, row: Any) -> None:
        if self._disk_backed and self._flush_at is None:
            # Without flush_at every row stays in the Python buffer until finalize(),
            # so a disk-backed accumulator would hold the whole cell in RAM -- the
            # exact thing disk-backing exists to prevent (174 review IN-07).
            raise ValueError(
                "Float32ChunkAccumulator(disk_backed=True).append_row() requires flush_at; "
                "use append_chunk() or construct with flush_at"
            )
        self._buf.append(row)
        if self._flush_at is not None and len(self._buf) >= self._flush_at:
            self._flush_buf()

    def append_chunk(self, rows: Any) -> None:
        if not len(rows):
            return
        if self._disk_backed:
            self._write_disk_chunk(rows)
        else:
            self._chunks.append(np.array(rows, dtype=np.float32))

    def _write_disk_chunk(self, rows: Any) -> None:
        """Write one batch directly into the memmap at the running offset.

        Crash-loud on overflow (Phase 174 D-04, todo 371 / T-174-06): a pre-flight
        row estimate that undercounts must fail loud, never silently truncate the
        cell -- that would change what is measured, exactly the failure class the
        cross-sectional cell-size guard already exists to forbid elsewhere.
        """
        arr = np.array(rows, dtype=np.float32)
        n = arr.shape[0]
        end = self._write_offset + n
        if self._estimated_rows is not None and end > self._estimated_rows:
            raise ValueError(
                f"Float32ChunkAccumulator disk-backed overflow: estimated_rows="
                f"{self._estimated_rows} but this write would reach {end} rows -- "
                "the pre-flight row estimate undercounted; fix the estimate, do not "
                "silently truncate the cell"
            )
        self._memmap[self._write_offset : end] = arr
        self._write_offset = end

    def _flush_buf(self) -> None:
        if not self._buf:
            return
        if self._disk_backed:
            self._write_disk_chunk(self._buf)
        else:
            self._chunks.append(np.array(self._buf, dtype=np.float32))
        self._buf = []

    def finalize(self) -> np.ndarray | None:
        """Disk-backed: flush any buffered rows, then return
        `self._memmap[: self._write_offset]` -- a VIEW over the memmap, no
        `np.vstack`, no copy. That view stays readable until, and only until, the
        caller calls `close()`; the caller's `try`/`finally` must span every
        downstream consumer of this return value, not just the accumulation loop
        (see the class docstring's memmap ownership contract). Returns `None` (and
        cleans up the scratch file immediately via `close()`) when nothing was ever
        appended, matching the in-RAM mode's empty contract.

        In-RAM: vstack every chunk and free them; None if nothing was ever appended.
        """
        self._flush_buf()
        if self._disk_backed:
            if self._write_offset == 0:
                self.close()
                return None
            return self._memmap[: self._write_offset]
        if not self._chunks:
            return None
        result = np.vstack(self._chunks)
        self._chunks = []
        return result

    def close(self) -> None:
        """Release a disk-backed accumulator's resources: flush and drop the memmap,
        close the underlying `NamedTemporaryFile` handle, then unlink the scratch file.
        Not closing the `NamedTemporaryFile` leaks one Python file descriptor per
        accumulator (T-174-39) -- across the thousands of cells in a corpus run that
        exhausts the process fd limit. The mapping itself is released when its last
        view is garbage-collected, never by an explicit close (see below).

        Idempotent: safe to call twice, and a no-op in in-RAM mode. Each step is
        wrapped independently so a failure in one does not skip the others. Plan 05's
        caller invokes this in a `finally` block that spans every consumer of
        `finalize()`'s returned view -- see the class docstring's ownership contract.
        """
        path = self._tmpfile.name if self._tmpfile is not None else None
        if self._memmap is not None:
            try:
                self._memmap.flush()
            except Exception as error:
                _logger.warning("float32_chunk_accumulator.mmap_flush_failed", error=str(error))
            # Drop the reference; never close the mmap explicitly. An explicit
            # `_mmap.close()` turned any still-live view into a use-after-unmap:
            # a segfault, or -- once a later cell's memmap reused the address -- a
            # silent read of another cell's data (174 review WR-06). Without it the
            # kernel unmaps when the last view is garbage-collected, and a stale read
            # returns this cell's own data.
            self._memmap = None
        if self._tmpfile is not None:
            try:
                self._tmpfile.close()
            except Exception as error:
                _logger.warning("float32_chunk_accumulator.tmpfile_close_failed", error=str(error))
            finally:
                self._tmpfile = None
        if path is not None:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as error:
                _logger.warning(
                    "float32_chunk_accumulator.unlink_failed", path=path, error=str(error)
                )

    def __enter__(self) -> Float32ChunkAccumulator:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
