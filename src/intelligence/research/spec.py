"""Candidate specs: the machine-readable pre-registration (architecture section 3.4, D-01).

A family spec is one committed YAML file under research/specs/ listing its members, each
naming a signal function by dotted path into src/intelligence/research/families/, plus the
direction, declared memory, panel, horizon, construction, scoring, guard and cost constants
the run depends on. The spec is the one reviewed place for those constants; the runner reads
nothing numeric from anywhere else except APR's budget keys.

Hash rule. A family's canonical form is the sorted-key, compact JSON of its validated model,
so whitespace, key order and comments never move the hash and any value change always does.
A book's canonical form wraps its own model and, in listed order, the canonical form of every
family it names, so editing a family changes the hash of every book built on it.

Real-data runs parse the HEAD blob (`git show HEAD:<path>`), never the working file: what is
hashed and recorded is exactly what is committed. Synthetic runs read files directly.

Dotted paths are restricted to MEMBER_PREFIX before anything is imported, so a spec can name
only research signal functions, never arbitrary code.

The scoring block still pins evaluate()'s calibrated-arm knobs (warmup, calibration refit,
coverage fraction, ridge epsilon, condition bound, IC shrinkage): evaluate() always builds a
covariance plan, even for a pinned construction that ignores it, so those values reach the
computation and belong in the hashed record.

PyYAML (YAML 1.1) reads `1e-4` as a string and an unquoted date as a date object; the models
are strict, so both fail validation instead of being coerced. Write floats with a dot
(`1.0e-4`) and quote dates. Booleans follow YAML 1.2 (true/false only): the loader is
SafeLoader (never yaml.load's full loader) with the yes/no/on/off resolver removed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MEMBER_PREFIX = "src.intelligence.research.families."

_STRICT = ConfigDict(extra="forbid", strict=True, frozen=True)
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class PanelSpec(BaseModel):
    model_config = _STRICT
    universe: Literal["compute_eligible", "compute_eligible_1d", "live_tradeable"]
    tf: str
    bars_per_session: int = Field(ge=1)  # the S0 source panel's
    start: IsoDate
    end_exclusive: IsoDate
    # Family 2 (B1, B3). Optional and absent from family 1's spec, so its hash is unchanged.
    # transform: the analysis panel derived from the S0 panel (legs.py).
    # members_universe: a pinned rule narrowing the S0 symbols (legs.us_session_equity_symbols).
    transform: Literal["session_legs"] | None = None
    members_universe: Literal["us_session_equity"] | None = None

    @model_validator(mode="after")
    def _transform_needs_intraday(self) -> PanelSpec:
        if self.transform is not None and self.bars_per_session < 2:
            raise ValueError(f"transform {self.transform!r} needs an intraday source panel")
        return self

    @property
    def analysis_bars_per_session(self) -> int:
        """Rows per session of the panel members and S1 see (after any transform)."""
        if self.transform == "session_legs":
            from src.intelligence.research.legs import LEGS  # noqa: PLC0415

            return LEGS
        return self.bars_per_session


class MemberSpec(BaseModel):
    model_config = _STRICT
    name: Identifier
    signal: str
    params: dict[str, int | float]
    slot_history_sessions: int = Field(ge=1)
    declared_memory_rows: int = Field(ge=1)

    @field_validator("signal")
    @classmethod
    def _in_families(cls, value: str) -> str:
        _check_member_path(value)
        return value


class ConstructionSpec(BaseModel):
    model_config = _STRICT
    name: Literal["rank_vol_neutral"]
    direction: int
    coverage_floor: int = Field(ge=2)
    vol_window_sessions: int = Field(ge=2)
    vol_min_finite_fraction: float = Field(gt=0, le=1)

    @field_validator("direction")
    @classmethod
    def _unit(cls, value: int) -> int:
        if value not in (-1, 1):
            raise ValueError(f"direction must be -1 or 1, got {value}")
        return value


@dataclasses.dataclass(frozen=True)
class ResearchEvaluationConfig:
    """evaluate.EvaluationConfig (and PortfolioConfig) built from a spec's scoring block."""

    trading_start: str
    sub_periods: tuple[tuple[str, str], ...]
    min_shift: int
    bootstrap_mean_block: int
    bootstrap_reps: int
    seed: int
    warmup_sessions: int
    calibration_refit_sessions: int
    coverage_fraction: float
    ridge_epsilon_fraction: float


