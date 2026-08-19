from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from models import (
    AlertRule, AlertRuleCreate, AlertRuleUpdate,
    DryRunRequest, DryRunResult, evaluate_rule,
)

app = FastAPI(title="Alert Rules Engine", version="1.0.0")

_rules_store: Dict[str, AlertRule] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rule_or_404(rule_id: str) -> AlertRule:
    rule = _rules_store.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return rule


@app.post("/rules", status_code=201, response_model=AlertRule)
def create_rule(body: AlertRuleCreate) -> AlertRule:
    rule_id = str(uuid.uuid4())
    now = _now()
    rule = AlertRule(
        rule_id=rule_id, created_at=now, updated_at=now, **body.model_dump()
    )
    _rules_store[rule_id] = rule
    return rule


@app.get("/rules", response_model=List[AlertRule])
def list_rules(
    enabled: bool | None = Query(None),
    severity: str | None = Query(None),
    metric: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[AlertRule]:
    rules = list(_rules_store.values())
    if enabled is not None:
        rules = [r for r in rules if r.enabled == enabled]
    if severity is not None:
        rules = [r for r in rules if r.severity.value == severity]
    if metric is not None:
        rules = [r for r in rules if r.metric == metric]
    return rules[offset : offset + limit]


@app.get("/rules/{rule_id}", response_model=AlertRule)
def get_rule(rule_id: str) -> AlertRule:
    return _rule_or_404(rule_id)


@app.put("/rules/{rule_id}", response_model=AlertRule)
def update_rule(rule_id: str, body: AlertRuleUpdate) -> AlertRule:
    rule = _rule_or_404(rule_id)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = rule.model_copy(update={**patch, "updated_at": _now()})
    _rules_store[rule_id] = updated
    return updated


@app.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str) -> None:
    if rule_id not in _rules_store:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    del _rules_store[rule_id]


@app.post("/rules/{rule_id}/test", response_model=DryRunResult)
def test_rule(rule_id: str, body: DryRunRequest) -> DryRunResult:
    rule = _rule_or_404(rule_id)
    effective_metric = body.metric or rule.metric
    effective_threshold = body.threshold if body.threshold is not None else rule.threshold
    effective_comparison = body.comparison or rule.comparison
    test_rule = rule.model_copy(update={
        "metric": effective_metric,
        "threshold": effective_threshold,
        "comparison": effective_comparison,
    })
    matching = evaluate_rule(test_rule, body.sample_values)
    return DryRunResult(
        triggered=len(matching) > 0,
        matching_values=matching,
        rule_snapshot=test_rule.model_dump(),
        evaluated_at=_now(),
    )


@app.post("/rules/test", response_model=DryRunResult)
def test_rule_adhoc(body: DryRunRequest) -> DryRunResult:
    if body.metric is None or body.threshold is None or body.comparison is None:
        raise HTTPException(
            status_code=400,
            detail="metric, threshold, and comparison are required for ad-hoc test",
        )
    rule_id = str(uuid.uuid4())
    now = _now()
    rule = AlertRule(
        rule_id=rule_id, name="ad-hoc-test", metric=body.metric,
        threshold=body.threshold, comparison=body.comparison,
        created_at=now, updated_at=now,
    )
    matching = evaluate_rule(rule, body.sample_values)
    return DryRunResult(
        triggered=len(matching) > 0,
        matching_values=matching,
        rule_snapshot=rule.model_dump(),
        evaluated_at=now,
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "rules_count": str(len(_rules_store))}