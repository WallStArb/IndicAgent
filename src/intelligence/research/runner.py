"""The research runner (architecture step 4): no real-data number outside a recorded run.

Real mode, in order (D-02, D-03):

1. Gate, before any ledger row or data: the spec is committed and unchanged at HEAD (parsed
   from the HEAD blob), its declared memory matches the member definition, every member
   resolves inside the families package, no checked code or spec is dirty or untracked, and
   the ledger holds no real run for the spec hash. Any failure raises RunRefused.
2. The ledger writes one `started` row per member (and the identity rows), before any data is
   read. From here every outcome is recorded; a crash leaves the rows started, which counts.
3. S0 snapshot (content hash verified), S1 residual bar returns and residual forward target,
   the E17 static-size precondition (todo 447: a family above its H0 battery's gated sizes is
   refused, uncharged), S2 members, S3 guards (real-data split, D-25), the shift-floor refusal (evidence runs are
   never refused on power, D-21), S5 per member with R1 and R2, the evidence record, and the
   terminal update.

A guard failure ends every row guard_failed; a refusal ends them refused; any other error
ends the unfinished rows failed and re-raises. Synthetic mode (D-04) runs the same pipeline
on a given panel with no git check, no ledger and no snapshot, so tests exercise the real code.

S3 on real data (D-25): S1 costs minutes per call on the full panel, so it is probed once on a
sub-panel of the spec's first s1_probe_sessions sessions, and the members are probed on the
fixed full-size residual array with the array guards.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib
import math
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from zoneinfo import ZoneInfo

import numpy as np

from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.features.contract import causality_probe as truncation
from src.intelligence.features.contract.derived_inputs import with_derived_inputs
from src.intelligence.features.contract.registry import KernelRegistryError, default_registry
from src.intelligence.research import (
    align,
    certificate,
    clock,
    contribution,
    data_quality,
    dividends,
    feature_inputs,
    guards,
    kernel_source,
    null_battery_persistent,
    power,
    provenance,
    smoothing,
    snapshot,
    static_sizes,
    store,
    synthetic,
    transforms,
)
from src.intelligence.research import panel as panel_mod
from src.intelligence.research import recipe as recipe_mod
from src.intelligence.research.book import book_memory, book_timing
from src.intelligence.research.combiner import Combiner, EqualWeight, RidgeSpec, SignFold
from src.intelligence.research.construction import resolve_rule
from src.intelligence.research.evaluate import (
    PoolFactory,
    evaluate,
    session_shifts,
    trade_mask,
)
from src.intelligence.research.evidence import (
    coverage_summary,
    evidence_record,
    turnover_per_session,
)
from src.intelligence.research.factors import VINTAGE_1, FactorSpec
from src.intelligence.research.families import features as features_family
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.ledger import (
    AttemptSeries,
    Identity,
    LedgerRefusal,
    PinnedRun,
    RunRequest,
    SubsetRefit,
)
from src.intelligence.research.member_memory import (
    MemberMemory,
    feature_member_memory,
    warmup_prefix_sessions,
)
from src.intelligence.research.panel import SECTOR_PIT, Panel, fwd_span, present
from src.intelligence.research.portfolio import RANK_VOL_NEUTRAL_ARM, trailing_vol
from src.intelligence.research.recipe import RecipeContent
from src.intelligence.research.spec import (
    TIMING_STATISTIC,
    BookSpec,
    FamilySpec,
    LoadedSpec,
    MemberSpec,
    resolve_member,
)
from src.intelligence.research.timing import e17_memory, timing_test
from src.intelligence.research.transforms import PanelTransform

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

FACTOR_SPECS = {"vintage_1": VINTAGE_1}


@dataclasses.dataclass(frozen=True)
class BudgetConfig:
    vintage_id: str
    budget_m: int
    screen_alpha: float


@dataclasses.dataclass(frozen=True)
class ContributionConfig:
    """Contribution accounting settings (APR alpha.research.contribution.*, read by the caller,
    never inside the research layer). A RunContext without one skips accounting."""

    exact_max_families: int
    shapley_samples: int
    shapley_seed: int
    cluster_corr: float


class RunRefused(Exception):
    """A real run refused before any ledger row exists (D-02, or a ledger refusal)."""


class LedgerPort(Protocol):
    async def has_real_run(self, spec_hash: str) -> bool: ...

    async def start_runs(self, request, identities, run_concepts) -> dict[str, str]: ...

    async def finish_run(
        self, run_id, *, status, snapshot_hash, evidence, series=None, universe_hash=None
    ) -> None: ...

    async def pinned_run(self, run_id: str) -> PinnedRun | None: ...

    async def start_subset_refits(self, parent_run_id: str, refits, author: str) -> dict: ...


async def _source_configs(
    dsn: str, spec: FamilySpec
) -> tuple[list[str], list, dict[str, FeatureFactoryConfig]]:
    """(universe symbols, source requests, verified FeatureFactoryConfig per source tf) for a
    spec with input members, read before any bar is fetched (B1c, B1f). The member memory and
    the certificate's memory bound are checked on them, so a refusal needs no snapshot."""
    symbols = await snapshot.universe_symbols(dsn, spec.panel.universe)
    sources = _source_requests(spec)
    configs: dict[str, FeatureFactoryConfig] = {}
    if sources:
        found = await snapshot.source_configs(
            dsn, sources, spec.panel.start, spec.panel.end_exclusive, symbols=symbols
        )
        configs = {tf: entry["config"] for tf, entry in found.items()}
        _check_member_memory(spec, configs)
    return symbols, sources, configs


async def preflight_member_memory(spec: FamilySpec, ctx: RunContext) -> None:
    """Refuse a member whose declared memory or source memory the certificate does not cover
    before the ledger opens a run (todo 588 m1): a refusal must never burn a spec hash as a
    failed run. Needs the provenance configs, so it runs when this run builds its own snapshot
    (the default build) or is handed a snapshot whose manifest records them."""
    if not _input_members(spec):
        return
    if ctx.snapshot is not None:
        _check_member_memory(spec, _manifest_configs(store.read_meta(ctx.snapshot)["manifest"]))
    elif ctx.build_snapshot is None and ctx.dsn is not None:
        await _source_configs(ctx.dsn, spec)


async def _default_build(dsn: str, out_dir: Path, spec: FamilySpec) -> Path:
    symbols, sources, configs = await _source_configs(dsn, spec)
    inputs: dict = {}
    if sources:
        inputs = {
            "warmup_sessions": _warmup_prefix(spec, configs),
            "sources": sources,
        }
    return await snapshot.build_panel(
        dsn,
        out_dir,
        symbols=symbols,
        tf=spec.panel.tf,
        start=spec.panel.start,
        end_exclusive=spec.panel.end_exclusive,
        manifest_extra={"universe": spec.panel.universe},
        dividends=spec.panel.total_return is not None,
        fields=_build_fields(spec),
        **inputs,
    )


@dataclasses.dataclass
class RunContext:
    root: Path
    budget: BudgetConfig
    workers: int = 1
    pool_factory: PoolFactory | None = None
    ledger: LedgerPort | None = None
    dsn: str | None = None
    snapshot_dir: Path | None = None
    snapshot: Path | None = None
    build_snapshot: Callable[..., Awaitable[Path]] | None = None
    # Plan 187-11: the APR values the run's definition depends on (the book test's bar reads the
    # budget M and the screen alpha; recorded in the book's recipe), and the attempt that
    # prompted this one (research_run.informed_by).
    apr_values: dict = dataclasses.field(default_factory=dict)
    informed_by: str | None = None
    # Plan 187-14: contribution accounting of a book test; None records none.
    contribution: ContributionConfig | None = None


@dataclasses.dataclass(frozen=True)
class Residuals:
    bar: np.ndarray  # S1 residual bar returns [n, m]
    fwd: np.ndarray  # S1 residual forward target [n, m]


def compute_residuals(
    panel: Panel,
    *,
    horizon: int,
    factor_spec: FactorSpec,
    transform: PanelTransform = transforms.IDENTITY,
) -> Residuals:
    """S1 twice, as the panel's transform defines it: residual bar returns (the members' input)
    and the residual forward target."""
    return Residuals(
        bar=transform.s1_bar(panel, factor_spec),
        fwd=transform.s1_target(panel, horizon, factor_spec),
    )


def _member_fn(spec: FamilySpec, member, bars_per_session: int):
    return functools.partial(
        resolve_member(member.signal),
        bars_per_session=bars_per_session,
        coverage_floor=spec.construction.coverage_floor,
        **member.params,
    )


def compute_members(
    spec: FamilySpec,
    resid_bar: np.ndarray,
    *,
    bars_per_session: int,
    panel: Panel | None = None,
) -> dict[str, np.ndarray]:
    """S2: every member on its declared input: the S1 residual bar returns (unchanged for every
    resid_bar member) or, for a feature or kernel member, the source value S2b aligned to the
    book clock (`panel` carries the S0 sources)."""
    return {
        m.name: _member_fn(spec, m, bars_per_session)(member_input(spec, m, panel, resid_bar))
        for m in spec.members
    }


def _sub_panel(panel: Panel, sessions: int) -> Panel:
    kept = min(sessions, panel.n_sessions)
    rows = slice(0, kept * panel.bars_per_session)
    optional = {
        name: np.asarray(array[:kept] if name == SECTOR_PIT else array[rows])
        for name, array in present(panel).items()
    }
    return dataclasses.replace(
        panel,
        timestamps=panel.timestamps[rows],
        valid=panel.valid[rows],
        open=np.asarray(panel.open[rows]),
        close=np.asarray(panel.close[rows]),
        volume=np.asarray(panel.volume[rows]),
        **optional,
    )


def _probe_rows(panel: Panel, g, transform: PanelTransform) -> np.ndarray:
    """guards.probe_rows plus the rows the transform says S3 must always probe."""
    rows = guards.probe_rows(panel, n_random=g.n_random, seed=g.seed, max_rows=g.max_rows)
    return np.unique(np.concatenate([rows, transform.extra_probe_rows(panel)]))


def real_guards(
    panel: Panel,
    spec: FamilySpec,
    members: dict[str, np.ndarray],
    residuals: Residuals,
    *,
    factor_spec: FactorSpec,
    transform: PanelTransform = transforms.IDENTITY,
    source_probe: Panel | None = None,
) -> dict:
    """S3 split per D-25; raises guards.GuardFailure. Returns the integrity reports (for
    coverage) and a summary for the evidence record. `source_probe`, for a transformed panel,
    is the S0 source sub-panel the transform's own causality probe runs on."""
    bps, n = panel.bars_per_session, len(panel.timestamps)
    g = spec.guards
    reports = {name: guards.integrity(panel, alpha) for name, alpha in members.items()}
    rows = _probe_rows(panel, g, transform)
    reach = {}
    input_reports = {}
    for m in spec.members:
        fn = _member_fn(spec, m, bps)
        if m.input is not None:
            reach[m.name], input_reports[m.name] = _guard_input_member(spec, m, panel, fn, rows)
            continue
        declared = m.slot_history_sessions * bps
        guards.causality_probe_array(fn, residuals.bar, rows, seed=g.seed)
        reach[m.name] = guards.memory_check_array(
            fn, residuals.bar, rows[rows < n - declared - 1], declared=declared
        )

    sub = _sub_panel(panel, g.s1_probe_sessions)
    h = spec.horizon

    bar_fn = functools.partial(transform.s1_bar, factor_spec=factor_spec)

    def target_fn(p: Panel) -> np.ndarray:
        return transform.s1_target(p, h, factor_spec)

    sub_rows = _probe_rows(sub, g, transform)
    if transform.probe is not None:
        if source_probe is None:
            raise ValueError(f"transform {transform.name!r} needs its source sub-panel to probe")
        transform.probe(source_probe, sub_rows, g.seed)
    guards.causality_probe(bar_fn, sub, sub_rows, seed=g.seed)
    guards.causality_probe(target_fn, sub, sub_rows, seed=g.seed, reach=fwd_span(h))
    s1_declared = (factor_spec.window_sessions + factor_spec.refit_sessions) * bps
    n_sub = len(sub.timestamps)
    s1_reach = guards.memory_check(
        bar_fn, sub, sub_rows[sub_rows < n_sub - s1_declared - 1], declared=s1_declared
    )
    summary = {
        "probe_rows": len(rows),
        "member_memory_reach": reach,
        "s1_probe_sessions": sub.n_sessions,
        "s1_probe_rows": len(sub_rows),
        "s1_memory_reach": s1_reach,
    }
    if input_reports:
        summary["input_members"] = input_reports
    return {"reports": reports, "summary": summary}