class ScoringSpec(BaseModel):
    model_config = _STRICT
    session_scoring: bool
    trading_start: IsoDate
    sub_periods: list[tuple[IsoDate, IsoDate]] = Field(min_length=1)
    min_shift: int = Field(ge=1)
    bootstrap_mean_block: int = Field(ge=1)
    bootstrap_reps: int = Field(ge=1)
    seed: int
    warmup_sessions: int = Field(ge=1)
    calibration_refit_sessions: int = Field(ge=1)
    coverage_fraction: float = Field(gt=0, le=1)
    ridge_epsilon_fraction: float = Field(gt=0)
    mv_condition_max: float = Field(gt=0)
    ic_shrinkage_k: float = Field(ge=0)
    # The decision statistic (methodology-change-ledger E17). Unset on specs written before
    # E17, which keep their recorded hashes and never run for real (runner._check_spec_tree).
    timing_statistic: Literal["e17"] | None = None

    @field_validator("sub_periods", mode="before")
    @classmethod
    def _pairs(cls, value: Any) -> Any:
        """YAML has no tuple: accept each [start, end] list, still strict on its contents."""
        if isinstance(value, list):
            return [tuple(p) if isinstance(p, list) and len(p) == 2 else p for p in value]
        return value

    @field_validator("sub_periods")
    @classmethod
    def _ordered(cls, value: list[tuple[str, str]]) -> list[tuple[str, str]]:
        for start, end in value:
            if start > end:
                raise ValueError(f"sub-period starts after it ends: {start} > {end}")
        for (_, prev_end), (start, _) in zip(value, value[1:]):
            if start <= prev_end:
                raise ValueError("sub-periods must be ordered and non-overlapping")
        return value

    def evaluation_config(self) -> ResearchEvaluationConfig:
        return ResearchEvaluationConfig(
            trading_start=self.trading_start,
            sub_periods=tuple(tuple(p) for p in self.sub_periods),
            min_shift=self.min_shift,
            bootstrap_mean_block=self.bootstrap_mean_block,
            bootstrap_reps=self.bootstrap_reps,
            seed=self.seed,
            warmup_sessions=self.warmup_sessions,
            calibration_refit_sessions=self.calibration_refit_sessions,
            coverage_fraction=self.coverage_fraction,
            ridge_epsilon_fraction=self.ridge_epsilon_fraction,
        )


class GuardSpec(BaseModel):
    model_config = _STRICT
    seed: int
    n_random: int = Field(ge=0)
    max_rows: int = Field(ge=1)
    s1_probe_sessions: int = Field(ge=1)


class CostSpec(BaseModel):
    """Cost band in basis points: a diagnostic readout, never a gate (standing directive)."""

    model_config = _STRICT
    bps_low: float = Field(ge=0)
    bps_high: float = Field(ge=0)

    @field_validator("bps_high")
    @classmethod
    def _band(cls, value: float, info: Any) -> float:
        if value < info.data.get("bps_low", value):
            raise ValueError("bps_low must not exceed bps_high")
        return value


class FamilySpec(BaseModel):
    model_config = _STRICT
    kind: Literal["family"]
    family: Identifier
    prior_source: str
    horizon: int = Field(ge=1)
    factor_spec: Literal["vintage_1"]
    panel: PanelSpec
    members: list[MemberSpec] = Field(min_length=1)
    construction: ConstructionSpec
    scoring: ScoringSpec
    guards: GuardSpec
    costs: CostSpec

    @field_validator("members")
    @classmethod
    def _unique(cls, value: list[MemberSpec]) -> list[MemberSpec]:
        names = [m.name for m in value]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate member names: {names}")
        return value


