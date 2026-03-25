import random
from datetime import UTC, datetime

from src.persistence.logic.stream_merger import StreamMerger


def test_stream_merger_adversarial_fuzzing():
    """Adversarial Fuzzer: Randomly order and omit tiers to verify convergence."""

    for _ in range(100):  # Run 100 random scenarios
        merger = StreamMerger()
        sequence_id = f"ES:1m:{datetime.now(UTC).isoformat()}"
        all_tiers = list(merger.EXPECTED_TIERS)

        # Scenario: Random subset of tiers arrives in random order
        shuffled = all_tiers[:]
        random.shuffle(shuffled)

        # Randomly drop 0 to 3 tiers to simulate network loss
        drop_count = random.randint(0, 3)
        dropped = random.sample(shuffled, drop_count)
        arrivals = [t for t in shuffled if t not in dropped]

        # Ingest tiers
        final_record = None
        for tier in arrivals:
            result = merger.ingest(tier, sequence_id, {"data": tier})
            if result:
                final_record = result

        # Verify Invariants
        if drop_count == 0:
            assert final_record is not None, f"Failed to converge with full set: {all_tiers}"
            assert final_record["is_complete"] is True
            assert set(final_record["tiers"].keys()) == set(all_tiers)
        else:
            # Should not be complete, or should be caught by expiration logic
            assert final_record is None
            expired = merger.check_expired()
            assert any(e["sequence_id"] == sequence_id for e in expired)
            # Verify partial state audit is accurate
            audit = next(e for e in expired if e["sequence_id"] == sequence_id)
            assert set(audit["missing_tiers"]) == set(dropped)

    print("\n✅ StreamMerger adversarial logic verified via 100+ random scenarios.")
