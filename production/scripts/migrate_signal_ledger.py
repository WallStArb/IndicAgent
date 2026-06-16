#!/usr/bin/env python3
"""
migrate_signal_ledger.py -- Batch migration from signal_ledger to signal_events + trade_frames.

Copies all rows from the legacy signal_ledger monolith into the 3-table signal architecture
(signal_events + trade_frames) introduced in Phase 128-129.

Column mapping per 129-CONTEXT.md D-01 and D-02:
  - direction integer (1/-1) -> text ('long'/'short')
  - signal_ledger.stop_loss -> trade_frames.stop_price
  - signal_ledger.targets[0] -> trade_frames.target_price
  - stop architecture fields + shadow fields -> trade_frames.frame_details JSONB
  - signal_schema_version text -> int4 (NULLIF blank)
  - status: hardcoded 'expired' for all historical rows
  - entry_type: hardcoded 'at_close' (one entry_type per historical row)

Idempotency:
  - signal_events: ON CONFLICT (signal_id, ts) DO NOTHING (composite PK)
  - trade_frames: ON CONFLICT (frame_id) DO NOTHING (PK); frame_id is deterministic
    uuid5(NAMESPACE_DNS, f"{signal_id}:at_close") -- same UUID on every run

Usage:
  python production/scripts/migrate_signal_ledger.py
  python production/scripts/migrate_signal_ledger.py --dry-run
"""

import argparse
import json
import sys
import time
import uuid

import psycopg2
import psycopg2.extras

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

BATCH_SIZE = 10_000
PROGRESS_INTERVAL = 10  # Print progress every N batches (every 100K rows)

DB_PARAMS = {
    "host": "localhost",
    "dbname": "indicagent",
    "user": "postgres",
    "password": "postgres",
}

DIRECTION_MAP = {1: "long", -1: "short"}

# uuid5 namespace for deterministic frame_id generation
_FRAME_ID_NS = uuid.NAMESPACE_DNS


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def direction_to_text(direction_int):
    """Convert direction integer (1/-1) to text ('long'/'short')."""
    result = DIRECTION_MAP.get(direction_int)
    if result is None:
        raise ValueError(f"Unexpected direction value: {direction_int!r}")
    return result


def safe_float(value):
    """Cast numeric/Decimal to float, returning None if None."""
    if value is None:
        return None
    return float(value)


def make_frame_id(signal_id):
    """
    Generate a deterministic frame_id for the at_close entry_type.

    Uses uuid5 so the same signal_id always produces the same frame_id,
    making the migration fully idempotent across restarts.
    """
    return uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:at_close")


def parse_schema_version(value):
    """
    Convert signal_schema_version text to int4.

    Returns None for NULL, empty string, or non-numeric values.
    """
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def extract_target_price(targets, entry_price, stop_price):
    """
    Extract first element of targets JSONB array as float.

    Returns (target_price, r_multiple). Both may be None.
    """
    target_price = None
    if targets and isinstance(targets, list) and len(targets) > 0:
        try:
            target_price = float(targets[0])
        except (ValueError, TypeError):
            pass
    elif targets and isinstance(targets, dict):
        # Defensive: some rows may have targets as a dict with a 'price' key
        raw = targets.get("price") or targets.get("target")
        if raw is not None:
            try:
                target_price = float(raw)
            except (ValueError, TypeError):
                pass

    r_multiple = None
    if target_price is not None and entry_price is not None and stop_price is not None:
        denom = entry_price - stop_price
        if denom != 0:
            r_multiple = (target_price - entry_price) / denom

    return target_price, r_multiple


def build_frame_details(row):
    """
    Build the frame_details JSONB from stop architecture fields + shadow fields.

    Per ADR: all stop architecture columns and historical shadow data are
    archived to frame_details JSONB (Renaissance data retention principle:
    never drop data that could contain signal).

    None values are removed from the dict -- sparse dicts are cleaner and
    reduce JSONB storage.
    """
    details = {
        "stop_basis": row["stop_basis"],
        "stop_type_col": row["stop_type_col"],
        "structural_stop_distance_atr": safe_float(row["structural_stop_distance_atr"]),
        "adaptive_buffer_mult": safe_float(row["adaptive_buffer_mult"]),
        "stop_structure_type": row["stop_structure_type"],
        "stop_structure_age_bars": row["stop_structure_age_bars"],
        "chandelier_vol_source": row["chandelier_vol_source"],
        "trailing_stop_price": safe_float(row["trailing_stop_price"]),
        "trailing_stop_tightening_rate": safe_float(row["trailing_stop_tightening_rate"]),
        "entry_zone_low": safe_float(row["entry_zone_low"]),
        "entry_zone_high": safe_float(row["entry_zone_high"]),
        "shadow_tracking_start_ts": (
            row["shadow_tracking_start_ts"].isoformat() if row["shadow_tracking_start_ts"] else None
        ),
        "shadow_mae": safe_float(row["shadow_mae"]),
        "shadow_mfe": safe_float(row["shadow_mfe"]),
        "shadow_outcome": row["shadow_outcome"],
        "targets_raw": row["targets"],
    }
    # Remove None-valued keys for a cleaner sparse JSONB
    return {k: v for k, v in details.items() if v is not None}