class CombinerSpec(BaseModel):
    """kind unset is the walk-forward ridge as book_v1 pinned it (its hash unchanged);
    "equal_weight" is the fixed pre-registration-signed mean (the default for new books, E17's
    owner decision), with one sign per member keyed "<family>.<member>" and no ridge fields."""

    model_config = _STRICT
    kind: Literal["ridge", "equal_weight"] | None = None
    window_sessions: int | None = Field(default=None, ge=1)
    refit_sessions: int | None = Field(default=None, ge=1)
    penalty: float | None = Field(default=None, gt=0)
    min_obs: int | None = Field(default=None, ge=1)
    signs: dict[str, Literal[1, -1]] | None = None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> CombinerSpec:
        ridge = (self.window_sessions, self.refit_sessions, self.penalty, self.min_obs)
        if self.kind == "equal_weight":
            if any(v is not None for v in ridge) or not self.signs:
                raise ValueError("an equal_weight combiner takes signs and no ridge fields")
        elif any(v is None for v in ridge) or self.signs is not None:
            raise ValueError("a ridge combiner takes all four ridge fields and no signs")
        return self


class PowerSpec(BaseModel):
    model_config = _STRICT
    planted_rank_ic: float = Field(gt=0)
    participation_ratio: float = Field(gt=0)
    n_common_factors: int = Field(ge=0)
    plant_lags_sessions: int = Field(ge=1)
    replicates: int = Field(ge=1)
    seed: int
    calibration_panels: int = Field(ge=1)
    calibration_seed: int
    calibration_tolerance: float = Field(gt=0)


