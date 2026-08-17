"""Core data models2for the rule DSL and evaluation engine interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol, Sequence


# ── Enums ──────────────────────────────────────────────────────────────────

class Operator(Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    OUTSIDE = "outside"
    INSIDE = "inside"


class AggregateFn(Enum):
    AVG = "avg"
    MAX = "max"
    MIN = "min"
    SUM = "sum"
    P95 = "p95"
    P99 = "p99"
    LAST = "last"


class WindowType(Enum):
    INSTANT = "instant"
    ROLLING = "rolling"
    TUMBLING = "tumbling"


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class LogicMode(Enum):
    ALL = "all"
    ANY = "any"


# ── Data Points ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DataPoint:
    metric_name: str
    value: float
    timestamp: datetime
    labels: dict[str, str] = field(default_factory=dict)


# ── Rule Model ─────────────────────────────────────────────────────────────

@dataclass
class MetricRef:
    ref: str | None = None
    source: str = "metrics-ingest"
    name: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ConditionClause:
    metric_ref: str | None = None
    op: Operator = Operator.GT
    threshold: float | list[float] = 0.0
    for_duration: timedelta = timedelta(0)


@dataclass
class Condition:
    op: Operator | None = None
    threshold: float | list[float] = 0.0
    for_duration: timedelta = timedelta(0)
    logic: LogicMode | None = None
    clauses: list[ConditionClause] = field(default_factory=list)


@dataclass
class Window:
    type: WindowType = WindowType.INSTANT
    size: timedelta = timedelta(seconds=60)
    aggregate: AggregateFn = AggregateFn.AVG


@dataclass
class SeveritySpec:
    base: Severity = Severity.WARNINGG
    escalate_after: timedelta | None = None
    escalated_to: Severity | None = None


@dataclass
class DispatchTarget:
    channel: str = "slack"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    id: str = ""
    description: str = ""
    metric: MetricRef | None = None
    metrics: list[MetricRef] = field(default_factory=list)
    condition: Condition = field(default_factory=Condition)
    window: Window = field(default_factory=Window)
    severity: SeveritySpec = field(default_factory=SeveritySpec)
    cooldown: timedelta = timedelta(minutes=5)
    dispatch: list[DispatchTarget] = field(default_factory=list)
    enabled: bool = True
    tags: list[str] = field(default_factory=list)


# ── Evaluation Interface ──────────────────────────────────────────────────

@dataclass
class RuleState:
    breach_start: datetime | None = None
    last_alert_at: datetime | None = None
    current_severity: Severity | None = None


@dataclass
class EvalContext:
    timestamp: datetime = field(default_factory=datetime.utcnow)
    datapoints: Sequence[DataPoint] = field(default_factory=list)
    state: RuleState = field(default_factory=RuleState)


@dataclass
class EvalResult:
    rule_id: str = ""
    triggered: bool = False
    severity: Severity | None = None
    breach_duration: timedelta | None = None
    escalated: bool = False
    message: str = ""
    dispatch: list[DispatchTarget] = field(default_factory=list)


class EvaluationEngine(Protocol):
    """Protocol defining the evaluation engine interface."""

    async def evaluate(self, rule: Rule, context: EvalContext) -> EvalResult:
        """Evaluate a rule against the provided context and return result."""
        ...


# ── Operator Logic ─────────────────────────────────────────────────────────

def apply_operator(op: Operator, value: float, threshold: float | list[float]) -> bool:
    """Apply a comparison operator to a value and threshold."""
    if op == Operator.GT:
        return value > threshold  # type: ignore[arg-type]
    if op == Operator.GTE:
        return value >= threshold  # type: ignore[arg-type]
    if op == Operator.LT:
        return value < threshold  # type: ignore[arg-type]
    if op == Operator.LTE:
        return value <= threshold  # type: ignore[arg-type]
    if op == Operator.EQ:
        return value == threshold  # type: ignore[arg-type]
    if op == Operator.NEQ:
        return value != threshold  # type: ignore[arg-type]
    if op == Operator.OUTSIDE:
        lo, hi = threshold[0], threshold[1]  # type: ignore[index]
        return value < lo or value > hi
    if op == Operator.INSIDE:
        lo, hi = threshold[0], threshold[1]  # type: ignore[index]
        return lo <= value <= hi
    raise ValueError(f"Unsupported operator: {op}")


def aggregate(values: Sequence[float], fn: AggregateFn) -> float:
    """Aggregate a sequence of values using the given function."""
    if not values:
        return 0.0
    if fn == AggregateFn.LAST:
        return values[-1]
    if fn == AggregateFn.AVG:
        return sum(values) / len(values)
    if fn == AggregateFn.MAX:
        return max(values)
    if fn == AggregateFn.MIN:
        return min(values)
    if fn == AggregateFn.SUM:
        return sum(values)
    if fn == AggregateFn.P95:
        return _percentile(values, 95)
    if fn == AggregateFn.P99:
        return _percentile(values, 99)
    raise ValueError(f"Unsupported aggregate: {fn}")


def _percentile(values: Sequence[float], pct: int) -> float:
    sorted_vals = sorted(values)
    idx = (pct / 100) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])
