"""/api/system/units joins services to their timers; /api/system/dlq counts recent DLQ traffic."""

from datetime import UTC, datetime

from src.api.routes import system


def test_units_join_each_service_to_the_timer_that_activates_it(client, monkeypatch):
    async def fake(*args):
        if args[0] == "list-units":
            return [
                {
                    "unit": "indicagent-a.service",
                    "active": "failed",
                    "sub": "failed",
                    "description": "A",
                },
                {
                    "unit": "indicagent-b.service",
                    "active": "active",
                    "sub": "running",
                    "description": "B",
                },
            ]
        return [
            {
                "unit": "indicagent-a.timer",
                "activates": "indicagent-a.service",
                "last": 1_700_000_000_000_000,
                "next": 0,
            }
        ]

    monkeypatch.setattr(system, "_systemctl_json", fake)
    body = client.get("/api/system/units").json()
    rows = {r["unit"]: r for r in body["rows"]}
    assert body["source"] == "systemd"
    assert rows["indicagent-a.service"]["timer"] == "indicagent-a.timer"
    assert rows["indicagent-a.service"]["last_run"].startswith("2023-11-14")
    assert rows["indicagent-a.service"]["next_run"] is None  # 0 means never
    assert rows["indicagent-b.service"]["timer"] is None


def test_dlq_reads_the_window_from_apr(client, mock_db):
    newest = datetime(2026, 10, 26, tzinfo=UTC)
    mock_db.execute_query.return_value = [
        {
            "dlq_topic": "bar.writer.dlq",
            "error_type": "ValueError",
            "events": 3,
            "newest": newest,
            "quarantined": 0,
        }
    ]
    body = client.get("/api/system/dlq").json()
    sql, since = mock_db.execute_query.call_args.args
    assert "FROM dlq_events" in sql
    assert (datetime.now(UTC) - since).days == 7
    assert body["meta"]["window_days"] == 7 and body["rows"][0]["events"] == 3
