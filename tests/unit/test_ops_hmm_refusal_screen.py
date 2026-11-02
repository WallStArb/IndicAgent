import json
import math
from argparse import Namespace

import numpy as np
import pytest

from scripts.ops.ops_hmm_refusal_screen import (
    _n_params,
    _names,
    _read_records,
    _summarize,
    aggregate,
    bic_arm_summary,
    bic_fit_record,
    decide,
    segment_layout,
    summarize_run,
    summarize_stored,
)
from src.intelligence.features.kernels._hmm import (
    EVENT_CONVERGENCE,
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    HmmConfig,
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
    fit = {"iters_used": 200, "n_iter_cap": 200, "converged": True, "seg_start": 0}
    events = [
        RegimeEventRecord(EVENT_CONVERGENCE, fit),
        RegimeEventRecord(
            EVENT_SEGMENT_SKIPPED, {"reason": "degenerate_occupation", "seg_start": 0}
        ),
        RegimeEventRecord(EVENT_SEGMENT_SKIPPED, {"reason": "fit_failed", "seg_start": 2}),
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


def test_segment_layout_runs_from_the_boundary_in_refit_steps():
    assert segment_layout(10, 4, 3) == [(4, 7), (7, 10)]
    assert segment_layout(4, 4, 3) == []


def test_from_row_drops_segments_and_rows_outside_the_panel():
    # two segments of 2 rows each over bar rows 2-3 (written) and 4-5 (degenerate); offset 2
    status = np.array([0.0, 0.0, 1.0, 1.0, 2.0, 2.0])
    events = [
        RegimeEventRecord(EVENT_CONVERGENCE, {"iters_used": 1, "n_iter_cap": 9, "seg_start": 0}),
        RegimeEventRecord(EVENT_CONVERGENCE, {"iters_used": 1, "n_iter_cap": 9, "seg_start": 2}),
        RegimeEventRecord(
            EVENT_SEGMENT_SKIPPED, {"reason": "degenerate_occupation", "seg_start": 2}
        ),
    ]
    whole = summarize_run(status, events)
    inside = summarize_run(status, events, from_row=4)
    assert (whole["segments"], whole["refused"], whole["written"]) == (2, 1, 2)
    assert (inside["segments"], inside["refused"], inside["modeled"], inside["written"]) == (
        1,
        1,
        2,
        0,
    )


def test_summarize_stored_matches_summarize_run_on_the_same_layout():
    timestamps = list(range(8))  # bar rows 0-7; observation j is row 2 + j; boundary 1, refit 2
    stored = {3, 4}  # the first segment (rows 3-4) is written, the second (rows 5-6) is not
    out = summarize_stored(timestamps, stored, n_obs=6, offset=2, boundary=1, refit=2)
    assert (out["segments"], out["refused"], out["modeled"], out["written"]) == (3, 2, 5, 2)
    inside = summarize_stored(timestamps, stored, 6, 2, 1, 2, from_row=5)
    assert (inside["segments"], inside["refused"]) == (2, 2)


def test_n_params_by_covariance_type():
    # K=3, d=2: means 6; covars full 9 / diag 6 / spherical 3 / tied 3; transmat 6; start 2
    assert _n_params(3, 2, "full") == 6 + 9 + 6 + 2
    assert _n_params(3, 2, "diag") == 6 + 6 + 6 + 2
    assert _n_params(3, 2, "spherical") == 6 + 3 + 6 + 2
    assert _n_params(3, 2, "tied") == 6 + 3 + 6 + 2


def _params(**over) -> HmmConfig:
    base = {
        "feature.hmm.n_components": 3,
        "feature.hmm.vol_window": 5,
        "feature.hmm.obs_momentum_window": 5,
        "feature.hmm.obs_vol_of_vol_window": 5,
        "feature.hmm.n_iter": 200,
        "alpha.hmm.random_state": 42,
        "feature.hmm.covariance_type": "diag",
        "feature.hmm.min_hold_bars": 2,
        "feature.hmm.full_cov_min_obs": 10_000,  # a tiny series stays diag, as in production
        "feature.hmm.min_state_occupation": 0.05,
        "feature.hmm.churn_window": 5,
        "feature.hmm.min_obs_factor": 10,
        "alpha.hmm.covariance_ridge": 1e-6,
        "alpha.hmm.momentum_vol_floor": 1e-8,
        "alpha.hmm_volatility.n_components": 2,
        "alpha.hmm_volatility.vol_window": 5,
        "alpha.hmm_volatility.vol_of_vol_window": 5,
        "alpha.hmm_volatility.covariance_type": "diag",
        **{
            f"alpha.hmm.walk_forward.{which}.{tf}": 500
            for which in ("refit_every_bars", "initial_warmup_bars")
            for tf in ("5m", "15m", "1h", "1d")
        },
    }
    base.update(over)
    return HmmConfig.from_values(base.get)


def _series(n: int = 600) -> dict:
    rng = np.random.default_rng(7)
    steps = rng.normal(0, 0.01, n)
    close = 100.0 * np.exp(np.cumsum(steps))
    return {"close": close, "volume": rng.uniform(1e6, 2e6, n), "timestamps": list(range(n))}


def test_bic_fit_record_winner_is_best_converged_restart_and_bic_formula():
    record = bic_fit_record(
        FAMILY_SPECS["trend"], _params(), _series(), k=3, restarts=2, block_rows=None
    )
    assert record["converged"] and len(record["attempts"]) == 2
    assert [a["seed"] for a in record["attempts"]] == [42, 43]  # restart 0 is the APR seed
    best = max((a for a in record["attempts"] if a["converged"]), key=lambda a: a["log_lik"])
    assert record["log_lik"] == best["log_lik"] and record["winner_seed"] == best["seed"]
    # the trend observation matrix has 5 columns; diag covars under 10k obs
    assert record["covariance_type"] == "diag" and record["n_params"] == _n_params(3, 5, "diag")
    assert record["bic"] == record["n_params"] * math.log(record["n_obs"]) - 2 * best["log_lik"]


def test_bic_fit_record_fits_the_volatility_family_at_k_above_its_vocab():
    # the volatility vocabulary supports only K=2/K=3 for labels; the BIC arm maps no labels
    record = bic_fit_record(
        FAMILY_SPECS["volatility"], _params(), _series(), k=6, restarts=1, block_rows=None
    )
    assert record["converged"] and record["n_params"] == _n_params(6, 2, "diag")


def test_bic_fit_record_short_series_is_an_error_not_a_crash():
    record = bic_fit_record(
        FAMILY_SPECS["trend"],
        _params(),
        {"close": np.full(4, 100.0), "volume": np.full(4, 1e6), "timestamps": list(range(4))},
        k=3,
        restarts=1,
        block_rows=None,
    )
    assert record["error"] == "insufficient_observations" and record["n_obs"] == 0


def _bic_record(symbol, k, bic, converged=True, family="trend", tf="1d"):
    return {
        "symbol": symbol,
        "tf": tf,
        "family": family,
        "k": k,
        "source": "bic",
        "restarts": 3,
        "n_obs": 5000,
        "converged": converged,
        "bic": bic,
        "log_lik": -bic,
    }


def test_bic_arm_summary_winners_mode_and_no_converged():
    records = [
        # lower BIC wins; A's winner is K=5, B's K=3, C's K=6 (its lower-BIC K=5 never
        # converged and cannot win); D converges nowhere
        _bic_record("A", 3, -30000.0),
        _bic_record("A", 4, -29500.0),
        _bic_record("A", 5, -31000.0),
        _bic_record("B", 3, -30000.0),
        _bic_record("B", 4, -29000.0),
        _bic_record("B", 5, -29900.0),
        _bic_record("C", 4, -50000.0),
        _bic_record("C", 5, -55000.0, converged=False),
        _bic_record("C", 6, -52000.0),
        _bic_record("D", 3, -1.0, converged=False),
        _bic_record("D", 4, -1.0, converged=False),
    ]
    arm = bic_arm_summary(records)[("trend", "1d")]
    assert arm["names"] == 4 and arm["no_converged"] == ["D"]
    assert arm["distribution"] == {3: 1, 5: 1, 6: 1}  # three-way tie: the mode is the smallest K
    assert arm["reference_k"] == 3
    assert [r["k"] for r in arm["rows"]] == [3, 4, 5, 6]
    assert arm["rows"][0]["converged"] == 2  # D's unconverged cells count in names, not converged


def test_summarize_reports_bic_arm_and_divergence(tmp_path, capsys):
    refusal = [
        {
            "symbol": s,
            "tf": "1d",
            "family": "trend",
            "k": k,
            "segments": 10,
            "refused": refused,
            "modeled": 100,
            "written": 80,
            "hit_cap": 0,
        }
        for s in "AB"
        for k, refused in ((3, 5), (4, 15))
    ]
    bic = [
        _bic_record(s, k, bic)
        for s in "AB"
        for k, bic in ((3, -30000.0), (4, -31000.0), (5, -32000.0), (6, -31500.0))
    ] + [
        _bic_record("A", 3, -30000.0, family="volatility")
    ]  # vol arm: no refusal pair
    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in refusal + bic) + "\n")
    _summarize([str(path)])
    out = capsys.readouterr().out
    assert "chosen K per timeframe: {'1d': 3}" in out
    assert "BIC arm trend 1d" in out and "BIC arm volatility 1d" in out
    assert "winners {5: 2}, no_converged 0, reference K=5" in out
    assert (
        "BIC vs refusal, trend 1d: reference K=5, winner K=3 (DIVERGENCE (583 disclosure))" in out
    )
