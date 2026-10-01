"""Append-only planning for FRED series (todo 480)."""

import json
from datetime import UTC, date, datetime

import pytest

from services.economic_series_writer import (
    BASIS_ASSUMED_LAG,
    BASIS_FETCH,
    parse_series_config,
    plan_rows,
)
from src.providers.fred import parse_observations
from src.providers.nyfed import FIELD_SUFFIX, SUFFIX_UNIT, parse_rate_records, series_unit

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def test_first_fetch_estimates_availability_from_the_lag():
    plan = plan_rows([(date(2008, 12, 4), 6.16)], {}, True, NOW, 1)
    (row,) = plan.rows
    # Thursday 2008-12-04 posts on Friday 12-05; available once that day has ended.
    assert row.available_at == datetime(2008, 12, 6, tzinfo=UTC)
    assert row.basis == BASIS_ASSUMED_LAG and not row.is_revision


def test_friday_observation_is_available_after_monday_ends():
    plan = plan_rows([(date(2026, 9, 25), 5.2)], {}, True, NOW, 1)  # a Friday
    assert plan.rows[0].available_at == datetime(2026, 9, 29, tzinfo=UTC)  # Tuesday 00:00


def test_first_fetch_never_claims_availability_in_the_future():
    plan = plan_rows([(date(2026, 10, 1), 5.2)], {}, True, NOW, 3)
    assert plan.rows[0].available_at == NOW


def test_later_new_day_is_stamped_with_the_fetch_time():
    plan = plan_rows([(date(2026, 9, 30), 5.2)], {}, False, NOW, 1)
    (row,) = plan.rows
    assert row.available_at == NOW and row.basis == BASIS_FETCH and not row.is_revision


def test_unchanged_day_appends_nothing():
    stored = {date(2026, 9, 30): 5.2}
    assert plan_rows([(date(2026, 9, 30), 5.2)], stored, False, NOW, 1).rows == []


def test_revised_day_appends_a_new_row():
    stored = {date(2026, 9, 30): 5.2}
    (row,) = plan_rows([(date(2026, 9, 30), 5.25)], stored, False, NOW, 1).rows
    assert row.is_revision and row.value == 5.25 and row.available_at == NOW


def test_days_fred_stopped_serving_are_counted_inside_the_span_only():
    stored = {date(2020, 1, 1): 1.0, date(2026, 9, 29): 5.0, date(2026, 9, 30): 5.1}
    fetched = [(date(2026, 9, 29), 5.0), (date(2026, 10, 1), 5.2)]
    plan = plan_rows(fetched, stored, False, NOW, 1)
    # 2020-01-01 is before the served span (kept, not counted); 09-30 is inside it and absent.
    assert plan.n_vanished == 1


def test_parse_observations_drops_missing_days_never_zero():
    payload = {
        "observations": [
            {"date": "2026-09-28", "value": "5.25"},
            {"date": "2026-09-27", "value": "."},
        ]
    }
    assert parse_observations(payload) == [(date(2026, 9, 28), 5.25)]


def test_parse_observations_rejects_a_payload_without_observations():
    with pytest.raises(ValueError):
        parse_observations({"error_code": 400, "error_message": "bad"})


def test_parse_observations_rejects_non_finite_values():
    with pytest.raises(ValueError):
        parse_observations({"observations": [{"date": "2026-09-28", "value": "nan"}]})


def test_series_config_requires_revision_and_consumer():
    ok = [{"series_id": "DGS10", "revision": "none", "consumer": "rate_level_screen"}]
    assert parse_series_config(json.dumps(ok)) == [{"source": "fred", **ok[0]}]
    with pytest.raises(ValueError):
        parse_series_config(json.dumps([{"series_id": "DGS10", "revision": "none"}]))
    with pytest.raises(ValueError):
        parse_series_config(json.dumps([{**ok[0], "revision": "sometimes"}]))
    with pytest.raises(ValueError):
        parse_series_config(json.dumps(ok + ok))


def test_series_config_checks_source_and_nyfed_rate_type():
    nyfed = {"source": "nyfed", "series_id": "SOFR", "revision": "revised", "consumer": "c"}
    assert parse_series_config(json.dumps([nyfed])) == [nyfed]
    with pytest.raises(ValueError):
        parse_series_config(json.dumps([{**nyfed, "series_id": "DGS10"}]))
    with pytest.raises(ValueError):
        parse_series_config(json.dumps([{**nyfed, "source": "bloomberg"}]))
    # the same id from two sources is two entries, not a duplicate
    fred = {**nyfed, "source": "fred"}
    assert len(parse_series_config(json.dumps([nyfed, fred]))) == 2


def _sofr(day, **fields):
    return {"type": "SOFR", "effectiveDate": day, "revisionIndicator": "", **fields}


def test_nyfed_records_expand_to_one_series_per_published_field():
    series = parse_rate_records(
        "SOFR",
        [
            _sofr("2026-09-29", percentRate=3.9, percentPercentile99=3.99, volumeInBillions=3230),
            _sofr("2026-09-30", percentRate=3.88),
        ],
    )
    assert series["NYFED_SOFR_RATE"] == [(date(2026, 9, 29), 3.9), (date(2026, 9, 30), 3.88)]
    assert series["NYFED_SOFR_P99"] == [(date(2026, 9, 29), 3.99)]
    # a field a record lacks is missing for that day, never zero
    assert series["NYFED_SOFR_VOLUME_BN"] == [(date(2026, 9, 29), 3230.0)]


def test_nyfed_records_reject_a_duplicate_day_or_foreign_type():
    with pytest.raises(ValueError):
        parse_rate_records("SOFR", [_sofr("2026-09-29", percentRate=3.9)] * 2)
    with pytest.raises(ValueError):
        parse_rate_records("EFFR", [_sofr("2026-09-29", percentRate=3.9)])


def test_nyfed_not_published_marker_is_missing_and_other_text_fails():
    series = parse_rate_records(
        "SOFR", [_sofr("2021-08-05", percentRate=0.05, percentPercentile1="NA")]
    )
    assert "NYFED_SOFR_P01" not in series and series["NYFED_SOFR_RATE"]
    with pytest.raises(ValueError):
        parse_rate_records("SOFR", [_sofr("2021-08-05", percentRate="oops")])


def test_every_nyfed_field_has_a_declared_unit():
    assert set(FIELD_SUFFIX.values()) == set(SUFFIX_UNIT)
    assert series_unit("NYFED_SOFR_VOLUME_BN") == "billions_usd"
    assert series_unit("NYFED_SOFRAI_INDEX") == "index_level"
    assert series_unit("NYFED_SOFRAI_AVG_30D") == "percent"
    assert series_unit("NYFED_EFFR_TARGET_FROM") == "percent"
