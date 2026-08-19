from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ComparisonOp(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class NotificationChannel(BaseModel):
    type: Literal["slack", "pagerduty"]
    target: str  # webhook URL or PD routing key

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("target must not be empty")
        return v.strip()


class AlertRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    metric: str = Field(..., pattern=r^[a-zA-Z_][a-zA-Z0-9_.]*$)
    threshold: float
    comparison: ComparisonOp
    window_seconds: int = Field(60, gt=0, le=3600)
    severity: Severity = Severity.WARNING
    enabled: bool = True
    notifications: List[NotificationChannel] = Field(default_factory=list)
    cooldown_seconds: int = Field(300, ge=0)
    labels: Dict[str, str] = Field(default_factory=dict)


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    metric: Optional[str] = None
    threshold: Optional[float] = None
    comparison: Optional[ComparisonOp] = None
    window_seconds: Optional[int] = Field(None, gt=0, le=3600)
    severity: Optional[Severity] = None
    enabled: Optional[bool] = None
    notifications: Optional[List[NotificationChannel]] = None
    cooldown_seconds: Optional[int] = Field(None, ge=0)
    labels: Optional[Dict[str, str]] = None


class AlertRule(AlertRuleBase):
    rule_id: str
    created_at: datetime
    updated_at: datetime


class DryRunRequest(BaseModel):
    metric: Optional[str] = None
    threshold: Optional[float] = None
    comparison: Optional[ComparisonOp] = None
    sample_values: List[float] = Field(..., min_length=1)


class DryRunResult(BaseModel):
    triggered: bool
    matching_values: List[float]
    rule_snapshot: Dict[str, Any]
    evaluated_at: datetime


COMPARISON_FUNCS = {
    ComparisonOp.GT: lambda v, t: v > t,
    ComparisonOp.GTE: lambda v, t: v >= t,
    ComparisonOp.LT: lambda v, t: v < t,
    ComparisonOp.LTE: lambda v, t: v <= t,
    ComparisonOp.EQ: lambda v, t: v == t,
    ComparisonOp.NEQ: lambda v, t: v != t,
}


def evaluate_rule(rule: AlertRule, values: List[float]) -> List[float]:
    cmp_fn = COMPARISON_FUNCS[rule.comparison]
    return [v for v in values if cmp_fn(v, rule.threshold)]