def family_identities(loaded: LoadedSpec) -> list[Identity]:
    spec = loaded.model
    family = f"family.{spec.family}"
    ids = [
        Identity(
            family,
            "family",
            f"Research family {spec.family} ({spec.prior_source})",
            {"prior_source": spec.prior_source, "spec_path": loaded.path},
        )
    ]
    for m in spec.members:
        ids.append(
            Identity(
                f"member.{spec.family}.{m.name}",
                "member",
                f"Member {m.name} of family {spec.family}",
                {"signal": m.signal, "params": dict(m.params)},
                parents=(family,),
            )
        )
    return ids


# --- feature and kernel input members (plan 184-09) ---------------------------------------

# Regular-session bars per source tf (the grid snapshot.build_grid derives; the 1h grid ends on
# the short 15:30 bucket). Pinned against the battery's table in the tests.
_BARS_PER_SESSION = {"1d": 1, "1h": 7, "15m": 26, "5m": 78}
# The supported subset of input-member books (184-REVIEWS row 4): the source tfs by book tf.
_SUPPORTED_SOURCES = {"1d": ("1d", "1h", "15m", "5m"), "1h": ("1d",)}


def _input_members(spec: FamilySpec) -> list[MemberSpec]:
    return [m for m in spec.members if m.input is not None]


def _check_input_column(m: MemberSpec) -> None:
    """A member's column is in the registry, applicable on its tf and has finite memory. Needs
    no data and no config; a regime-origin column is S0's to stop (B1j needs the batches)."""
    inp = m.input
    try:
        if inp.kind == "feature":
            registry = default_registry()
            feature_inputs.check_columns([inp.column], registry, inp.tf)
            feature_inputs.refuse_path_dependent(inp.column, registry)
        elif kernel_source.kernel_registry(inp.windows, None).is_path_dependent(inp.column):
            raise RunRefused(f"member {m.name}: {inp.column} is path dependent (B1g)")
    except (ValueError, KernelRegistryError) as error:
        raise RunRefused(f"member {m.name}: {error}") from error


def _check_pins(spec: FamilySpec) -> None:
    pinned: dict[str, tuple[str, str]] = {}
    for m in _input_members(spec):
        pin = m.input.config_projection_hash
        first = pinned.setdefault(m.input.tf, (pin, m.name))
        if first[0] != pin:
            raise RunRefused(
                f"members {first[1]} and {m.name} pin different config_projection_hash values "
                f"for source tf {m.input.tf}: one provenance config per source tf"
            )


def _check_supported_subset(spec: FamilySpec, book: BookSpec | None) -> None:
    """The routes the battery covers (184-REVIEWS row 4), refused before any certificate lookup."""
    allowed = _SUPPORTED_SOURCES.get(spec.panel.tf, ())
    problems = [
        f"member {m.name}: a {m.input.tf} source on a {spec.panel.tf} book"
        for m in _input_members(spec)
        if m.input.tf not in allowed
    ]
    if spec.horizon != 1:
        problems.append(f"horizon {spec.horizon}")
    if book is not None and _combiner_kind(book) != "equal_weight":
        problems.append(f"combiner {_combiner_kind(book)}")
    if book is not None and book.horizon_rule is not None:
        problems.append("a horizon rule")
    if problems:
        raise RunRefused(
            "input members run in the supported subset only (daily books with 1d, 1h, 15m or 5m "
            "sources, hourly books with 1d sources, horizon 1, equal weight, no horizon rule; "
            f"184-REVIEWS row 4): {'; '.join(problems)}"
        )


def _certificate_request(
    spec: FamilySpec, m: MemberSpec, source_memory_bars: int
) -> null_battery_persistent.CertificateRequest:
    inp = m.input
    if inp.kind == "feature":
        identity, window = "feature", None
    else:
        ((identity, window),) = inp.windows.items()
    return null_battery_persistent.CertificateRequest(
        identity=identity,
        window=window,
        smoothing_half_life=m.smoothing_half_life,
        source_tf=inp.tf,
        book_tf=spec.panel.tf,
        horizon=spec.horizon,
        combiner="equal_weight",
        max_age_rows=inp.max_age_rows,
        max_gap_rows=inp.max_gap_rows,
        source_memory_bars=source_memory_bars,
    )


def _admit(
    spec: FamilySpec, m: MemberSpec, source_memory_bars: int
) -> null_battery_persistent.BatteryCertificate:
    """The member's route against the passing battery certificates (184-05); the certificate that
    covers it."""
    try:
        return null_battery_persistent.admit(_certificate_request(spec, m, source_memory_bars))
    except null_battery_persistent.NotCertified as error:
        raise RunRefused(f"member {m.name}: {error}") from error


def _check_member_signal(m: MemberSpec) -> None:
    """The battery certified one member function (families.features.centred); an input member
    with any other signal ran a route no cell tested (todo 588 B2)."""
    if resolve_member(m.signal) is not features_family.centred:
        raise RunRefused(
            f"member {m.name}: an input member's signal must be "
            f"{features_family.__name__}.centred, the one function the 184-05 battery certified "
            f"(got {m.signal})"
        )


def _check_input_mix(specs: Sequence[FamilySpec]) -> None:
    """Input members live in one family, never beside residual-return members: the battery's
    cells are books of input members on certified routes (todo 588 m3). How many, and which
    routes together, is _check_book_routes."""
    with_inputs = [s.family for s in specs if _input_members(s)]
    residual = [m.name for s in specs for m in s.members if m.input is None]
    if len(with_inputs) > 1:
        raise RunRefused(
            f"input members in more than one family are not certified (todo 588 m3): {with_inputs}"
        )
    if with_inputs and residual:
        inputs = [m.name for s in specs for m in _input_members(s)]
        raise RunRefused(
            "a book mixing input members and residual-return members is not certified "
            f"(todo 588 m3): {inputs} with {residual}"
        )


def _check_book_routes(
    spec: FamilySpec, routes: Sequence[null_battery_persistent.BatteryCertificate]
) -> None:
    """A book of more than one input member runs only as a composition whose own cells passed
    (todo 588 part B); one member needs just its route's certificate."""
    try:
        null_battery_persistent.admit_book(routes)
    except null_battery_persistent.NotCertified as error:
        raise RunRefused(f"family {spec.family}: {error}") from error


def _check_input_members(spec: FamilySpec, mode: str, book: BookSpec | None) -> None:
    """Everything about input members that needs no data. Synthetic mode skips the subset and the
    certificate so the battery itself can run (184-REVIEWS row 3); the source memory against the
    certificate's bound is checked once the provenance config is known (_check_member_memory)."""
    if not _input_members(spec):
        return
    for m in _input_members(spec):
        _check_input_column(m)
    _check_pins(spec)
    if mode == "synthetic":
        return
    _check_supported_subset(spec, book)
    _check_input_mix([spec])
    routes = []
    for m in _input_members(spec):
        _check_member_signal(m)
        routes.append(_admit(spec, m, 0))
    _check_book_routes(spec, routes)


def _member_memory(
    spec: FamilySpec, m: MemberSpec, configs: dict[str, FeatureFactoryConfig] | None
) -> MemberMemory:
    """The one member-memory function: `configs` maps a source tf to the FeatureFactoryConfig
    built from its verified provenance (never defaults). A residual-bar member keeps its declared
    rule (slot history in sessions, declared rows including S1's reach)."""
    bps = spec.panel.analysis_bars_per_session
    inp = m.input
    if inp is None:
        return MemberMemory(
            source_memory_bars=0,
            max_age_rows=0,
            smoothing_sessions=0,
            slot_history_sessions=m.slot_history_sessions,
            book_bars_per_session=bps,
            sessions=m.slot_history_sessions,
            rows=m.declared_memory_rows,
        )
    config = (configs or {}).get(inp.tf)
    if config is None:
        raise RunRefused(f"member {m.name}: no verified provenance config for source tf {inp.tf}")
    try:
        if inp.kind == "feature":
            source_bars = feature_inputs.column_memory_bars(inp.column, config, default_registry())
        else:
            source_bars = kernel_source.kernel_member_memory_bars(inp.column, inp.windows, config)
        return feature_member_memory(
            source_memory_bars=source_bars,
            source_bars_per_session=_BARS_PER_SESSION[inp.tf],
            max_age_rows=inp.max_age_rows,
            smoothing_half_life=m.smoothing_half_life,
            slot_history_sessions=m.slot_history_sessions,
            book_bars_per_session=bps,
        )
    except (ValueError, KernelRegistryError) as error:
        raise RunRefused(f"member {m.name}: {error}") from error


def _check_member_memory(spec: FamilySpec, configs: dict[str, FeatureFactoryConfig]) -> None:
    """Declared rows against the verified memory, and the source memory against the certificate's
    bound; both refuse before any bar is fetched or member computed."""
    for m in _input_members(spec):
        memory = _member_memory(spec, m, configs)
        if m.declared_memory_rows != memory.rows:
            raise RunRefused(
                f"member {m.name}: declared_memory_rows {m.declared_memory_rows} != {memory.rows} "
                "(source memory under the provenance config, alignment, smoothing, slot history)"
            )
        _admit(spec, m, memory.source_memory_bars)


def _manifest_configs(manifest: dict) -> dict[str, FeatureFactoryConfig]:
    """The configs a snapshot was built under: each source tf's verified provenance block."""
    return {
        tf: feature_inputs.feature_config(info["provenance"])
        for tf, info in (manifest.get("sources") or {}).items()
    }


def _member_memories(spec: FamilySpec, manifest: dict) -> dict[str, MemberMemory]:
    """Every member's memory; the E17 L of the run is book_memory / timing.e17_memory over these."""
    configs = _manifest_configs(manifest) if _input_members(spec) else None
    return {m.name: _member_memory(spec, m, configs) for m in spec.members}


def _warmup_prefix(spec: FamilySpec, configs: dict[str, FeatureFactoryConfig]) -> int:
    return warmup_prefix_sessions(
        [_member_memory(spec, m, configs).sessions for m in _input_members(spec)]
    )


def _needs_high_low(m: MemberSpec) -> bool:
    inp = m.input
    if inp.kind != "kernel":
        return False
    registry = kernel_source.kernel_registry(inp.windows, None)
    return any(
        name in ("high", "low")
        for kernel in registry.topological_order((inp.column,))
        for name in kernel.inputs
    )