# -------------------------------------------------------------------------
# SELECT query
# -------------------------------------------------------------------------

SELECT_SQL = """
SELECT
    signal_id,
    timestamp,
    symbol,
    timeframe,
    setup_plugin,
    direction,
    raw_confidence,
    calibrated_confidence,
    cis_score,
    weights_version,
    hmm_regime_at_fire,
    plugin_regime_type,
    garch_sigma_at_fire,
    is_shadow,
    is_backfill,
    signal_schema_version,
    ttl_bars,
    expires_at,
    signal_computed_at,
    feature_ts,
    was_selected,
    entry_price,
    stop_loss,
    targets,
    entry_zone_low,
    entry_zone_high,
    stop_basis,
    stop_type_col,
    structural_stop_distance_atr,
    adaptive_buffer_mult,
    stop_structure_type,
    stop_structure_age_bars,
    chandelier_vol_source,
    trailing_stop_price,
    trailing_stop_tightening_rate,
    shadow_tracking_start_ts,
    shadow_mae,
    shadow_mfe,
    shadow_outcome
FROM signal_ledger
ORDER BY timestamp ASC, signal_id ASC
LIMIT %s OFFSET %s
"""

# -------------------------------------------------------------------------
# INSERT queries
# -------------------------------------------------------------------------

SIGNAL_EVENTS_INSERT = """
INSERT INTO signal_events (
    signal_id,
    ts,
    symbol,
    tf,
    setup_plugin,
    direction,
    raw_confidence,
    calibrated_confidence,
    cis_score,
    weights_version,
    factor_scores,
    context_features,
    ctf_score,
    ctf_confirmed,
    zone_friction_score,
    hmm_regime_at_fire,
    plugin_regime_type,
    garch_sigma_at_fire,
    is_shadow,
    is_backfill,
    status,
    signal_schema_version,
    ttl_bars,
    expires_at,
    signal_computed_at,
    feature_ts,
    concurrent_signal_count,
    concurrent_plugins
) VALUES %s
ON CONFLICT (signal_id, ts) DO NOTHING
"""

TRADE_FRAMES_INSERT = """
INSERT INTO trade_frames (
    frame_id,
    signal_id,
    signal_ts,
    entry_type,
    direction,
    entry_price,
    stop_price,
    target_price,
    r_multiple,
    was_selected,
    ttl_bars,
    expires_at,
    frame_details
) VALUES %s
ON CONFLICT (frame_id) DO NOTHING
"""


# -------------------------------------------------------------------------
# Batch processing
# -------------------------------------------------------------------------


def process_batch(rows):
    """
    Convert raw signal_ledger rows into (signal_events_rows, trade_frames_rows).

    Returns (se_rows, tf_rows) as lists of tuples for execute_values().
    """
    se_rows = []
    tf_rows = []

    for row in rows:
        signal_id = str(row["signal_id"])
        ts = row["timestamp"]
        direction = direction_to_text(row["direction"])

        # --- signal_events row ---
        raw_confidence = row["raw_confidence"]
        if raw_confidence is None:
            # raw_confidence is NOT NULL in signal_events; use 0.0 as sentinel
            # for rows that predate the confidence field
            raw_confidence = 0.0

        se_rows.append(
            (
                signal_id,
                ts,
                row["symbol"],
                row["timeframe"],
                row["setup_plugin"],
                direction,
                raw_confidence,
                row["calibrated_confidence"],
                row["cis_score"],
                row["weights_version"],
                None,  # factor_scores -- not in signal_ledger (was bucket_scores, not mapped)
                None,  # context_features -- not in signal_ledger
                None,  # ctf_score -- not in signal_ledger
                None,  # ctf_confirmed -- not in signal_ledger
                None,  # zone_friction_score -- not in signal_ledger
                row["hmm_regime_at_fire"],
                row["plugin_regime_type"],
                row["garch_sigma_at_fire"],
                row["is_shadow"],
                row["is_backfill"],
                "expired",  # status -- all historical rows are past TTL
                parse_schema_version(row["signal_schema_version"]),
                row["ttl_bars"],
                row["expires_at"],
                row["signal_computed_at"],
                row["feature_ts"],
                None,  # concurrent_signal_count -- Phase 130 writer populates going forward
                None,  # concurrent_plugins -- Phase 130 writer populates going forward
            )
        )

        # --- trade_frames row ---
        entry_price = safe_float(row["entry_price"])
        stop_price = safe_float(row["stop_loss"])
        target_price, r_multiple = extract_target_price(row["targets"], entry_price, stop_price)
        frame_details = build_frame_details(row)
        frame_id = str(make_frame_id(signal_id))

        tf_rows.append(
            (
                frame_id,
                signal_id,
                ts,  # signal_ts -- FK anchor for hypertable composite PK
                "at_close",  # entry_type -- hardcoded; historical rows had one entry_type
                direction,
                entry_price,
                stop_price,
                target_price,
                r_multiple,
                row["was_selected"],
                row["ttl_bars"],
                row["expires_at"],
                json.dumps(frame_details) if frame_details else None,
            )
        )

    return se_rows, tf_rows


