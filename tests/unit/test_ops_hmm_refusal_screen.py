import json
from argparse import Namespace

import numpy as np
import pytest

from scripts.ops.ops_hmm_refusal_screen import (
    _names,
    _read_records,
    _summarize,
    aggregate,
    decide,
    summarize_run,
)
from src.intelligence.features.kernels._hmm import (
    EVENT_CONVERGENCE,
    EVENT_SEGMENT_SKIPPED,
    RegimeEventRecord,
)


def _record(tf, k, segments, refused, modeled=100, written=50, hit_cap=0):
    return {
        "tf": tf,
        "k": k,
        "segments": segments,
        "refused": refused,
        "modeled": modeled,
        "written": written,
        "hit_cap": hit_cap,
    }


def test_summarize_run_counts_segments_and_reasons():
    status = np.array([0.0, 0.0, 1.0, 1.0, 2.0, 5.0])
    fit = {"iters_used": 200, "n_iter_cap": 200, "converged": True}
    events = [
        RegimeEventRecord(EVENT_CONVERGENCE, fit),
        RegimeEventRecord(EVENT_SEGMENT_SKIPPED, {"reason": "degenerate_occupation"}),
        RegimeEventRecord(EVENT_SEGMENT_SKIPPED, {"reason": "fit_failed"}),
    ]
    out = summarize_run(status, events)
    assert (out["modeled"], out["written"]) == (4, 2)
    assert out["segments"] == 2  # one fitted segment plus one failed fit
    assert out["refused"] == 2 and out["hit_cap"] == 1
    assert out["reasons"] == {"degenerate_occupation": 1, "fit_failed": 1}


def test_aggregate_excludes_unmodeled_names_from_name_shares():
    rows = aggregate(
        [
            _record("1d", 5, 10, 8, modeled=100, written=0),
            _record("1d", 5, 10, 2, modeled=100, written=80),
            _record("1d", 5, 0, 0, modeled=0, written=0),  # too short for any model
        ]
    )
    (row,) = rows
    assert row["names"] == 3 and row["names_modeled"] == 2
    assert row["refused_share"] == 0.5 and row["zero_output_share"] == 0.5
    assert row["median_written_share"] == 0.4


def test_decide_takes_smallest_k_within_two_points_of_the_best():
    rows = aggregate(
        [
            _record("1d", 3, 100, 20),  # 20%: 1 point above the best
            _record("1d", 4, 100, 19),
            _record("1d", 5, 100, 70),
            _record("1h", 3, 100, 30),
            _record("1h", 4, 100, 25),  # 5 points better than K=3: K=3 is outside the band
            _record("1h", 5, 100, 27),
        ]
    )
    assert decide(rows) == {"1d": 3, "1h": 4}


def test_decide_two_point_gap_is_inside_the_band_despite_float_error():
    # 0.20 - 0.18 is 0.020000000000000018 in floating point
    rows = aggregate([_record("1d", 3, 100, 20), _record("1d", 4, 100, 18)])
    assert decide(rows) == {"1d": 3}


def test_read_records_dedupes_resumed_lines_and_survives_a_truncated_line(tmp_path):
    base = {"symbol": "A", "tf": "1d", "family": "trend", "k": 3}
    path = tmp_path / "run.jsonl"
    path.write_text(
        json.dumps({**base, "refused": 5}) + "\n  \n" + json.dumps({**base, "refused": 2}) + "\n"
        '{"symbol": "B", "tf"'
    )
    records, unreadable = _read_records([str(path)])
    assert [r["refused"] for r in records] == [2] and unreadable == 1


def _args(**kw):
    return Namespace(
        **{
            "symbols": [f"S{i}" for i in range(10)],
            "symbols_file": None,
            "sample": None,
            "seed": 7,
            "shard": "0/1",
            **kw,
        }
    )


def test_names_shards_partition_and_sample_is_seeded():
    shards = [_names(_args(shard=f"{i}/3")) for i in range(3)]
    assert sorted(n for shard in shards for n in shard) == sorted(_args().symbols)
    assert _names(_args(sample=4)) == _names(_args(sample=4))
    for bad in (_args(shard="3/3"), _args(shard="x"), _args(sample=11), _args(sample=0)):
        with pytest.raises(SystemExit):
            _names(bad)


def test_summarize_reports_errors_and_noncomparable_name_sets(tmp_path, capsys):
    rows = [
        {
            "symbol": "A",
            "tf": "1d",
            "family": "trend",
            "k": 3,
            "segments": 10,
            "refused": 2,
            "modeled": 100,
            "written": 80,
            "hit_cap": 0,
        },
        {"symbol": "B", "tf": "1d", "family": "trend", "k": 3, "error": "ValueError: boom"},
        {
            "symbol": "A",
            "tf": "1d",
            "family": "trend",
            "k": 5,
            "segments": 10,
            "refused": 9,
            "modeled": 100,
            "written": 10,
            "hit_cap": 0,
        },
        {
            "symbol": "C",
            "tf": "1d",
            "family": "trend",
            "k": 5,
            "segments": 10,
            "refused": 9,
            "modeled": 100,
            "written": 10,
            "hit_cap": 0,
        },
    ]
    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    _summarize([str(path)])
    out = capsys.readouterr().out
    assert "1 name fits errored" in out
    assert "K cells cover different names" in out
    assert "chosen K per timeframe: {'1d': 3}" in out