def _source_requests(spec: FamilySpec) -> list[snapshot.SourceRequest]:
    """The S0 source requests the spec implies: one per distinct source tf, with its config pin."""
    by_tf: dict[str, list[MemberSpec]] = {}
    for m in _input_members(spec):
        by_tf.setdefault(m.input.tf, []).append(m)
    return [
        snapshot.SourceRequest(
            tf=tf,
            pinned_config_projection_hash=members[0].input.config_projection_hash,
            members=tuple(
                snapshot.MemberSourceRequest(
                    member=m.name,
                    kind=m.input.kind,
                    column=m.input.column,
                    windows=None if m.input.windows is None else dict(m.input.windows),
                    max_age_rows=m.input.max_age_rows,
                    max_gap_rows=m.input.max_gap_rows,
                    coverage_floor=m.input.coverage_floor,
                )
                for m in members
            ),
            need_high_low=any(_needs_high_low(m) for m in members),
        )
        for tf, members in sorted(by_tf.items())
    ]


def _build_fields(spec: FamilySpec) -> tuple[str, ...]:
    """The panel's optional arrays: the spec's, plus high and low when a kernel member on the
    book's own tf reads them (plan 187-15's field path)."""
    fields = set(spec.panel.fields or ())
    if any(r.need_high_low and r.tf == spec.panel.tf for r in _source_requests(spec)):
        fields |= {"high", "low"}
    return tuple(sorted(fields))


# --- S2b and S3 for feature and kernel members (plan 184-10) ------------------------------


@dataclasses.dataclass(frozen=True)
class InputSources:
    """Where S2b reads a snapshot's source arrays: the book snapshot directory (equal-tf arrays and
    a finer source's index evidence), the child directory of each coarser tf, and the snapshot's
    columns. Digests were checked when the snapshot loaded (`_load_panel`), so reads here are
    plain memory maps. `cache` holds the run's member indexes (Panel.sources is not hashed)."""

    path: Path
    symbols: tuple[str, ...]
    children: Mapping[str, Path]
    cache: dict = dataclasses.field(default_factory=dict, compare=False, repr=False)

    def array(self, name: str) -> np.ndarray:
        return np.asarray(store.read_array(self.path, name))

    def has(self, name: str) -> bool:
        return store.has_array(self.path, name)

    def _dir(self, tf: str, book_tf: str) -> Path:
        path = self.path if tf == book_tf else self.children.get(tf)
        if path is None:
            raise ValueError(f"no loaded source for tf {tf}")
        return path

    def source_array(self, tf: str, book_tf: str, name: str) -> np.ndarray:
        directory = self._dir(tf, book_tf)
        if not store.has_array(directory, name):
            raise ValueError(f"no loaded source array {name!r} for tf {tf}")
        return np.asarray(store.read_array(directory, name))

    def source_grid(self, tf: str, book_tf: str) -> Panel:
        """The source-clock panel (the book's own grid when tf is the book's)."""
        key = ("grid", tf)
        if key not in self.cache:
            self.cache[key] = panel_mod.load(self._dir(tf, book_tf), verify=False)
        return self.cache[key]

    def columns(self, symbols: tuple[str, ...]) -> slice | np.ndarray:
        """The snapshot columns of the analysis panel's symbols (a members_universe narrowing
        selects; a symbol the snapshot lacks, such as a total_return segment, is refused)."""
        if tuple(symbols) == self.symbols:
            return slice(None)
        where = {s: j for j, s in enumerate(self.symbols)}
        missing = [s for s in symbols if s not in where]
        if missing:
            raise RunRefused(
                f"input members read S0 source columns by symbol; {missing[:3]} is not one "
                "(total_return segments are not supported)"
            )
        return np.array([where[s] for s in symbols])


def _attach_sources(panel: Panel, sources: InputSources) -> Panel:
    return dataclasses.replace(panel, sources=sources)


@dataclasses.dataclass(frozen=True)
class MemberIndex:
    """One member's alignment to the book clock: `gather(values, gather_idx)` is the aligned
    input. `src_idx` are the same reads as source-grid rows (what S3 checks against
    `src_closes`); for a coarser or equal source the two index arrays are one."""

    values: np.ndarray
    gather_idx: np.ndarray
    src_idx: np.ndarray
    src_closes: np.ndarray  # datetime64[ns] [ns], clock.closes_at on the source bar grid


def _is_finer(source_tf: str, book_tf: str) -> bool:
    return _BARS_PER_SESSION[source_tf] > _BARS_PER_SESSION[book_tf]


def _input_sources(panel: Panel | None, m: MemberSpec) -> InputSources:
    sources = None if panel is None else panel.sources
    if not isinstance(sources, InputSources):
        raise ValueError(f"member {m.name}: no loaded source for tf {m.input.tf}")
    return sources


def member_index(spec: FamilySpec, m: MemberSpec, panel: Panel) -> MemberIndex:
    """S2b: the only alignment of a member's source to the book clock. A coarser or equal source
    is aligned here with `align.align_index` over availability recomputed from the source grid;
    a finer source replays the index S0 persisted, remapped into the referenced values. No
    availability is read from stored metadata."""
    inp, book_tf = m.input, spec.panel.tf
    sources = _input_sources(panel, m)
    if panel.closes_at is None:
        raise RunRefused(f"member {m.name}: the panel carries no closes_at (B1b)")
    key = (
        m.name,
        inp.kind,
        inp.tf,
        inp.column,
        tuple(sorted((inp.windows or {}).items())),
        inp.max_age_rows,
        panel.symbols,
    )
    if key in sources.cache:
        return sources.cache[key]
    cols = sources.columns(panel.symbols)
    bps = _BARS_PER_SESSION[inp.tf]
    if _is_finer(inp.tf, book_tf):
        for name in (f"idx__{m.name}", f"ref_rows__{m.name}", f"ref_values__{m.name}"):
            if not sources.has(name):
                raise ValueError(f"member {m.name}: no loaded source for tf {inp.tf} ({name})")
        src_closes = clock.closes_at(
            sources.array(f"src_ts__{inp.tf}"), sources.array(f"src_valid__{inp.tf}"), inp.tf, bps
        )
        src_idx = sources.array(f"idx__{m.name}")[:, cols]
        if src_idx.shape[0] != len(panel.timestamps):
            raise RunRefused(
                f"member {m.name}: the persisted index has {src_idx.shape[0]} book rows, the "
                f"panel {len(panel.timestamps)} (a transform changed the row grid)"
            )
        ref_rows = sources.array(f"ref_rows__{m.name}")
        used = np.maximum(src_idx, 0)
        pos = np.searchsorted(ref_rows, used)
        if np.any((src_idx >= 0) & (ref_rows[np.minimum(pos, max(len(ref_rows) - 1, 0))] != used)):
            raise ValueError(f"member {m.name}: persisted index reads rows missing from ref_rows")
        gather_idx = np.where(src_idx >= 0, pos, -1).astype(np.int32)
        values = sources.array(f"ref_values__{m.name}")[:, cols]
    else:
        name = (
            feature_inputs.feature_array_name(inp.tf, inp.column)
            if inp.kind == "feature"
            else f"kernel__{inp.tf}__{m.name}"
        )
        values = sources.source_array(inp.tf, book_tf, name)[:, cols]
        grid = sources.source_grid(inp.tf, book_tf)
        src_closes = clock.closes_at(grid.timestamps, grid.valid, inp.tf, grid.bars_per_session)
        src_idx = gather_idx = align.align_index(
            np.isfinite(values), src_closes, panel.closes_at, inp.max_age_rows
        )
    sources.cache[key] = MemberIndex(values, gather_idx, src_idx, src_closes)
    return sources.cache[key]


def member_input(
    spec: FamilySpec, m: MemberSpec, panel: Panel | None, resid_bar: np.ndarray
) -> np.ndarray:
    """A member's declared input: the S1 residual bar returns for a resid_bar member (the same
    object, so those members are untouched), else the S2b-aligned source, smoothed when the
    member pins a half-life."""
    if m.input is None:
        return resid_bar
    index = member_index(spec, m, panel)
    aligned = align.gather(index.values, index.gather_idx)
    if m.smoothing_half_life is None:
        return aligned
    return smoothing.smooth(aligned, m.smoothing_half_life)


def _probe_panels(
    spec: FamilySpec, m: MemberSpec, panel: Panel, need_hl: bool
) -> list[tuple[int, Panel]]:
    """(panel column, one-symbol source-clock Panel of raw bars) for the symbols S0 kept raw
    bars of (a finer source: its probe symbols) or the first symbols (otherwise)."""
    inp, sources = m.input, panel.sources
    bps = _BARS_PER_SESSION[inp.tf]
    out = []
    if _is_finer(inp.tf, spec.panel.tf):
        bars = sources.array(f"probe_bars__{inp.tf}")
        ts, valid = sources.array(f"src_ts__{inp.tf}"), sources.array(f"src_valid__{inp.tf}")
        for i, name in enumerate(panel.manifest["sources"][inp.tf]["probe_symbols"]):
            if name not in panel.symbols:
                continue
            b = bars[:, [i], :]
            one = Panel(
                tf=inp.tf,
                symbols=(name,),
                timestamps=ts,
                bars_per_session=bps,
                valid=valid,
                open=b[:, :, 0],
                close=b[:, :, 3],
                volume=b[:, :, 4],
                high=b[:, :, 1] if need_hl else None,
                low=b[:, :, 2] if need_hl else None,
            )
            out.append((panel.symbols.index(name), one))
        return out
    grid = sources.source_grid(inp.tf, spec.panel.tf)
    for pcol, name in list(enumerate(panel.symbols))[: snapshot.PROBE_SYMBOLS]:
        j = [grid.symbols.index(name)]
        hl = {
            f: (
                np.asarray(getattr(grid, f))[:, j]
                if need_hl and getattr(grid, f) is not None
                else None
            )
            for f in ("high", "low")
        }
        one = Panel(
            tf=grid.tf,
            symbols=(name,),
            timestamps=grid.timestamps,
            bars_per_session=grid.bars_per_session,
            valid=grid.valid,
            open=np.asarray(grid.open)[:, j],
            close=np.asarray(grid.close)[:, j],
            volume=np.asarray(grid.volume)[:, j],
            **hl,
        )
        out.append((pcol, one))
    return out


def _kernel_column(p1: Panel, m: MemberSpec, config, need_hl: bool) -> np.ndarray:
    inp = m.input
    result = kernel_source.kernel_source(
        p1,
        [inp.column],
        dict(inp.windows),
        config,
        max_gap_rows=int(inp.max_gap_rows),
        high=p1.high if need_hl else None,
        low=p1.low if need_hl else None,
    )
    return result.values[inp.column][:, 0]


def _perturb(p1: Panel, later: np.ndarray, fill: str, rng: np.random.Generator) -> Panel:
    """p1 with every raw bar in the `later` rows replaced (NaN, or one seeded rescale per row for
    the prices, which keeps high >= low, and one for the volume)."""
    price = np.exp(rng.normal(0.0, 0.5, int(later.sum())))
    volume = np.exp(rng.normal(0.0, 0.5, int(later.sum())))
    fields = {}
    for name in ("open", "high", "low", "close", "volume"):
        array = getattr(p1, name)
        if array is None:
            continue
        array = np.array(array, dtype=float, copy=True)
        if fill == "nan":
            array[later] = np.nan
        else:
            array[later] *= (volume if name == "volume" else price)[:, None]
        fields[name] = array
    return dataclasses.replace(p1, **fields)