def migrate(conn, total_rows, dry_run=False):
    """Run the batched migration. Returns (migrated_count, failed_count)."""
    migrated = 0
    failed = 0
    num_batches = (total_rows + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Batch size: {BATCH_SIZE:,}  batches: {num_batches}")

    for batch_num in range(num_batches):
        offset = batch_num * BATCH_SIZE

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(SELECT_SQL, (BATCH_SIZE, offset))
                rows = cur.fetchall()

            if not rows:
                break

            se_rows, tf_rows = process_batch(rows)

            if not dry_run:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur, SIGNAL_EVENTS_INSERT, se_rows, template=None, page_size=1000
                    )
                    psycopg2.extras.execute_values(
                        cur, TRADE_FRAMES_INSERT, tf_rows, template=None, page_size=1000
                    )
                conn.commit()

            migrated += len(rows)

            if (batch_num + 1) % PROGRESS_INTERVAL == 0 or batch_num == 0:
                pct = migrated / total_rows * 100
                print(
                    f"  [{pct:5.1f}%] batch {batch_num + 1}/{num_batches} -- {migrated:,} rows processed"
                )

        except Exception as error:
            # Log the batch range and error; rollback; continue
            batch_start = offset
            batch_end = offset + BATCH_SIZE - 1
            print(
                f"  ERROR in batch {batch_num + 1} (offsets {batch_start}-{batch_end}): {error}",
                file=sys.stderr,
            )
            try:
                conn.rollback()
            except Exception:
                pass
            failed += min(BATCH_SIZE, total_rows - offset)

    return migrated, failed


# -------------------------------------------------------------------------
# Dry-run sample output
# -------------------------------------------------------------------------


def print_sample_mapping(conn):
    """Fetch and display first row mapping for dry-run validation."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(SELECT_SQL, (1, 0))
        row = cur.fetchone()

    if not row:
        print("  (no rows in signal_ledger)")
        return

    signal_id = str(row["signal_id"])
    direction = direction_to_text(row["direction"])
    entry_price = safe_float(row["entry_price"])
    stop_price = safe_float(row["stop_loss"])
    target_price, r_multiple = extract_target_price(row["targets"], entry_price, stop_price)
    frame_id = str(make_frame_id(signal_id))
    schema_ver = parse_schema_version(row["signal_schema_version"])

    print("Sample mapping (first row):")
    print(f"  signal_id:            {signal_id}")
    print(f"  ts:                   {row['timestamp']}")
    print(f"  symbol:               {row['symbol']}")
    print(f"  tf:                   {row['timeframe']}")
    print(f"  direction (int->text):{row['direction']} -> {direction!r}")
    print("  entry_type:           at_close  (hardcoded)")
    print("  status:               expired  (hardcoded)")
    print(f"  entry_price:          {entry_price}")
    print(f"  stop_price:           {stop_price}  (was stop_loss)")
    print(f"  target_price:         {target_price}  (was targets[0])")
    print(f"  r_multiple:           {r_multiple}")
    print(f"  signal_schema_version:{row['signal_schema_version']!r} -> {schema_ver}")
    print(f"  frame_id (det.):      {frame_id}")
    frame_details = build_frame_details(row)
    print(f"  frame_details keys:   {list(frame_details.keys())}")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Migrate signal_ledger rows to signal_events + trade_frames."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows and print sample mapping without writing any data.",
    )
    args = parser.parse_args()

    print("migrate_signal_ledger.py" + (" -- dry-run mode" if args.dry_run else ""))
    print()

    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM signal_ledger")
            total_rows = cur.fetchone()[0]

        print(f"Total rows in signal_ledger: {total_rows:,}")

        if args.dry_run:
            print_sample_mapping(conn)
            print()
            print("Dry-run complete. No rows written.")
            return

        # Live migration
        print()
        start_time = time.monotonic()
        migrated, failed = migrate(conn, total_rows, dry_run=False)
        elapsed = time.monotonic() - start_time

        print()
        print(f"Migration complete in {elapsed:.1f}s")
        print(f"  Rows migrated: {migrated:,}")
        if failed:
            print(f"  Rows failed:   {failed:,}", file=sys.stderr)
        else:
            print("  Rows failed:   0")

        # Verify counts
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM signal_events")
            se_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM trade_frames")
            tf_count = cur.fetchone()[0]

        print(f"  signal_events rows:  {se_count:,}")
        print(f"  trade_frames rows:   {tf_count:,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
