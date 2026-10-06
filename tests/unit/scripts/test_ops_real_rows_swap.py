"""Real-rows swap preflight (todo 462 step 6, plan 185-25): refusal paths, digest comparison,
consumer audit, disk plan and gates, all on fixtures. No database, no live tables."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.ops.bars import ops_real_rows_swap as swap

# --- refusal paths ------------------------------------------------------------------------------


def test_no_writers_means_no_blockers():
    assert swap.writer_blockers(swap.WriterState()) == []
    swap.refuse_if_writers(swap.WriterState())  # does not raise


@pytest.mark.parametrize(
    ("state", "fragment"),
    [
        (
            swap.WriterState(lock_holders=("488548 lease:ibkr_history_stream:bulk:hp:46",)),
            "lock held",
        ),
        (swap.WriterState(processes=("123 bar_derivation.py",)), "writer process"),
        (
            swap.WriterState(active_units=("indicagent-nightly-backfill.service",)),
            "writer unit active",
        ),
        (
            swap.WriterState(write_locks=("77 RowExclusiveLock market_data_ohlcv",)),
            "write lock",
        ),
    ],
)
def test_any_writer_refuses(state, fragment):
    assert any(fragment in b for b in swap.writer_blockers(state))
    with pytest.raises(swap.SwapRefused, match=fragment):
        swap.refuse_if_writers(state)


def test_verify_refuses_before_reading_while_a_writer_runs(monkeypatch):
    held = swap.WriterState(lock_holders=("1 lease:ibkr_history_stream:bulk:x:46",))
    monkeypatch.setattr(swap, "load_writer_state", lambda conn, *a, **k: held)

    class _NoReads:
        def cursor(self):  # pragma: no cover - reaching it is the failure
            raise AssertionError("verify read the table while a writer held the lease")

        def execute(self, *_a):  # pragma: no cover
            raise AssertionError("verify ran a statement while a writer held the lease")

    with pytest.raises(swap.SwapRefused):
        swap.verify(_NoReads())


def test_writer_processes_match_argv_basenames_only():
    cmdlines = {
        10: ["/bin/bash", "logs/backfill_ops/intraday_htf_lane.sh", "htf_all", "46"],
        11: [".venv/bin/python", "-u", "services/bar_derivation.py", "--apply"],
        # a shell whose command string only mentions the names must not match
        12: ["/bin/bash", "-c", "ps -eo args | grep bar_derivation.py intraday_chain.sh"],
        13: ["/usr/bin/python3", "services/feature_vector_pipeline.py"],
        14: [".venv/bin/python", "scripts/ops/bars/ops_real_rows_swap.py"],
    }
    found = swap.writer_processes(cmdlines, self_pid=14)
    assert found == ["10 intraday_htf_lane.sh", "11 bar_derivation.py"]


def test_writer_processes_skip_self():
    assert swap.writer_processes({5: ["python", "bar_writer.py"]}, self_pid=5) == []


def test_advisory_key_parts_match_the_live_lease_key():
    # The ibkr_history_stream lease measured live on 2026-10-06 in pg_locks.
    assert swap.advisory_key_parts("ibkr_history_stream") == (4163975343, 2061137787)


# --- digest comparison --------------------------------------------------------------------------


def _digests(**series):
    return {tuple(k.split("__")): v for k, v in series.items()}


def test_identical_digests_pass():
    old = _digests(SPY__5m=(100, "a"), SPY__1d=(20, "b"), AAPL__5m=(90, "c"))
    result = swap.compare_digests(old, dict(old))
    assert result.ok
    assert result.n_compared == 3


def test_count_mismatch_fails():
    old = _digests(SPY__5m=(100, "a"))
    new = _digests(SPY__5m=(99, "a"))
    result = swap.compare_digests(old, new)
    assert not result.ok
    assert result.count_mismatch == [("SPY", "5m", 100, 99)]


def test_same_count_different_content_fails():
    old = _digests(SPY__5m=(100, "a"))
    new = _digests(SPY__5m=(100, "z"))
    result = swap.compare_digests(old, new)
    assert not result.ok
    assert result.digest_mismatch == [("SPY", "5m")]


def test_series_lost_or_gained_in_the_copy_fails():
    old = _digests(SPY__5m=(100, "a"), CCJ__15m=(5, "q"))
    new = _digests(SPY__5m=(100, "a"), XYZ__1h=(1, "r"))
    result = swap.compare_digests(old, new)
    assert not result.ok
    assert result.missing_in_new == [("CCJ", "15m")]
    assert result.extra_in_new == [("XYZ", "1h")]


def test_digest_sql_keeps_null_source_rows_and_covers_every_column():
    for statement in (swap._OLD_DIGEST_SQL, swap._NEW_DIGEST_SQL):
        assert "source IS DISTINCT FROM 'synthetic_fill'" in statement
        assert "<> 'synthetic_fill'" not in statement
        for column in swap.DIGEST_COLUMNS:
            assert column in statement
    assert "FROM market_data_ohlcv\n" in swap._OLD_DIGEST_SQL
    assert "FROM market_data_ohlcv_new\n" in swap._NEW_DIGEST_SQL


def test_digest_column_check_blocks_on_any_drift():
    live = [*swap.KEY_COLUMNS, *swap.DIGEST_COLUMNS]
    assert swap.digest_column_blockers(live) == []
    assert "not covered" in swap.digest_column_blockers([*live, "vwap"])[0]
    assert "missing" in swap.digest_column_blockers([c for c in live if c != "base"])[0]


# --- measurement and disk ------------------------------------------------------------------------


def _chunks():
    return [
        swap.ChunkInfo("_ti", "c1", True, total_bytes=100, before_bytes=1000, after_bytes=100),
        swap.ChunkInfo("_ti", "c2", False, total_bytes=500, before_bytes=None, after_bytes=None),
    ]


def _counts():
    return {
        "c1": {
            "5m": swap.TfCount(total=80, synthetic=60, null_source=1, synthetic_tradeable=0),
            "1d": swap.TfCount(total=20, synthetic=5, null_source=0, synthetic_tradeable=0),
        },
        "c2": {"5m": swap.TfCount(total=50, synthetic=0, null_source=0, synthetic_tradeable=0)},
    }


def test_summarize_per_timeframe():
    summary = swap.summarize(_chunks(), _counts())
    assert list(summary) == ["1d", "5m"]
    s5 = summary["5m"]
    assert (s5.total, s5.synthetic, s5.real, s5.null_source) == (130, 60, 70, 1)
    assert s5.chunks == 2
    assert (s5.rows_in_compressed_chunks, s5.rows_in_uncompressed_chunks) == (80, 50)
    assert s5.est_compressed_bytes == pytest.approx(80.0)  # 100 bytes x 80/100
    assert s5.est_uncompressed_bytes == pytest.approx(800.0 + 500.0)
    assert s5.est_real_uncompressed_bytes == pytest.approx(1000 * 20 / 100 + 500.0)
    s1 = summary["1d"]
    assert (s1.total, s1.real, s1.chunks) == (20, 15, 1)


def test_disk_plan_uses_real_rows_uncompressed_times_margin():
    summary = swap.summarize(_chunks(), _counts())
    peak = 1000 * (20 + 15) / 100 + 500  # 850
    plan = swap.disk_plan(summary, free_bytes=2000, margin=2.0)
    assert plan.copy_peak_bytes == pytest.approx(peak)
    assert plan.required_bytes == pytest.approx(2 * peak)
    assert plan.ok
    assert not swap.disk_plan(summary, free_bytes=1000, margin=2.0).ok


def test_disk_margin_below_one_is_refused():
    with pytest.raises(ValueError):
        swap.disk_plan({}, free_bytes=1, margin=0.5)


def test_synthetic_rows_with_volume_block_the_swap():
    counts = _counts()
    counts["c2"]["5m"] = swap.TfCount(total=50, synthetic=3, null_source=0, synthetic_tradeable=2)
    blockers = swap.tradeable_blockers(swap.summarize(_chunks(), counts))
    assert blockers == ["5m: 2 synthetic_fill rows with volume > 0"]
    assert swap.tradeable_blockers(swap.summarize(_chunks(), _counts())) == []


# --- masked-slot gate --------------------------------------------------------------------------

_NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def _fact(tf, value=0.0, passed=True, age_h=6):
    return swap.MaskedFact(tf, value, passed, _NOW - timedelta(hours=age_h))


def test_masked_gate_passes_on_fresh_zero_facts():
    facts = {"15m": _fact("15m"), "1h": _fact("1h")}
    assert swap.masked_gate_blockers(facts, _NOW, timedelta(hours=48)) == []


def test_masked_gate_blocks_missing_nonzero_and_stale():
    facts = {"15m": _fact("15m", value=12.0, passed=False)}
    blockers = swap.masked_gate_blockers(facts, _NOW, timedelta(hours=48))
    assert any("15m: 12" in b for b in blockers)
    assert any("1h: no D7 fact" in b for b in blockers)
    stale = {"15m": _fact("15m", age_h=72), "1h": _fact("1h")}
    assert "stale" in swap.masked_gate_blockers(stale, _NOW, timedelta(hours=48))[0]


# --- consumer audit ----------------------------------------------------------------------------


def test_every_allow_listed_reader_has_a_verdict():
    allow_list = swap.load_allow_list()
    assert set(allow_list) == set(swap.CONSUMER_VERDICTS), (
        "the boundary allow-list and CONSUMER_VERDICTS drifted apart: record a verdict for "
        "each new raw reader, drop the verdict of each removed one"
    )


def test_unknown_reader_blocks():
    rows, blockers = swap.consumer_audit(["services/new_reader.py"], {}, verdicts={})
    assert rows[0]["category"] == "unknown"
    assert blockers == ["consumer services/new_reader.py: no verdict recorded"]


def test_contiguous_reader_blocks_regardless_of_counts():
    verdicts = {"a.py": swap.ConsumerVerdict(swap.CONTIGUOUS, "needs the grid")}
    _, blockers = swap.consumer_audit(["a.py"], {}, verdicts=verdicts)
    assert blockers == ["consumer a.py: contiguous"]


def test_placeholder_coverage_blocks_only_where_synthetic_rows_remain():
    verdicts = {"g.py": swap.ConsumerVerdict(swap.PLACEHOLDER_COVERAGE, "gaps", ("5m", "1m"))}
    rows, blockers = swap.consumer_audit(["g.py"], {"5m": 10, "1m": 0}, verdicts=verdicts)
    assert blockers == ["consumer g.py: placeholder_coverage on 5m"]
    assert rows[0]["timeframes_with_synthetic"] == ["5m"]
    _, clear = swap.consumer_audit(["g.py"], {"5m": 0, "1d": 99}, verdicts=verdicts)
    assert clear == []


def test_dead_and_real_rows_readers_never_block():
    verdicts = {
        "d.py": swap.ConsumerVerdict(swap.DEAD, "archived"),
        "r.py": swap.ConsumerVerdict(swap.REAL_ROWS, "counts"),
    }
    _, blockers = swap.consumer_audit(["d.py", "r.py"], {"5m": 10}, verdicts=verdicts)
    assert blockers == []


def test_load_allow_list_parses_without_importing(tmp_path: Path):
    source = tmp_path / "boundary.py"
    source.write_text('X = 1\n_ALLOW_LIST: dict[str, str] = {\n    "a.py": ("one " "two"),\n}\n')
    assert swap.load_allow_list(source) == {"a.py": "one two"}
    (tmp_path / "empty.py").write_text("Y = 2\n")
    with pytest.raises(ValueError):
        swap.load_allow_list(tmp_path / "empty.py")


# --- APR ---------------------------------------------------------------------------------------


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, *_a):
        return None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cursor(self._rows)


def test_apr_falls_back_to_defaults_with_provenance():
    values, provenance = swap.load_apr(_Conn([(swap.APR_DISK_MARGIN, "1.5")]))
    assert values[swap.APR_DISK_MARGIN] == 1.5
    assert provenance[swap.APR_DISK_MARGIN] == "apr"
    assert values[swap.APR_STATEMENT_TIMEOUT_S] == swap.APR_DEFAULTS[swap.APR_STATEMENT_TIMEOUT_S]
    assert provenance[swap.APR_STATEMENT_TIMEOUT_S] == "default"


def test_apr_seed_migration_matches_the_defaults():
    migration = Path(__file__).resolve().parents[3] / (
        "production/migrations/439_market_data_ohlcv_real_rows_swap.sql"
    )
    text = migration.read_text()
    for key, default in swap.APR_DEFAULTS.items():
        assert f"'{key}'" in text
        assert f"('{key}', '{default:g}'" in text


# --- write path: state -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tables", "state"),
    [
        ({"market_data_ohlcv": False}, swap.ABSENT),
        ({"market_data_ohlcv": False, "market_data_ohlcv_new": True}, swap.PRE),
        ({"market_data_ohlcv": True, "market_data_ohlcv_old": False}, swap.SWAPPED),
        ({"market_data_ohlcv": True}, swap.DONE),
        # anything else refuses every step
        ({"market_data_ohlcv": False, "market_data_ohlcv_new": False}, swap.INCONSISTENT),
        ({"market_data_ohlcv": True, "market_data_ohlcv_new": True}, swap.INCONSISTENT),
        ({"market_data_ohlcv_new": True}, swap.INCONSISTENT),
        (
            {
                "market_data_ohlcv": True,
                "market_data_ohlcv_new": True,
                "market_data_ohlcv_old": False,
            },
            swap.INCONSISTENT,
        ),
        ({}, swap.INCONSISTENT),
    ],
)
def test_classify_state(tables, state):
    assert swap.classify_state(tables) == state


# --- write path: copy windows ------------------------------------------------------------------


def test_chunk_windows_align_to_the_epoch_grid():
    # The live 90-day chunk 2026-09-04 .. 2026-12-03 sits on the Unix-epoch grid.
    lo = datetime(2026, 9, 20, tzinfo=UTC)
    hi = datetime(2026, 12, 10, tzinfo=UTC)
    windows = swap.chunk_windows(lo, hi, timedelta(days=90))
    assert [w.start for w in windows] == [
        datetime(2026, 9, 4, tzinfo=UTC),
        datetime(2026, 12, 3, tzinfo=UTC),
    ]
    assert all(w.end - w.start == timedelta(days=90) for w in windows)
    with pytest.raises(ValueError):
        swap.chunk_windows(lo, hi, timedelta(0))


def test_window_chunk_refuses_a_misaligned_grid():
    w = swap.Window(datetime(2026, 9, 4, tzinfo=UTC), datetime(2026, 12, 3, tzinfo=UTC))
    assert swap.window_chunk([], w) is None
    exact = swap.ChunkRange("_ti", "c", w.start, w.end, False)
    assert swap.window_chunk([exact], w) is exact
    shifted = swap.ChunkRange("_ti", "c", w.start + timedelta(days=1), w.end, False)
    with pytest.raises(swap.SwapAborted, match="misaligned"):
        swap.window_chunk([shifted], w)
    with pytest.raises(swap.SwapAborted):
        swap.window_chunk([exact, exact], w)


def test_copy_sql_moves_every_column_and_keeps_null_source_rows():
    for column in swap.COPY_COLUMNS:
        assert column in swap._COPY_WINDOW_SQL
    assert "INSERT INTO market_data_ohlcv_new" in swap._COPY_WINDOW_SQL
    assert "FROM market_data_ohlcv\n" in swap._COPY_WINDOW_SQL
    assert "source IS DISTINCT FROM 'synthetic_fill'" in swap._COPY_WINDOW_SQL
    assert "DELETE FROM market_data_ohlcv_new " in swap._CLEAR_WINDOW_SQL


def test_count_differences():
    original = {"5m": swap.TfCount(100, 70, 0, 0), "1d": swap.TfCount(10, 0, 0, 0)}
    assert (
        swap.count_differences(
            original, {"5m": swap.TfCount(30, 0, 0, 0), "1d": swap.TfCount(10, 0, 0, 0)}
        )
        == []
    )
    diffs = swap.count_differences(original, {"5m": swap.TfCount(31, 1, 0, 0)})
    assert any("synthetic_fill" in d for d in diffs)
    assert any(d.startswith("5m: rebuilt 31") for d in diffs)
    assert any(d.startswith("1d: rebuilt 0") for d in diffs)


# --- write path: exchange ----------------------------------------------------------------------


def test_plan_index_renames_both_directions():
    live = ["idx_ohlcv_symbol_tf_time", "market_data_ohlcv_pkey_idx"]
    incoming = [n + swap.SUFFIX_REBUILT for n in live]
    out, into = swap.plan_index_renames(live, incoming, swap.SUFFIX_ORIGINAL, swap.SUFFIX_REBUILT)
    assert out == [(n, n + swap.SUFFIX_ORIGINAL) for n in live]
    assert into == [(n + swap.SUFFIX_REBUILT, n) for n in live]
    with pytest.raises(swap.SwapAborted, match="index sets differ"):
        swap.plan_index_renames(live, incoming[:1], swap.SUFFIX_ORIGINAL, swap.SUFFIX_REBUILT)
    with pytest.raises(swap.SwapAborted, match="out of pattern"):
        swap.plan_index_renames(live, live, swap.SUFFIX_ORIGINAL, swap.SUFFIX_REBUILT)


def _shape(**over):
    base = dict(
        columns=(("timestamp", "timestamp with time zone", True),),
        constraints=(("market_data_ohlcv_timestamp_not_null", 'NOT NULL "timestamp"'),),
        indexes=(("market_data_ohlcv_pkey_idx", "UNIQUE btree (...)"),),
        dimensions=(("timestamp", "timestamp with time zone", "Time", "90 days", "", ""),),
        columnstore=("symbol,timeframe", '"timestamp"', "", "[]"),
        acl=(("bar_derivation_writer", "SELECT"),),
        reloptions=("autovacuum_vacuum_scale_factor=0.05",),
        owner="postgres",
    )
    base.update(over)
    return swap.TableShape(**base)


def test_shape_differences_name_each_drift():
    assert swap.shape_differences(_shape(), _shape()) == []
    diffs = swap.shape_differences(_shape(), _shape(acl=(), reloptions=()))
    assert [d.split(":")[0] for d in diffs] == ["acl", "reloptions"]


def test_index_names_compare_without_swap_suffixes():
    assert swap.index_base("market_data_ohlcv_pkey_idx_rebuilt") == "market_data_ohlcv_pkey_idx"
    assert swap.index_base("idx_ohlcv_symbol_tf_time_original") == "idx_ohlcv_symbol_tf_time"
    a = swap.index_signature(True, "CREATE UNIQUE INDEX a ON public.t USING btree (x)")
    b = swap.index_signature(True, "CREATE UNIQUE INDEX b ON public.u USING btree (x)")
    assert a == b == "UNIQUE btree (x)"


def test_policy_differences():
    live = [swap.Policy(2, "30 days", "12:00:00", True, "{}")]
    kept = [swap.Policy(1, "30 days", "12:00:00", False, "{}")]
    assert swap.policy_differences(live, kept) == []
    assert swap.policy_differences(live, [swap.Policy(1, "30 days", "12:00:00", True, "{}")])
    assert swap.policy_differences([], kept)
    assert swap.policy_differences(live, [swap.Policy(1, "7 days", "12:00:00", False, "{x}")])


# --- write path: post-swap checks --------------------------------------------------------------

_TRADEABLE_DEF = """ SELECT "timestamp" FROM market_data_ohlcv WHERE volume > 0 AND NOT (EXISTS (
 SELECT 1 FROM bar_quality_flag q WHERE q.symbol = market_data_ohlcv.symbol));"""


def test_rebind_view_sql_rewrites_every_whole_word_reference():
    out = swap.rebind_view_sql(_TRADEABLE_DEF, "market_data_ohlcv_old")
    assert out.count("market_data_ohlcv_old") == 2
    assert not out.endswith(";")
    assert "bar_quality_flag" in out


def test_real_rows_view_sql_shadows_the_table_with_a_cte():
    out = swap.real_rows_view_sql(_TRADEABLE_DEF, "market_data_ohlcv_old")
    assert out.startswith(
        "WITH market_data_ohlcv AS (SELECT * FROM market_data_ohlcv_old "
        "WHERE source IS DISTINCT FROM 'synthetic_fill') "
    )
    assert "market_data_ohlcv.symbol" in out  # qualified references resolve to the CTE


def test_view_blockers():
    live = {"5m": 10}
    # placeholders leave a grid view: allowed, as long as the real rows match
    assert swap.view_blockers("public.market_data_5m", live, {"5m": 10}, {"5m": 40}) == []
    assert swap.view_blockers("public.market_data_5m", live, {"5m": 11}, {"5m": 40})
    # the tradeable view must not change at all
    name = "public.market_data_ohlcv_tradeable"
    assert swap.view_blockers(name, live, {"5m": 10}, {"5m": 10}) == []
    assert "changed" in swap.view_blockers(name, live, {"5m": 10}, {"5m": 12})[0]


# --- write path: gates and CLI -----------------------------------------------------------------


def test_accept_placeholder_coverage_drops_only_those_blockers():
    consumers = [
        {"path": "g.py", "category": swap.PLACEHOLDER_COVERAGE, "blocks": True},
        {"path": "c.py", "category": swap.CONTIGUOUS, "blocks": True},
    ]
    blockers = [
        "consumer g.py: placeholder_coverage on 5m",
        "consumer c.py: contiguous",
        "lock held: 1 lease",
    ]
    kept, accepted = swap.accept_placeholder_coverage(consumers, blockers, accept=True)
    assert accepted == ["consumer g.py: placeholder_coverage on 5m"]
    assert kept == ["consumer c.py: contiguous", "lock held: 1 lease"]
    assert swap.accept_placeholder_coverage(consumers, blockers, accept=False) == (blockers, [])
    assert swap.accept_placeholder_coverage([], blockers, accept=True) == (blockers, [])


def test_cli_modes_are_exclusive():
    assert swap._mode(swap._parse_args([])) == "dry_run"
    assert swap._mode(swap._parse_args(["--drop-old"])) == "drop_old"
    with pytest.raises(SystemExit):
        swap._parse_args(["--copy", "--swap"])