def _truncation_probe(registry, p1: Panel, config, m: MemberSpec, need_hl: bool, n_rows: int):
    """Phase 186's truncation probe and memory check on the member's kernel chain, over the
    present rows of one probe symbol; returns the kernel names probed."""
    close = np.asarray(p1.close, dtype=float)[:, 0]
    present = np.flatnonzero(np.asarray(p1.valid, dtype=bool) & np.isfinite(close))
    if present.size == 0:
        return []
    inputs = {
        "ts": np.asarray(p1.timestamps).astype("datetime64[ns]").astype(np.int64)[present],
        "tf": np.full(present.size, p1.tf, dtype=object),
    }
    for name in ("open", "high", "low", "close", "volume"):
        array = getattr(p1, name)
        if array is not None and (need_hl or name not in ("high", "low")):
            inputs[name] = np.asarray(array, dtype=float)[present, 0]
    available = with_derived_inputs(inputs)
    n_probe = min(max(n_rows, 1), present.size)
    rows = np.unique(np.linspace(0, present.size - 1, n_probe).astype(np.int64))
    names = []
    try:
        for kernel in registry.topological_order((m.input.column,)):
            truncation.causality_probe(kernel, available, config, rows)
            if not kernel.path_dependent:
                truncation.memory_check(kernel, available, config, rows)
            native = kernel.compute({k: available[k] for k in kernel.inputs}, config)
            available.update({k: np.asarray(native[k]) for k in kernel.outputs})
            names.append(kernel.name)
    except (truncation.CausalityViolation, truncation.MemoryViolation) as error:
        raise guards.GuardFailure(f"member {m.name}: kernel truncation probe: {error}") from error
    return names


def _kernel_probe(
    spec: FamilySpec, m: MemberSpec, panel: Panel, x: np.ndarray, fn, rows: np.ndarray
) -> dict:
    """End-to-end probe for a kernel member (184-REVIEWS row 1). Per probe symbol the kernel,
    alignment and smoother are recomputed from the S0 raw bars and must equal the persisted
    input; then every raw bar not available by a decision row's close is replaced (NaN, then a
    seeded rescale) and the member recomputed: alpha rows at or before that decision row must not
    move. The cross-section is the stored one with only the probe columns recomputed."""
    g, inp = spec.guards, m.input
    config = _manifest_configs(panel.manifest)[inp.tf]
    need_hl = _needs_high_low(m)
    index = member_index(spec, m, panel)
    dst, h = panel.closes_at, m.smoothing_half_life
    probes = _probe_panels(spec, m, panel, need_hl)
    if not probes:
        raise guards.GuardFailure(f"member {m.name}: no S0 probe symbol is in the panel")

    def aligned_column(p1: Panel) -> tuple[np.ndarray, np.ndarray]:
        col = _kernel_column(p1, m, config, need_hl)[:, None]
        idx = align.align_index(np.isfinite(col), index.src_closes, dst, inp.max_age_rows)
        return idx[:, 0], align.gather(col, idx)[:, 0]

    registry = kernel_source.kernel_registry(inp.windows, config)
    kernels: list[str] = []
    for pcol, p1 in probes:
        idx, value = aligned_column(p1)
        same = np.array_equal(idx, index.src_idx[:, pcol])
        if not (same and np.array_equal(value, x[:, pcol], equal_nan=True)):
            raise guards.GuardFailure(
                f"member {m.name}: persisted {inp.tf} source differs from the kernel recomputed "
                f"from raw bars on {p1.symbols[0]}"
            )
        kernels = _truncation_probe(registry, p1, config, m, need_hl, g.n_random)

    def smoothed(a: np.ndarray) -> np.ndarray:
        return a if h is None else smoothing.smooth(a, h)

    base_in = smoothed(x)
    base_out = fn(base_in)
    base_nan = np.isnan(base_out)
    scored = _scored_mask(panel)
    at = np.sort(rows if scored is None else rows[scored[rows]])
    limit = max(g.n_random, 1)
    if len(at) > limit:
        at = at[np.linspace(0, len(at) - 1, limit).round().astype(np.int64)]
    rng = np.random.default_rng(g.seed)
    for fill in ("nan", "rescale"):
        for t in (int(r) for r in at):
            if np.isnat(dst[t]):
                continue
            later = np.isnat(index.src_closes) | (index.src_closes > dst[t])
            if not later.any():
                continue
            work = base_in.copy()
            for pcol, p1 in probes:
                _, value = aligned_column(_perturb(p1, later, fill, rng))
                work[:, [pcol]] = smoothed(value[:, None].astype(x.dtype, copy=False))
            out = fn(work)[: t + 1]
            out_nan = np.isnan(out)
            moved = (out_nan != base_nan[: t + 1]) | (~out_nan & (out != base_out[: t + 1]))
            if moved.any():
                raise guards.GuardFailure(
                    f"lookahead: member {m.name} alpha row {int(np.argwhere(moved)[0][0])} changed "
                    f"when raw {inp.tf} bars available after decision row {t} were replaced "
                    f"({fill})"
                )
    return {
        "kernel_probe_symbols": [p1.symbols[0] for _, p1 in probes],
        "kernel_probe_rows": len(at),
        "kernel_truncation": kernels,
    }


def _guard_input_member(
    spec: FamilySpec, m: MemberSpec, panel: Panel, fn, rows: np.ndarray
) -> tuple[int, dict]:
    """S3 for a feature or kernel member: every scored row's alignment against availability
    recomputed from the source grid, the causality probe and memory check over the aligned input
    composed with the smoother (declared at MemberMemory.transform_rows, the memory object that
    feeds the warmup prefix and E17's L), and for a kernel the end-to-end raw-bar probe. A stored
    feature's own causality is phase 186's truncation probe, cited here by code_key."""
    g, inp = spec.guards, m.input
    index = member_index(spec, m, panel)
    memory = _member_memory(spec, m, _manifest_configs(panel.manifest))
    scored = _scored_mask(panel)
    scored_rows = np.arange(len(panel.timestamps)) if scored is None else np.flatnonzero(scored)
    align.check_alignment(
        index.src_idx, index.src_closes, panel.closes_at, inp.max_age_rows, scored_rows
    )
    x = align.gather(index.values, index.gather_idx)
    h = m.smoothing_half_life

    def member_fn(a: np.ndarray) -> np.ndarray:
        return fn(a if h is None else smoothing.smooth(a, h))

    guards.causality_probe_array(member_fn, x, rows, seed=g.seed)
    declared = memory.transform_rows
    reach = guards.memory_check_array(
        member_fn, x, rows[rows < len(x) - declared - 1], declared=declared
    )
    block = panel.manifest["sources"][inp.tf].get("provenance", {})
    report = {
        "kind": inp.kind,
        "source_tf": inp.tf,
        "alignment_rows_checked": int(len(scored_rows)),
        "reach": reach,
        "declared_reach": declared,
        "code_key": block.get("code_key"),
    }
    if inp.kind == "feature":
        report["value_causality"] = "phase 186 truncation probe (code_key); 184 proves alignment"
    else:
        report.update(_kernel_probe(spec, m, panel, x, fn, rows))
    return reach, report


def _check_spec(spec: FamilySpec, mode: str = "real", book: BookSpec | None = None) -> None:
    """Spec load, no data read. `mode` is the run mode (real, exploration or synthetic) and `book`
    the BookSpec the family runs in, if any: the input-member subset and certificate checks need
    both (synthetic stays open so the battery itself can run)."""
    bps = spec.panel.analysis_bars_per_session
    factor_spec = FACTOR_SPECS[spec.factor_spec]
    for m in spec.members:
        if m.input is None:
            want = declared_memory_rows(m.slot_history_sessions, bps, factor_spec)
            if m.declared_memory_rows != want:
                raise RunRefused(
                    f"member {m.name}: declared_memory_rows {m.declared_memory_rows} != {want} "
                    f"(slot history {m.slot_history_sessions} sessions plus S1's reach)"
                )
        resolve_member(m.signal)
    _check_input_members(spec, mode, book)


async def _gate(
    loaded: LoadedSpec, ctx: RunContext, *, once: bool = True, mode: str = "real"
) -> tuple[Path, str]:
    root = provenance.repo_root(ctx.root)
    try:
        blob = provenance.require_committed(root, loaded.path)
        if loaded.blob_sha is not None and blob != loaded.blob_sha:
            raise RunRefused(f"spec blob {blob} is not the loaded blob {loaded.blob_sha}")
        for fam in loaded.families:
            provenance.require_committed(root, fam.path)
        for book in loaded.books:  # a pod (plan 187-10): each member book and its families
            provenance.require_committed(root, book.path)
            for fam in book.families:
                provenance.require_committed(root, fam.path)
        if not loaded.books:  # a pod's members were checked when their own attempts ran
            _check_spec_tree(loaded, mode)
        provenance.require_clean(root)
    except provenance.ProvenanceRefusal as error:
        raise RunRefused(str(error)) from error
    if once and await ctx.ledger.has_real_run(loaded.spec_hash):
        raise RunRefused(f"spec already run: {loaded.spec_hash}")
    return root, provenance.head_commit(root)


def _require_r1(spec: FamilySpec | BookSpec) -> None:
    """The calibrated and fixed-sign rules size from a covariance plan the runner does not build
    yet: they are the construction attempt at capital readiness (design 4.3), not discovery.
    Checked in every mode, before any data is read."""
    if spec.construction.name != RANK_VOL_NEUTRAL_ARM:
        raise RunRefused(
            f"construction {spec.construction.name}: the runner runs R1 "
            f"({RANK_VOL_NEUTRAL_ARM}) only during discovery (design 4.3)"
        )


def _check_spec_tree(loaded: LoadedSpec, mode: str = "real") -> None:
    specs = [f.model for f in loaded.families] or [loaded.model]
    book = loaded.model if isinstance(loaded.model, BookSpec) else None
    # S0 is built from the book's first family (run_book), so a later family's input members
    # would find no source arrays: refused until S0 is requested for the whole book.
    later = [s.family for s in specs[1:] if isinstance(s, FamilySpec) and _input_members(s)]
    if later:
        raise RunRefused(
            f"input members outside the book's first family are not supported: {later}"
        )
    for spec in specs:
        if isinstance(spec, FamilySpec):
            _check_spec(spec, mode, book)
    if mode != "synthetic":
        _check_input_mix([s for s in specs if isinstance(s, FamilySpec)])
    # A real record's spec hash names its decision statistic (E17): a spec written before E17
    # never runs, and re-scoring one under E17 is a new spec hash, not the old one reused.
    for spec in {id(s): s for s in [loaded.model, *specs]}.values():
        _require_r1(spec)
        if spec.scoring.timing_statistic != TIMING_STATISTIC:
            raise RunRefused(
                f"spec predates {TIMING_STATISTIC}: scoring.timing_statistic must be "
                f"{TIMING_STATISTIC!r} (methodology-change-ledger E17)"
            )


def _symbol_digest(symbols: tuple[str, ...] | list[str]) -> str:
    """sha256 over a symbol list, newline joined: one digest form for every recorded universe
    identity (members_universe_hash, research_run.universe_hash)."""
    return hashlib.sha256("\n".join(symbols).encode()).hexdigest()


