"""Todo 674 (commit R2): the research member path takes a pass-through's reach from the registry,
refuses the pass-throughs of a path-dependent builder, and refuses a pass-through whose reach is a
daily-bar definition on a source that is not daily. A pass-through admitted as memoryless would
pass any certificate bound, mask no warmup and understate the E17 memory L."""

from __future__ import annotations

import pytest

from src.intelligence.features.contract.registry import default_registry
from src.intelligence.research.feature_inputs import FeatureInputRefused, column_memory_bars
from tests.unit.intelligence.test_feature_memory_reach import BUILDER_FIRST_ROW, CONFIG, MARKED


@pytest.mark.parametrize("column", sorted(BUILDER_FIRST_ROW))
def test_a_finite_pass_through_member_reaches_its_builder_window(column: str) -> None:
    assert column_memory_bars(column, CONFIG, default_registry()) == BUILDER_FIRST_ROW[column](
        CONFIG
    )


@pytest.mark.parametrize("column", sorted(MARKED))
@pytest.mark.parametrize("tf", ["1d", "1h"])
def test_a_pass_through_of_a_path_dependent_builder_is_refused(column: str, tf: str) -> None:
    with pytest.raises(FeatureInputRefused, match="path-dependent builder"):
        column_memory_bars(column, CONFIG, default_registry(), tf)


@pytest.mark.parametrize("column", sorted(BUILDER_FIRST_ROW))
@pytest.mark.parametrize("tf", ["1h", "15m", "5m"])
def test_a_daily_defined_pass_through_is_refused_on_an_intraday_source(
    column: str, tf: str
) -> None:
    with pytest.raises(FeatureInputRefused, match="daily bars"):
        column_memory_bars(column, CONFIG, default_registry(), tf)


def test_an_ordinary_column_is_admitted_on_any_source_tf_with_its_memory() -> None:
    registry = default_registry()
    memory = registry.effective_memory_bars(registry.by_output("momentum_z_mid").name, CONFIG)
    for tf in ("1d", "1h", "5m"):
        assert column_memory_bars("momentum_z_mid", CONFIG, registry, tf) == memory > 0


def test_every_pass_through_column_is_accounted_for() -> None:
    """A new pass-through kernel must be listed (finite with a reach, or marked): otherwise it
    would be admitted as memoryless."""
    registry = default_registry()
    outputs = {
        o
        for k in registry.kernels
        if k.name.endswith(("_pass_through", "_passthrough"))
        for o in k.outputs
    }
    covered = set(BUILDER_FIRST_ROW) | set(MARKED)
    assert outputs == covered, sorted(outputs ^ covered)


def _consumers_of_marked() -> set[str]:
    """Every output whose kernel reads, directly or through other kernels, a marked output,
    derived from the registry's inputs (no column list)."""
    registry = default_registry()
    external = {e.name for e in registry.external_inputs}
    produced = {o for k in registry.kernels for o in k.outputs}

    def reads_marked(output: str, seen: frozenset[str] = frozenset()) -> bool:
        kernel = registry.by_output(output)
        for name in kernel.inputs:
            if name in seen or name in external or name not in produced:
                continue
            if name in MARKED or reads_marked(name, seen | {output}):
                return True
        return False

    return {o for o in produced if o not in MARKED and reads_marked(o)}


def test_a_consumer_of_a_marked_output_is_refused_like_the_output() -> None:
    """A column computed from a marked pass-through inherits its dependence on the builder's
    series start; admitting it would be a silent wrong answer (todo 674 finding 1)."""
    consumers = _consumers_of_marked()
    assert consumers, "the registry has consumers of a marked output (macro products)"
    registry = default_registry()
    for column in sorted(consumers):
        with pytest.raises(FeatureInputRefused, match="through its input"):
            column_memory_bars(column, CONFIG, registry)


def test_only_marked_outputs_and_their_consumers_are_refused() -> None:
    registry = default_registry()
    refused = {
        o
        for k in registry.kernels
        for o in k.outputs
        if registry.builder_path_dependent_source(o) is not None
    }
    assert refused == set(MARKED) | _consumers_of_marked()


@pytest.mark.parametrize("column", sorted(MARKED | _consumers_of_marked()))
def test_the_spec_check_refuses_a_marked_pass_through_without_a_config(column: str) -> None:
    """The refusal needs no data and no config, so it fires at spec load like its path-dependent
    sibling (B1g), not only once a provenance config is built."""
    from src.intelligence.research import runner
    from src.intelligence.research.runner import RunRefused

    class _Input:
        kind, tf = "feature", "1d"

    class _Member:
        name = "m"
        input = _Input()

    _Input.column = column
    with pytest.raises(RunRefused, match="path-dependent builder"):
        runner._check_input_column(_Member())
