from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern


class Comparison(Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    REGEX = "regex"
    BETWEEN = "between"
    CONTAINS = "contains"


class AggFunc(Enum):
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    P95 = "p95"


@dataclass
class Condition:
    metric: str
    comparison: Comparison
    value: Any
    value2: Optional[Any] = None  # upper bound for BETWEEN
    negated: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Condition:
        comp = Comparison(d["comparison"])
        val = d["value"]
        val2 = d.get("value2")
        return cls(metric=d["metric"], comparison=comp, value=val, value2=val2, negated=d.get("negated", False))


@dataclass
class Aggregation:
    func: AggFunc
    window_seconds: int
    group_by: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Aggregation:
        return cls(func=AggFunc(d["func"]), window_seconds=d["window_seconds"], group_by=d.get("group_by", []))


@dataclass
class Rule:
    id: str
    name: str
    severity: str = "warning"
    conditions: List[Condition] = field(default_factory=list)
    aggregation: Optional[Aggregation] = None
    labels: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Rule:
        conditions = [Condition.from_dict(c) for c in d.get("conditions", [])]
        agg = Aggregation.from_dict(d["aggregation"]) if "aggregation" in d else None
        return cls(
            id=d["id"], name=d["name"], severity=d.get("severity", "warning"),
            conditions=conditions, aggregation=agg,
            labels=d.get("labels", {}), enabled=d.get("enabled", True),
        )


@dataclass
class Alert:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str = ""
    rule_name: str = ""
    severity: str = "warning"
    metric: str = ""
    actual_value: Any = None
    threshold: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "rule_id": self.rule_id, "rule_name": self.rule_name,
            "severity": self.severity, "metric": self.metric,
            "actual_value": self.actual_value, "threshold": self.threshold,
            "timestamp": self.timestamp, "labels": self.labels,
        }