def _prepare_panel(
    spec: FamilySpec,
    source: Panel,
    *,
    source_hash: str | None,
    symbols: list[str] | None,
    grid: dividends.DividendGrid | None = None,
) -> tuple[Panel, Panel | None]:
    """The analysis panel from the S0 source: narrowed to the members' universe when the spec
    pins one (B3), converted to total-return prices when it declares total_return (todo 428),
    then transformed when it names a transform (B1). Returns it with the source
    sub-panel the transform's causality probe runs on (None without a transform)."""
    if symbols is not None:
        source = panel_mod.select_symbols(source, symbols)
        digest = _symbol_digest(source.symbols)
        source = dataclasses.replace(
            source,
            manifest={
                **source.manifest,
                "members_universe": spec.panel.members_universe,
                "members_universe_hash": digest,
                "members_universe_size": len(source.symbols),
            },
        )
    # D0 labels on database symbols, before total_return splits a name into segments (todo 501).
    labels = data_quality.panel_labels(source, total_return=spec.panel.total_return is not None)
    if labels is not None:
        source = dataclasses.replace(source, manifest={**source.manifest, "data_quality": labels})
    # After the universe filter (it matches database symbols; total_return renames split
    # segments `<symbol>~<k>`) and before the transform (legs read the corrected prices).
    if spec.panel.total_return is not None:
        if grid is None:
            raise ValueError("a total_return spec needs a snapshot captured with dividends")
        source = dividends.total_return(source, grid, spec.panel.total_return.suspect_yield)
    transform = transforms.resolve(spec.panel.transform)
    probe = None if transform.probe is None else _sub_panel(source, spec.guards.s1_probe_sessions)
    return transform.apply(source, source_hash), probe


async def _analysis_panel(
    spec: FamilySpec, ctx: RunContext, *, real: bool, panel: Panel | None, replay: bool = False
) -> tuple[Panel, str | None, str | None, Panel | None]:
    """(analysis panel, snapshot hash, universe hash, transform probe source): the S0 snapshot
    in real mode, the given panel in synthetic mode (which applies the transform but no
    universe filter: there is no database)."""
    if real:
        return await _load_panel(spec, ctx)
    # Generated synthetic panels carry no dividends: the identity grid keeps total_return a no-op.
    # A real S0 snapshot passed here arrives without its grid, so it is refused, never run on
    # unadjusted prices under a total-return spec.
    # Synthetic mode on a real snapshot is an uncounted look at the vintage; only a replay of
    # an already recorded run (plan 03's backfill and parity gate) may read one.
    if panel.manifest.get("source") == snapshot.PRICE_SOURCE and not replay:
        raise ValueError("a real S0 snapshot runs in real mode (synthetic runs are uncounted)")
    grid = None
    if spec.panel.total_return is not None:
        if panel.manifest.get("source") == snapshot.PRICE_SOURCE:
            raise ValueError("a total_return spec on a real snapshot runs in real mode")
        grid = dividends.no_dividends(panel)
    prepared, source_probe = _prepare_panel(spec, panel, source_hash=None, symbols=None, grid=grid)
    return prepared, None, None, source_probe


def _prefix_ok(manifest: dict, book_tf: str, required: int) -> bool:
    """The recorded warmup prefix holds `required` sessions: the declared count and, recomputed
    from the NYSE calendar between fetch_start and scored_start, the real one (184-REVIEWS row
    17). fetch_start must be the book clock's own start for that many sessions, so every source
    clock (same sessions, own bar stamps) has them too."""
    prefix = manifest.get("warmup_prefix")
    if not prefix or prefix["sessions"] < required:
        return False
    fetch = datetime.fromisoformat(prefix["fetch_start"])
    scored = datetime.fromisoformat(prefix["scored_start"])
    first = (fetch if book_tf == "1d" else fetch.astimezone(ZoneInfo("America/New_York"))).date()
    last = scored.date()
    available = 0
    if first < last:
        available = sum(1 for d in nyse_sessions(first, last) if d < last)
    return (
        scored.date().isoformat() == manifest.get("start")
        and available >= required
        and snapshot.warmup_fetch_start(scored, book_tf, available) == fetch
    )


def _source_match(spec: FamilySpec, panel: Panel) -> dict[str, tuple]:
    """The snapshot-against-spec pairs for input members: closes_at, the source tfs, each tf's
    config hash against its pin and the warmup prefix. A spec without input members expects
    neither sources nor a prefix, so a snapshot built for another spec cannot slip in."""
    manifest = panel.manifest
    sources = manifest.get("sources") or {}
    inputs = _input_members(spec)
    if not inputs:
        return {
            "sources": (sorted(sources), []),
            "warmup_prefix": ("warmup_prefix" in manifest, False),
        }
    pins = {m.input.tf: m.input.config_projection_hash for m in inputs}
    out: dict[str, tuple] = {
        "closes_at": (panel.closes_at is not None, True),
        "source_tfs": (sorted(sources), sorted(pins)),
    }
    for tf, pin in sorted(pins.items()):
        out[f"config_hash.{tf}"] = ((sources.get(tf) or {}).get("config_hash"), pin)
    required = None
    if set(pins) <= set(sources):
        required = _warmup_prefix(spec, _manifest_configs(manifest))
    out["warmup_prefix"] = (
        required is not None and _prefix_ok(manifest, spec.panel.tf, required),
        True,
    )
    return out


def _scored_mask(panel: Panel) -> np.ndarray | None:
    """bool [n]: rows at or after the snapshot's scored start; None without a warmup prefix."""
    prefix = panel.manifest.get("warmup_prefix")
    if not prefix:
        return None
    cut = datetime.fromisoformat(prefix["scored_start"]).astimezone(UTC).replace(tzinfo=None)
    return np.asarray(panel.timestamps).astype("datetime64[ns]") >= np.datetime64(cut, "ns")


def _trade(panel: Panel, cfg) -> np.ndarray:
    """The rows a run may trade: the scored span of the evaluation config on valid rows, and
    never a warmup prefix row (those only fill member memory, B1c)."""
    trade = trade_mask(panel.timestamps, cfg) & panel.valid
    scored = _scored_mask(panel)
    return trade if scored is None else trade & scored


async def _load_panel(spec: FamilySpec, ctx: RunContext) -> tuple[Panel, str, str, Panel | None]:
    """(analysis panel, snapshot content hash, universe hash, transform probe source). The
    universe hash (todo 491) is the sha256 over the S0 snapshot's symbol list, before any
    members_universe narrowing, so the promoted set the attempt ran on is on the run record."""
    path = ctx.snapshot
    if path is None:
        build = ctx.build_snapshot or _default_build
        path = await build(ctx.dsn, ctx.snapshot_dir, spec)
    digest = store.verify(path)
    panel = panel_mod.load(path)
    children = snapshot.verify_sources(path) if panel.manifest.get("sources") else {}
    universe_hash = _symbol_digest(panel.symbols)
    grid = dividends.load_grid(path)
    manifest = panel.manifest
    expected = {
        "tf": (panel.tf, spec.panel.tf),
        "bars_per_session": (panel.bars_per_session, spec.panel.bars_per_session),
        "start": (manifest.get("start"), spec.panel.start),
        "end_exclusive": (manifest.get("end_exclusive"), spec.panel.end_exclusive),
        "universe": (manifest.get("universe"), spec.panel.universe),
        "dividends": (grid is not None, spec.panel.total_return is not None),
        **_source_match(spec, panel),
    }
    wrong = {k: v for k, v in expected.items() if v[0] != v[1]}
    if wrong:
        raise ValueError(f"snapshot does not match the spec: {wrong}")
    if _input_members(spec):
        _check_member_memory(spec, _manifest_configs(manifest))
    symbols = None
    if spec.panel.members_universe == "us_session_equity":
        symbols = await snapshot.us_session_equity_symbols(ctx.dsn)
    elif spec.panel.members_universe == "daily_unseen":
        symbols = await snapshot.daily_unseen_symbols(ctx.dsn)
    sources = InputSources(Path(path), tuple(panel.symbols), children)
    panel, source_probe = _prepare_panel(
        spec, panel, source_hash=digest, symbols=symbols, grid=grid
    )
    if _input_members(spec):
        panel = _attach_sources(panel, sources)
    return panel, digest, universe_hash, source_probe


def _vol(spec: FamilySpec | BookSpec, resid_bar: np.ndarray, bps: int) -> np.ndarray:
    c = spec.construction
    window = c.vol_window_sessions * bps
    return trailing_vol(
        resid_bar, window_rows=window, min_finite=math.ceil(c.vol_min_finite_fraction * window)
    )


def _shift_diagnostic(
    alpha: np.ndarray,
    memory: int,
    spec: FamilySpec | BookSpec,
    horizon: int,
    panel: Panel,
    residuals: Residuals,
    vol: np.ndarray,
    ctx: RunContext,
):
    """The whole-session shift null of alpha under R1 and session scoring, a diagnostic since
    E16. (None, 0) when the panel admits no shift for this memory: the diagnostic is then
    absent, which never blocks a record."""
    s = spec.scoring
    n, bps = len(panel.timestamps), panel.bars_per_session
    try:
        shifts = session_shifts(n, bps, s.min_shift, memory)
    except ValueError:
        return None, 0
    res = evaluate(
        alpha,
        residuals.fwd,
        panel.close,
        panel.timestamps,
        s.evaluation_config(),
        mv_condition_max=s.mv_condition_max,
        ic_shrinkage_k=s.ic_shrinkage_k,
        shifts=shifts,
        workers=ctx.workers,
        construction=functools.partial(resolve_rule(spec, bps).returns, vol=vol),
        memory=memory,
        bars_per_session=bps,
        valid=panel.valid,
        embargo=fwd_span(horizon),
        pool_factory=ctx.pool_factory,
        session_scoring=s.session_scoring,
    )
    return res, len(shifts)


def static_gate(spec: FamilySpec) -> static_sizes.StaticGate:
    """The H0 battery gate for a family's module, before the ledger: a family no battery
    covers is refused without real data, never charged (E17 option C)."""
    module = family_module(spec)
    if not hasattr(module, "NULL_BATTERY"):
        raise RunRefused(
            f"family {spec.family}: no E17 H0 battery covers {module.__name__}; one at the "
            "family's measured static sizes must pass first (methodology-change-ledger E17)"
        )
    if module.NULL_BATTERY == null_battery_persistent.__name__:
        return null_battery_persistent.static_gate(_member_certificates(spec))
    return static_sizes.gate_for(module)


def _member_certificates(spec: FamilySpec) -> list[null_battery_persistent.BatteryCertificate]:
    """The passing certificates the input members route through, for the static gate (todo 588
    B1: a family is gated at the sizes its own certificates held). A member no certificate
    covers adds none; the admission check refuses it with its reason."""
    found = []
    for m in _input_members(spec):
        try:
            found.append(null_battery_persistent.admit(_certificate_request(spec, m, 0)))
        except null_battery_persistent.NotCertified:
            continue
    return found


def static_precondition(spec: FamilySpec, panel: Panel, gate: static_sizes.StaticGate) -> dict:
    """The family's measured static sizes against its battery's gate, on the analysis panel.
    A panel the sizes cannot be measured on fails the precondition: it is refused like one
    above the gate, never left to fail (a charged status) or to pass unchecked."""
    try:
        sizes = static_sizes.measure(
            panel,
            cell_rows=gate.cell_rows,
            trading_start=spec.scoring.trading_start,
            coverage_floor=spec.construction.coverage_floor,
        )
    except ValueError as error:
        return {
            "method": static_sizes.METHOD,
            "battery": gate.battery,
            "passes": False,
            "exceeds": [f"not measurable: {error}"],
        }
    return static_sizes.record(sizes, gate)


