"""Every DLQ topic has a consumer: dlq_writer subscribes to each topic_*_dlq builder, and the
provisioning script creates each one. A DLQ nobody reads is a black hole (a feature-vector DLQ
went unread this way until todo 509); a builder nobody publishes to belongs deleted."""

import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import src.core.stream_keys as stream_keys
from services.dlq_writer import DLQWriter

REPO = Path(__file__).resolve().parents[3]


_DLQ_BUILDERS = {
    name: fn
    for name, fn in inspect.getmembers(stream_keys, inspect.isfunction)
    if name.startswith("topic_") and name.endswith("_dlq")
}


def _dlq_topics(env: str) -> set[str]:
    return {fn(env) for fn in _DLQ_BUILDERS.values()}


def test_dlq_writer_reads_every_dlq_topic():
    stub = SimpleNamespace(settings=SimpleNamespace(env_name="dev"))
    assert set(DLQWriter._build_topics(stub)) == _dlq_topics("dev")  # type: ignore[arg-type]


def test_the_provisioning_script_creates_every_dlq_topic():
    script = (REPO / "scripts/infrastructure/kafka/infrastructure_ensure_topics.sh").read_text()
    block = re.search(r"DLQ_TOPICS=\(\n(.*?)\n\)", script, re.S)
    assert block
    provisioned = {line.strip() for line in block.group(1).splitlines() if line.strip()}
    assert provisioned == _dlq_topics("")


def test_dlq_topics_take_the_env_prefix():
    assert stream_keys.topic_bar_writer_dlq("dev") == "dev.bar.writer.dlq"
    assert stream_keys.topic_bar_writer_dlq("") == "bar.writer.dlq"


def test_no_dlq_topic_is_in_the_python_topic_specs():
    """infrastructure_ensure_topics.sh owns DLQ retention (7 days); a DLQ row in the Python specs
    would let infrastructure_enforce_topic_retention.py cut it back to the 1-day buffer tier."""
    from scripts.infrastructure.setup.infrastructure_init_kafka_topics import get_topic_specs

    assert not {suffix for suffix, *_ in get_topic_specs(["ibkr"])} & _dlq_topics("")


def test_every_dlq_topic_has_a_producer():
    """A DLQ builder nothing publishes to is dead weight in the consumer and the provisioning."""
    producers = [
        path
        for root in ("services", "src")
        for path in (REPO / root).rglob("*.py")
        if path.name not in {"stream_keys.py", "dlq_writer.py"}
    ]
    sources = [path.read_text() for path in producers]
    orphans = [b for b in _DLQ_BUILDERS if not any(re.search(rf"\b{b}\(", src) for src in sources)]
    assert not orphans, f"DLQ builders with no producer: {orphans}"