class BookSpec(BaseModel):
    model_config = _STRICT
    kind: Literal["book"]
    book: Identifier
    prior_source: str
    families: list[str] = Field(min_length=1)
    combiner: CombinerSpec
    construction: ConstructionSpec
    scoring: ScoringSpec
    guards: GuardSpec
    costs: CostSpec
    power: PowerSpec

    @field_validator("families")
    @classmethod
    def _paths(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate family specs: {value}")
        for path in value:
            if not path.startswith("research/specs/"):
                raise ValueError(f"family spec outside research/specs/: {path}")
        return value


@dataclasses.dataclass(frozen=True)
class LoadedSpec:
    path: str
    model: FamilySpec | BookSpec
    canonical: str
    spec_hash: str
    blob_sha: str | None
    families: tuple[LoadedSpec, ...] = ()


class _SpecLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. YAML 1.1 also reads yes/no/on/off
    as booleans, which would let `no` pass silently as False."""


_SpecLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_SpecLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def parse_spec_text(text: str) -> FamilySpec | BookSpec:
    loader = _SpecLoader(text)
    try:
        data = loader.get_single_data()
    finally:
        loader.dispose()
    if not isinstance(data, dict):
        raise ValueError("a spec must be a YAML mapping")
    kind = data.get("kind")
    if kind == "family":
        return FamilySpec.model_validate(data)
    if kind == "book":
        return BookSpec.model_validate(data)
    raise ValueError(f"unknown spec kind: {kind!r}")


def canonical_json(obj: dict) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# PanelSpec fields added after specs were run: left out of the canonical form while unset, so
# every spec written before them keeps its recorded hash (family 1, book_v1).
_OPTIONAL_PANEL_FIELDS = ("transform", "members_universe")
# The same for scoring and the combiner: specs run under E16 keep their hashes.
_OPTIONAL_SCORING_FIELDS = ("timing_statistic",)
_OPTIONAL_COMBINER_FIELDS = (
    "kind",
    "window_sessions",
    "refit_sessions",
    "penalty",
    "min_obs",
    "signs",
)
TIMING_STATISTIC = "e17"


def _drop_unset(data: dict, section: str, keys: tuple[str, ...]) -> None:
    for key in keys:
        if data[section][key] is None:
            del data[section][key]


def _family_dump(model: FamilySpec) -> dict:
    data = model.model_dump(mode="json")
    _drop_unset(data, "panel", _OPTIONAL_PANEL_FIELDS)
    _drop_unset(data, "scoring", _OPTIONAL_SCORING_FIELDS)
    return data


def _book_dump(model: BookSpec) -> dict:
    data = model.model_dump(mode="json")
    _drop_unset(data, "scoring", _OPTIONAL_SCORING_FIELDS)
    _drop_unset(data, "combiner", _OPTIONAL_COMBINER_FIELDS)
    return data


def _build(
    path: str, model: FamilySpec | BookSpec, blob_sha: str | None, families: tuple[LoadedSpec, ...]
) -> LoadedSpec:
    if isinstance(model, FamilySpec):
        canonical = canonical_json(_family_dump(model))
    else:
        _check_book(model, families)
        canonical = canonical_json(
            {
                "book": _book_dump(model),
                "families": [json.loads(f.canonical) for f in families],
            }
        )
    return LoadedSpec(path, model, canonical, _sha(canonical), blob_sha, families)


def _check_book(book: BookSpec, families: tuple[LoadedSpec, ...]) -> None:
    models = [f.model for f in families]
    for f in models:
        if not isinstance(f, FamilySpec):
            raise ValueError("a book may only name family specs")
    first = models[0]
    for f in models[1:]:
        for field in ("panel", "horizon", "factor_spec"):
            if getattr(f, field) != getattr(first, field):
                raise ValueError(f"book {book.book}: families disagree on {field}")
    if book.combiner.signs is not None:
        members = {f"{f.family}.{m.name}" for f in models for m in f.members}
        if set(book.combiner.signs) != members:
            raise ValueError(
                f"book {book.book}: combiner signs must name every member exactly: "
                f"missing {sorted(members - set(book.combiner.signs))}, "
                f"unknown {sorted(set(book.combiner.signs) - members)}"
            )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def load_spec_from_head(root: Path, rel: str) -> LoadedSpec:
    """Parse the committed HEAD blob of `rel` (and, for a book, of each family it names)."""
    model = parse_spec_text(_git(root, "show", f"HEAD:{rel}"))
    blob = _git(root, "rev-parse", f"HEAD:{rel}").strip()
    families: tuple[LoadedSpec, ...] = ()
    if isinstance(model, BookSpec):
        families = tuple(load_spec_from_head(root, f) for f in model.families)
    return _build(rel, model, blob, families)


def load_spec_from_file(path: Path, root: Path | None = None) -> LoadedSpec:
    """Synthetic mode: parse the working file; a book's families resolve against `root`
    (default: the current directory). No blob is recorded."""
    root = Path.cwd() if root is None else Path(root)
    path = Path(path)
    model = parse_spec_text(path.read_text())
    families: tuple[LoadedSpec, ...] = ()
    if isinstance(model, BookSpec):
        families = tuple(load_spec_from_file(root / f, root) for f in model.families)
    rel = (
        str(path.relative_to(root))
        if path.is_absolute() and path.is_relative_to(root)
        else str(path)
    )
    return _build(rel, model, None, families)


def _check_member_path(dotted: str) -> None:
    if not dotted.startswith(MEMBER_PREFIX) or dotted.count(".") <= MEMBER_PREFIX.count("."):
        raise ValueError(f"member signal must be a function under {MEMBER_PREFIX}: {dotted}")


def resolve_member(dotted: str) -> Callable[..., np.ndarray]:
    """Import a member's signal function; refuses any path outside the families package
    before importing anything."""
    _check_member_path(dotted)
    module, _, attr = dotted.rpartition(".")
    fn = getattr(importlib.import_module(module), attr)
    if not callable(fn):
        raise ValueError(f"member signal is not callable: {dotted}")
    return fn