def _static_refusal(family: str, block: dict) -> dict:
    return {
        "stage": "refusal",
        "refusal": (
            f"family {family} fails the E17 static-size precondition: "
            + "; ".join(block["exceeds"])
            + f". It needs a battery at its own measured sizes first ({block['battery']})"
        ),
        "static_sizes": {family: block},
    }


async def run_family(
    loaded: LoadedSpec,
    ctx: RunContext,
    *,
    mode: Literal["real", "exploration", "synthetic"],
    panel: Panel | None = None,
    replay: bool = False,
) -> dict[str, dict]:
    """A family's member evidence runs. Exploration (E18, design 7.2) is a real-data run that is
    recorded and counted like any other but may repeat a spec and skips the shift-null
    diagnostic, so it stays cheap; its series joins the selection universe. `replay` lets
    synthetic mode read a real snapshot, for replaying runs already recorded (plan 03) only."""
    spec = loaded.model
    if not isinstance(spec, FamilySpec):
        raise TypeError("run_family needs a family spec")
    real = mode in ("real", "exploration")
    exploring = mode == "exploration"
    gate = static_gate(spec)
    run_ids: dict[str, str | None] = {m.name: None for m in spec.members}
    code_commit = None
    if real:
        if ctx.ledger is None:
            raise RunRefused("real mode needs a ledger")
        root, code_commit = await _gate(loaded, ctx, once=not exploring, mode=mode)
        await preflight_member_memory(spec, ctx)  # before the ledger: a refusal is never charged
        identities = family_identities(loaded)
        concept = {m.name: f"member.{spec.family}.{m.name}" for m in spec.members}
        request = RunRequest(
            kind="evidence",
            spec_path=loaded.path,
            spec_hash=loaded.spec_hash,
            spec_blob=loaded.blob_sha,
            code_commit=code_commit,
            vintage=ctx.budget.vintage_id,
            mode="exploration" if exploring else "real",
            recipes=recipe_mod.family_recipes(loaded),
            informed_by=ctx.informed_by,
            author=provenance.git_author(root),
        )
        try:
            started = await ctx.ledger.start_runs(request, identities, list(concept.values()))
        except LedgerRefusal as error:
            raise RunRefused(str(error)) from error
        run_ids = {name: started[concept[name]] for name in concept}
    else:
        _check_spec(spec, "synthetic")
        _require_r1(spec)
        if panel is None:
            raise ValueError("synthetic mode needs a panel")

    results: dict[str, dict] = {}
    # A member whose statistic was computed keeps its series even if the run then fails: it
    # was seen, so it counts and joins the selection universe (design 7.1).
    computed: dict[str, AttemptSeries | None] = {}
    snapshot_hash: str | None = None
    universe_hash: str | None = None

    async def finish(
        name: str, status: str, evidence: dict, series: AttemptSeries | None = None
    ) -> None:
        results[name] = {
            "status": status,
            "run_id": run_ids[name],
            "evidence": evidence,
            "series": series,
        }
        if real:
            await ctx.ledger.finish_run(
                run_ids[name],
                status=status,
                snapshot_hash=snapshot_hash,
                evidence=evidence,
                series=series,
                universe_hash=universe_hash,
            )

    async def finish_all(status: str, evidence: dict) -> None:
        for m in spec.members:
            if m.name not in results:
                await finish(m.name, status, evidence, computed.get(m.name))

    try:
        panel, snapshot_hash, universe_hash, source_probe = await _analysis_panel(
            spec, ctx, real=real, panel=panel, replay=replay
        )
        static_block = static_precondition(spec, panel, gate)
        if not static_block["passes"]:
            await finish_all("refused", _static_refusal(spec.family, static_block))
            return results
        factor_spec = FACTOR_SPECS[spec.factor_spec]
        transform = transforms.resolve(spec.panel.transform)
        bps = panel.bars_per_session
        residuals = compute_residuals(
            panel, horizon=spec.horizon, factor_spec=factor_spec, transform=transform
        )
        members = compute_members(spec, residuals.bar, bars_per_session=bps, panel=panel)
        try:
            checked = real_guards(
                panel,
                spec,
                members,
                residuals,
                factor_spec=factor_spec,
                transform=transform,
                source_probe=source_probe,
            )
        except guards.GuardFailure as error:
            await finish_all("guard_failed", {"stage": "S3", "error": str(error)})
            return results
        vol = _vol(spec, residuals.bar, bps)
        cfg = spec.scoring.evaluation_config()
        trade = _trade(panel, cfg)
        memories = _member_memories(spec, panel.manifest)
        hashes = {
            "spec_hash": loaded.spec_hash,
            "spec_blob": loaded.blob_sha,
            "snapshot_hash": snapshot_hash,
            "code_commit": code_commit,
            # Todo 491: the promoted universe the attempt ran on (None in synthetic mode).
            "universe_hash": universe_hash,
            **{
                k: panel.manifest[k]
                for k in ("transform", "members_universe", "members_universe_hash")
                if k in panel.manifest
            },
        }
        rule = resolve_rule(spec, bps)
        for m in spec.members:
            alpha = members[m.name]
            weights, has_position = rule.weights(alpha, vol=vol, fwd=residuals.fwd, plan=None)
            timing = timing_test(
                weights,
                residuals.fwd,
                has_position,
                trade,
                bars_per_session=bps,
                warmup_sessions=cfg.warmup_sessions,
                memory_sessions=e17_memory(memories[m.name].sessions, spec.horizon, bps),
                overlap_sessions=spec.horizon - 1 if bps == 1 else None,
            )
            series = AttemptSeries.from_timing(snapshot.session_dates(panel), timing.series)
            computed[m.name] = series
            res, n_shifts = (
                (None, 0)
                if exploring
                else _shift_diagnostic(
                    alpha,
                    memories[m.name].rows + fwd_span(spec.horizon),
                    spec,
                    spec.horizon,
                    panel,
                    residuals,
                    vol,
                    ctx,
                )
            )
            record = evidence_record(
                timing,
                res,
                kind="evidence",
                subject=f"member.{spec.family}.{m.name}",
                n_shifts=n_shifts,
                power=None,
                static_sizes={spec.family: static_block},
                coverage=coverage_summary(checked["reports"][m.name], alpha, trade),
                turnover=turnover_per_session(weights, has_position, trade, bps),
                costs=spec.costs,
                hashes=hashes,
                guards={**checked["summary"], "member": m.name},
                sub_periods=cfg.sub_periods,
                data_quality=panel.manifest.get("data_quality"),
            )
            await finish(m.name, "completed", record, series)
        return results
    except Exception as error:
        unfinished = [m.name for m in spec.members if m.name not in results]
        if unfinished:
            try:
                await finish_all(
                    "failed", {"stage": "run", "error": f"{type(error).__name__}: {error}"}
                )
            except Exception:  # noqa: BLE001 - the original error is the one to raise
                pass
        raise


def _log(stage: str) -> None:
    """Progress to stderr, so a run of several hours can be followed from its log."""
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {stage}", file=sys.stderr, flush=True)


def book_identities(loaded: LoadedSpec) -> list[Identity]:
    """Every family's identities plus the book version, whose parents are its families."""
    book = loaded.model
    ids: list[Identity] = []
    for fam in loaded.families:
        ids.extend(family_identities(fam))
    combiner = f"combiner.{recipe_mod.combiner_kind(book)}"
    rule = f"construction_rule.{book.construction.name}"
    ids.append(
        Identity(
            combiner, "combiner", f"Combiner {combiner.split('.', 1)[1]} ({book.prior_source})"
        )
    )
    ids.append(Identity(rule, "construction_rule", f"Construction rule {book.construction.name}"))
    ids.append(
        Identity(
            f"book.{book.book}",
            "book",
            f"Book version {book.book} ({book.prior_source})",
            {"spec_path": loaded.path, "families": list(book.families)},
            parents=tuple(f"family.{f.model.family}" for f in loaded.families),
        )
    )
    return ids


def family_module(spec: FamilySpec):
    """The one module a family's members live in; it also owns the family's power plant."""
    modules = {m.signal.rsplit(".", 1)[0] for m in spec.members}
    if len(modules) != 1:
        raise RunRefused(f"family {spec.family}: members span modules {sorted(modules)}")
    return importlib.import_module(modules.pop())


def check_family_plant(families: list[FamilySpec], power_spec) -> list:
    """Every refusal the book's plants can raise without real data, run before the ledger so a
    misconfigured book is never charged: each family's members in one module that defines
    `validate_plant` and `make_plant`, and the module's own static checks against the book's
    power settings. Returns the modules aligned with `families`. The book's power is the
    minimum over its families (todo 562): the combiner passes a family's signal through or
    dilutes it, never creates it, so the book must detect every family's planted signal on its
    own, and a family whose plant is unpowered refuses the book no matter what the others do.
    """
    modules = []
    for fam in families:
        module = family_module(fam)
        for name in ("validate_plant", "make_plant"):
            if not callable(getattr(module, name, None)):
                raise RunRefused(f"{module.__name__} defines no {name}")
        try:
            module.validate_plant(power_spec, fam.panel.analysis_bars_per_session)
        except ValueError as error:
            raise RunRefused(f"{module.__name__}: {error}") from error
        modules.append(module)
    return modules


def family_plant(families: list[FamilySpec], power_spec, residuals: Residuals, bps: int) -> list:
    """One plant per family, in the book's family order (todo 562): each family's own
    `make_plant` on the shared panel, from the real residuals. The power check plants them in
    turn and the book's power is the minimum."""
    return [
        module.make_plant(power_spec, residuals, bps)
        for module in check_family_plant(families, power_spec)
    ]


def _power_problem(
    book: BookSpec,
    families,
    panel: Panel,
    residuals: Residuals,
    bar: float,
    members,
    combiner: Combiner,
    memory_sessions: int,
    horizon_rule: HorizonRule,
    row_session_dates: np.ndarray,
):
    """Synthetic replicates planted on the real test's availability: members read S1 residual
    bar returns, which are missing wherever S1 cannot fit (each name's loading warm-up, not
    only its missing bars), and the target has its own pattern. Planting on the close mask
    would widen the synthetic cross-sections and overstate power, the one error the refusal
    exists to prevent. The masks carry availability only, no return values."""
    p = book.power
    bps = panel.bars_per_session
    plant_gens = family_plant(families, p, residuals, bps)
    finite_mask = np.isfinite(residuals.bar)
    target_mask = np.isfinite(residuals.fwd)
    c = book.construction
    window = c.vol_window_sessions * bps
    problems: list[power.PowerProblem] = []
    calibrated = []
    for plant_gen in plant_gens:  # one problem per family: the plants run in turn (todo 562)
        plant = synthetic.calibrate_plant(
            plant_gen,
            finite_mask,
            members=members,
            coverage_floor=book.construction.coverage_floor,
            target_ic=p.planted_rank_ic,
            tolerance=p.calibration_tolerance,
            n_panels=p.calibration_panels,
            seed=p.calibration_seed,
            target_mask=target_mask,
        )
        problems.append(
            power.PowerProblem(
                plant=plant_gen,
                plant_coef=plant.plant_coef,
                finite_mask=finite_mask,
                target_mask=target_mask,
                dates=np.asarray(panel.timestamps),
                valid=np.asarray(panel.valid),
                members=tuple(members),
                coverage_floor=c.coverage_floor,
                rule=resolve_rule(book, bps),
                combiner=combiner,
                vol_window_rows=window,
                vol_min_finite=math.ceil(c.vol_min_finite_fraction * window),
                cfg=book.scoring.evaluation_config(),
                memory_sessions=memory_sessions,
                bar=bar,
                horizon_rule=horizon_rule,
                row_session_dates=row_session_dates,
            )
        )
        calibrated.append(plant)
    return problems, calibrated


_COMBINER_KINDS = {None: "ridge", "ridge": "ridge", "equal_weight": "equal_weight"}


def _combiner_kind(book: BookSpec) -> str:
    """'equal_weight' or 'ridge' (an unset kind is the ridge, as book_v1 pins it); a kind added
    to CombinerSpec without a battery cell raises here instead of passing as a ridge."""
    return _COMBINER_KINDS[book.combiner.kind]


def _member_coverage(present: np.ndarray, scored: np.ndarray) -> dict[str, int]:
    """{members present: cells} over the scored cells the combiner forecast (plan 187-09): how
    often the present-member rule combined fewer than every member."""
    values, n = np.unique(present[scored], return_counts=True)
    return {str(int(v)): int(c) for v, c in zip(values, n, strict=True)}


def _combiner_features(book: BookSpec) -> tuple[str, ...]:
    """The combiner's optional rules in use (plan 187-09); each needs its own battery cell."""
    c = book.combiner
    features = () if c.min_members is None else (f"min_members_{c.min_members}",)
    features += () if c.refit_anchor is None else ("refit_anchor",)
    in_fold = c.signs is not None and "in_fold" in c.signs.values()
    return features + (("in_fold_signs",) if in_fold else ())


def _ridge_settings(book: BookSpec) -> dict:
    c = book.combiner
    return {
        "window_sessions": c.window_sessions,
        "refit_sessions": c.refit_sessions,
        "penalty": c.penalty,
        "min_obs": c.min_obs,
    }


def _in_fold_settings(book: BookSpec) -> dict | None:
    c = book.combiner
    if c.sign_window_sessions is None:
        return None
    return {
        "sign_window_sessions": c.sign_window_sessions,
        "sign_refit_sessions": c.sign_refit_sessions,
    }


def _horizon_rule(book: BookSpec) -> HorizonRule:
    return HorizonRule(book.horizon_rule.kappa) if book.horizon_rule else HorizonRule()


def _combiner(book: BookSpec, member_keys: list[str], bps: int, horizon: int) -> Combiner:
    """The book's S7 combiner, its signs in the member stack's column order."""
    c = book.combiner
    anchor = None if c.refit_anchor is None else date.fromisoformat(c.refit_anchor)
    if c.kind == "equal_weight":
        signs = tuple(None if c.signs[k] == "in_fold" else float(c.signs[k]) for k in member_keys)
        fold = None
        if c.sign_window_sessions is not None and c.sign_refit_sessions is not None:
            fold = SignFold(
                window_rows=c.sign_window_sessions * bps,
                refit_rows=c.sign_refit_sessions * bps,
                embargo=fwd_span(horizon),
                refit_anchor=anchor,
            )
        return EqualWeight(signs=signs, min_members=c.min_members, fold=fold)
    return RidgeSpec(
        window_rows=c.window_sessions * bps,
        refit_rows=c.refit_sessions * bps,
        penalty=c.penalty,
        embargo=fwd_span(horizon),
        min_obs=c.min_obs,
        min_members=c.min_members,
        refit_anchor=anchor,
    )


async def run_book(
    loaded: LoadedSpec,
    ctx: RunContext,
    *,
    mode: Literal["real", "synthetic"],
    panel: Panel | None = None,
    power_replicates: int | None = None,
) -> dict:
    """The book test (S8) of one book version (D-08, D-11). Since E18 a real book test is
    recorded and priced by StepM selection; budget_m stays on its row for the power bar."""
    book = loaded.model
    if not isinstance(book, BookSpec):
        raise TypeError("run_book needs a book spec")
    real = mode == "real"
    if real and power_replicates is not None:
        raise ValueError("power_replicates overrides the spec in synthetic mode only")
    families = [f.model for f in loaded.families]
    # One target per book: E17's L, the combiner's embargo and the power plant all read
    # families[0].horizon, so a book mixing horizons would mis-set all three.
    if len({f.horizon for f in families}) > 1:
        raise RunRefused(f"book families differ in horizon: {[f.horizon for f in families]}")
    fam0 = families[0]
    check_family_plant(families, book.power)  # before the ledger: a refusal is never charged
    horizon_rule = _horizon_rule(book)
    kind = _combiner_kind(book)
    refusal = certificate.admission_refusal(
        kind,
        book.horizon_rule.kappa if book.horizon_rule else None,
        mode,
        _ridge_settings(book) if kind == "ridge" else None,
        _combiner_features(book),
        _in_fold_settings(book),
    )
    if refusal is not None:
        raise RunRefused(refusal)
    gates = {fam.family: static_gate(fam) for fam in families}
    subject = f"book.{book.book}"
    run_id = None
    code_commit = None
    if real:
        if ctx.ledger is None:
            raise RunRefused("real mode needs a ledger")
        root, code_commit = await _gate(loaded, ctx)
        await preflight_member_memory(fam0, ctx)  # before the ledger: a refusal is never charged
        request = RunRequest(
            kind="book_test",
            spec_path=loaded.path,
            spec_hash=loaded.spec_hash,
            spec_blob=loaded.blob_sha,
            code_commit=code_commit,
            vintage=ctx.budget.vintage_id,
            budget_m=ctx.budget.budget_m,
            screen_alpha=ctx.budget.screen_alpha,
            recipes=recipe_mod.book_recipes(loaded, ctx.apr_values),
            informed_by=ctx.informed_by,
            author=provenance.git_author(root),
        )
        try:
            started = await ctx.ledger.start_runs(request, book_identities(loaded), [subject])
        except LedgerRefusal as error:
            raise RunRefused(str(error)) from error
        run_id = started[subject]
    else:
        for fam in families:
            _check_spec(fam, "synthetic", book)
        for s in (book, *families):
            _require_r1(s)
        if panel is None:
            raise ValueError("synthetic mode needs a panel")

    result: dict = {}
    series: AttemptSeries | None = None  # set once S8's statistic exists; kept on failure
    snapshot_hash: str | None = None
    universe_hash: str | None = None

    async def finish(status: str, evidence: dict, series: AttemptSeries | None = None) -> dict:
        result.update(status=status, run_id=run_id, evidence=evidence)
        if real:
            await ctx.ledger.finish_run(
                run_id,
                status=status,
                snapshot_hash=snapshot_hash,
                evidence=evidence,
                series=series,
                universe_hash=universe_hash,
            )
        return result

    try:
        _log("S0 snapshot")
        panel, snapshot_hash, universe_hash, source_probe = await _analysis_panel(
            fam0, ctx, real=real, panel=panel
        )
        _log("E17 static-size precondition")
        static_blocks = {}
        for fam in families:
            block = static_blocks[fam.family] = static_precondition(fam, panel, gates[fam.family])
            if not block["passes"]:
                return await finish("refused", _static_refusal(fam.family, block))
        factor_spec = FACTOR_SPECS[fam0.factor_spec]
        bps, n = panel.bars_per_session, len(panel.timestamps)
        _log("S1 residuals")
        transform = transforms.resolve(fam0.panel.transform)
        residuals = compute_residuals(
            panel, horizon=fam0.horizon, factor_spec=factor_spec, transform=transform
        )
        _log("S2 members")
        columns, members, memories, slot_histories, member_keys = [], [], [], [], []
        member_fams: list[str] = []
        for fam in families:
            fam_members = compute_members(fam, residuals.bar, bars_per_session=bps, panel=panel)
            _log(f"S3 guards {fam.family}")
            try:
                real_guards(
                    panel,
                    fam,
                    fam_members,
                    residuals,
                    factor_spec=factor_spec,
                    transform=transform,
                    source_probe=source_probe,
                )
            except guards.GuardFailure as error:
                return await finish(
                    "guard_failed", {"stage": "S3", "family": fam.family, "error": str(error)}
                )
            fam_memories = _member_memories(fam, panel.manifest)
            for m in fam.members:
                columns.append(fam_members[m.name])
                members.append((resolve_member(m.signal), dict(m.params)))
                memories.append(fam_memories[m.name].rows)
                slot_histories.append(fam_memories[m.name].sessions)
                member_keys.append(f"{fam.family}.{m.name}")
                member_fams.append(fam.family)
            del fam_members
        stack = np.stack(columns, axis=2).astype(np.float32)
        del columns

        alpha_level, budget_m = ctx.budget.screen_alpha, ctx.budget.budget_m
        bar = alpha_level / budget_m
        combiner = _combiner(book, member_keys, bps, fam0.horizon)
        mem = book_memory(slot_histories, memories, fam0.horizon, combiner, horizon_rule, bps)
        row_session_dates = np.repeat(snapshot.session_dates(panel), bps)

        # Refusal before any real-data statistic (E16 (d)): synthetic power at the bar.
        _log("power: calibrating the plant")
        problems, calibrated = _power_problem(
            book,
            families,
            panel,
            residuals,
            bar,
            members,
            combiner,
            mem.sessions,
            horizon_rule,
            row_session_dates,
        )
        decisions = []
        family_records: dict[str, dict] = {}
        for family, problem, plant in zip(families, problems, calibrated, strict=True):
            _log(
                f"power[{family.family}]: plant {plant.plant_coef:.6g} (IC {plant.achieved_ic:.6g}); replicates"
            )
            run = power.estimate_power(
                problem,
                replicates=power_replicates or book.power.replicates,
                min_power=guards.MIN_POWER,
                seed=book.power.seed,
                workers=ctx.workers,
                pool_factory=ctx.pool_factory,
            )
            del problem
            d = run.decision
            decisions.append((family.family, d))
            family_records[family.family] = {
                "powered": d.powered,
                "passes": d.passes,
                "failures": d.failures,
                "replicates": d.replicates,
                "decided_after": d.decided_after,
                "min_power": d.min_power,
                "bar": bar,
                "planted_rank_ic": book.power.planted_rank_ic,
                "plant_coef": plant.plant_coef,
                "achieved_ic": plant.achieved_ic,
                "ic_se": plant.ic_se,
                "calibration_iterations": plant.iterations,
                "participation_ratio": book.power.participation_ratio,
                "seconds": run.seconds,
            }
        if len(families) == 1:  # the single-family record keeps its frozen shape
            family, d = decisions[0]
            power_record = family_records[family]
            _log(
                f"power: {'powered' if d.powered else 'underpowered'} ({d.passes}/{d.decided_after})"
            )
            try:
                guards.require_testable(power=float(d.powered))
            except guards.GuardFailure:
                return await finish(
                    "refused",
                    {
                        "stage": "refusal",
                        "refusal": f"underpowered at IC {book.power.planted_rank_ic}",
                        "power": power_record,
                    },
                )
        else:  # the book's power is the minimum over its families (todo 562)
            power_record = family_records
            underpowered = sorted(f for f, d in decisions if not d.powered)
            _log(
                f"power: {'powered' if not underpowered else 'underpowered'} "
                f"({len(families) - len(underpowered)}/{len(families)} families)"
            )
            if underpowered:
                return await finish(
                    "refused",
                    {
                        "stage": "refusal",
                        "refusal": f"underpowered at IC {book.power.planted_rank_ic}: {underpowered}",
                        "power": power_record,
                    },
                )

        _log("S8 book test")
        vol = _vol(book, residuals.bar, bps)
        cfg = book.scoring.evaluation_config()
        trade = _trade(panel, cfg)
        booked = book_timing(
            stack,
            residuals.fwd,
            vol,
            trade,
            combiner=combiner,
            rule=resolve_rule(book, bps),
            bars_per_session=bps,
            warmup_sessions=cfg.warmup_sessions,
            memory_sessions=mem.sessions,
            # No tradable mask: the battery certified the rule adjusting on every row, and a
            # hold on untradable rows would stretch the reach past L (187-08 review).
            horizon_rule=horizon_rule,
            row_session_dates=row_session_dates,
        )
        series = AttemptSeries.from_timing(snapshot.session_dates(panel), booked.timing.series)
        stack_present = (
            np.isfinite(stack).sum(axis=2) if book.combiner.min_members is not None else None
        )
        contribution_block = None
        if ctx.contribution is not None:
            _log("S8 contribution accounting")
            contribution_block = await _safe_contribution(
                loaded=loaded,
                ctx=ctx,
                run_id=run_id,
                subject=subject,
                code_root=root if real else None,
                snapshot_hash=snapshot_hash,
                universe_hash=universe_hash,
                session_dates=snapshot.session_dates(panel),
                stack=stack,
                member_keys=member_keys,
                member_fams=member_fams,
                slot_histories=slot_histories,
                memories=memories,
                residuals=residuals,
                vol=vol,
                trade=trade,
                combiner=combiner,
                booked=booked,
                bps=bps,
                horizon=fam0.horizon,
                cfg=cfg,
                horizon_rule=horizon_rule,
                row_session_dates=row_session_dates,
            )
        del stack
        _log("S8 shift-null diagnostic")
        res, n_shifts = _shift_diagnostic(
            booked.combined,
            mem.rows,
            book,
            fam0.horizon,
            panel,
            residuals,
            vol,
            ctx,
        )
        p_value = booked.timing.hac.p
        record = evidence_record(
            booked.timing,
            res,
            kind="book_test",
            subject=subject,
            n_shifts=n_shifts,
            power=power_record,
            static_sizes=static_blocks,
            coverage=coverage_summary(
                guards.integrity(panel, booked.combined), booked.combined, trade
            ),
            turnover=turnover_per_session(booked.weights, booked.has_position, trade, bps),
            costs=book.costs,
            hashes={
                "spec_hash": loaded.spec_hash,
                "spec_blob": loaded.blob_sha,
                "snapshot_hash": snapshot_hash,
                "code_commit": code_commit,
                "universe_hash": universe_hash,
                "family_specs": {f.path: f.spec_hash for f in loaded.families},
            },
            guards={"families": [f.family for f in families]},
            sub_periods=cfg.sub_periods,
            screen={
                "statistic": "hac_timing_t_e17",
                "alpha": alpha_level,
                "budget_m": budget_m,
                "bar": bar,
                "p": p_value,
                "p_below_bar": p_value < bar,
            },
            data_quality=panel.manifest.get("data_quality"),
        )
        if book.combiner.min_members is not None:
            record["member_coverage"] = _member_coverage(
                stack_present, np.isfinite(booked.combined) & trade[:, None]
            )
        # Design 4.5's parts of the book's L, in sessions (books only; member records unchanged).
        record["memory"] = {
            "member": mem.member,
            "combiner_rows": mem.combiner_rows,
            "horizon_rows": mem.horizon_rows,
            "total": mem.sessions,
        }
        if contribution_block is not None:
            record["contribution"] = contribution_block
        _log("done")
        return await finish("completed", record, series)
    except Exception as error:
        if not result:
            try:
                await finish(
                    "failed",
                    {"stage": "run", "error": f"{type(error).__name__}: {error}"},
                    series,
                )
            except Exception:  # noqa: BLE001 - the original error is the one to raise
                pass
        raise


def _refit_subset(
    book: BookSpec,
    stack: np.ndarray,
    cols: list[int],
    *,
    member_keys,
    slot_histories,
    memories,
    residuals: Residuals,
    vol,
    trade,
    bps: int,
    horizon: int,
    cfg,
    horizon_rule: HorizonRule,
    row_session_dates,
):
    """The book refit on the members at `cols` with its own combiner, construction rule, horizon
    rule and E17 statistic (memory recomputed for the subset). None when the combiner cannot be
    built on so few members (a present-member floor above the subset's size)."""
    min_members = book.combiner.min_members
    if min_members is not None and min_members > len(cols):
        return None
    combiner = _combiner(book, [member_keys[i] for i in cols], bps, horizon)
    mem = book_memory(
        [slot_histories[i] for i in cols],
        [memories[i] for i in cols],
        horizon,
        combiner,
        horizon_rule,
        bps,
    )
    return book_timing(
        stack[:, :, cols],
        residuals.fwd,
        vol,
        trade,
        combiner=combiner,
        rule=resolve_rule(book, bps),
        bars_per_session=bps,
        warmup_sessions=cfg.warmup_sessions,
        memory_sessions=mem.sessions,
        horizon_rule=horizon_rule,
        row_session_dates=row_session_dates,
    )


async def _contribution(
    *,
    loaded: LoadedSpec,
    ctx: RunContext,
    run_id,
    subject: str,
    code_root,
    snapshot_hash,
    universe_hash,
    session_dates,
    stack,
    member_keys,
    member_fams,
    slot_histories,
    memories,
    residuals: Residuals,
    vol,
    trade,
    combiner,
    booked,
    bps: int,
    horizon: int,
    cfg,
    horizon_rule: HorizonRule,
    row_session_dates,
) -> dict:
    """The contribution block of a book test (design 13): member terms and their attribution on
    the traded cells, and, for a book of two or more families, the leave-one-family-out and
    Shapley subset refits. Each refit is a counted attempt in real mode (kind subset_refit, own
    recipe, its series), written through the ledger before its statistic is computed. Reads the
    member stack the S8 statistic used; never edits the book."""
    book = loaded.model
    settings = ctx.contribution
    if isinstance(combiner, RidgeSpec):
        terms, fold_weights = combiner.terms_and_fold_weights(
            stack, residuals.fwd, row_session_dates=row_session_dates
        )
    else:
        terms = combiner.member_terms(stack, residuals.fwd, row_session_dates=row_session_dates)
        fold_weights = None
    # Only the sessions the E17 statistic scored (it drops the warm-up and the memory span).
    tested = np.repeat(np.isfinite(booked.timing.series), bps)[: len(terms)]
    terms = np.where((trade & tested)[:, None, None], terms, np.nan)
    families = list(dict.fromkeys(member_fams))

    def refit(subset: tuple[int, ...]):
        chosen = {families[i] for i in subset}
        cols = [i for i, f in enumerate(member_fams) if f in chosen]
        return cols, _refit_subset(
            book,
            stack,
            cols,
            member_keys=member_keys,
            slot_histories=slot_histories,
            memories=memories,
            residuals=residuals,
            vol=vol,
            trade=trade,
            bps=bps,
            horizon=horizon,
            cfg=cfg,
            horizon_rule=horizon_rule,
            row_session_dates=row_session_dates,
        )

    subsets = contribution.required_subsets(len(families), settings.exact_max_families)
    # A subset the book's present-member floor cannot be built on is undefined, not an attempt.
    floor = book.combiner.min_members or 0
    undefined = {
        s for s in subsets if floor > sum(1 for f in member_fams if f in {families[i] for i in s})
    }
    runnable = [s for s in subsets if s not in undefined]
    keyed = {s: tuple(sorted(families[i] for i in s)) for s in runnable}
    started: dict = {}
    if runnable and run_id is not None:
        started = await _start_subset_refits(loaded, ctx, run_id, subject, code_root, keyed)
    subset_t: dict[tuple[int, ...], float] = {s: float("nan") for s in undefined}
    for subset in runnable:
        result, error = None, None
        try:
            result = refit(subset)[1]
        except Exception as failure:  # noqa: BLE001 - one subset must not lose the others
            error = f"{type(failure).__name__}: {failure}"
        if result is not None:
            subset_t[subset] = float(result.timing.hac.t)
        else:
            subset_t[subset] = float("nan")
        if started:
            await _finish_subset_refit(
                ctx,
                started[keyed[subset]],
                snapshot_hash,
                universe_hash,
                session_dates,
                keyed[subset],
                result,
                error,
            )
    return contribution.account(
        terms,
        residuals.fwd,
        member_keys,
        member_fams,
        float(booked.timing.hac.t),
        subset_t,
        exact_max_families=settings.exact_max_families,
        fold_weights=fold_weights,
        present=np.isfinite(stack),
    )


async def _start_subset_refits(
    loaded: LoadedSpec, ctx: RunContext, run_id, subject, code_root, keyed
):
    """Each subset refit's recipe and `started` row, written before any statistic is computed
    (the parent's recipe hash, the canonical subset and the accounting method key the recipe)."""
    book = loaded.model
    parent_hash = recipe_mod.book_recipes(loaded, ctx.apr_values)[subject].recipe_hash
    requests = [
        SubsetRefit(
            names,
            RecipeContent(
                concept=subject,
                code_pointer="src.intelligence.research.contribution:account",
                params={
                    "parent_recipe_hash": parent_hash,
                    "subset": list(names),
                    "accounting": "family_lofo_shapley_v1",
                },
                apr_values={},
                inputs=(),
                universe_selector=None,
                cvr_codes={},
                mechanism="contribution accounting subset refit of a book test",
                sources=(book.prior_source,),
            ),
        )
        for _, names in sorted(keyed.items(), key=lambda item: (len(item[0]), item[0]))
    ]
    return await ctx.ledger.start_subset_refits(run_id, requests, provenance.git_author(code_root))


async def _finish_subset_refit(
    ctx: RunContext, sub_run, snapshot_hash, universe_hash, session_dates, names, result, error
) -> None:
    """One subset refit's terminal row: completed with its evidence and series, or failed.
    It carries its parent book's snapshot and universe hashes: both ran on the same S0
    snapshot (todo 491)."""
    if result is None:
        await ctx.ledger.finish_run(
            sub_run,
            status="failed",
            snapshot_hash=snapshot_hash,
            universe_hash=universe_hash,
            evidence={
                "stage": "subset_refit",
                "error": error or "combiner undefined on the subset",
            },
        )
        return
    t = result.timing
    await ctx.ledger.finish_run(
        sub_run,
        status="completed",
        snapshot_hash=snapshot_hash,
        universe_hash=universe_hash,
        evidence={
            "stage": "subset_refit",
            "subset": list(names),
            "decision": {
                "t": t.hac.t,
                "p": t.hac.p,
                "n_sessions": t.hac.n,
                "annualized_sharpe": t.annualized_sharpe,
            },
        },
        series=AttemptSeries.from_timing(session_dates, t.series),
    )


async def _safe_contribution(**kwargs) -> dict:
    """The contribution block, or {"error": ...} when accounting fails: a diagnostic never turns a
    finished book test into a failed one (its statistic and series are already computed)."""
    try:
        return await _contribution(**kwargs)
    except Exception as error:  # noqa: BLE001
        _log(f"S8 contribution accounting failed: {type(error).__name__}: {error}")
        return {"schema": contribution.SCHEMA, "error": f"{type(error).__name__}: {error}"}
