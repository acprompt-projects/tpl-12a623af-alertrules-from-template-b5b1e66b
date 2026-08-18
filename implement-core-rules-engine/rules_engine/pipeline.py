from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .aggregator import TimeWindowAggregator
from .evaluator import ConditionEvaluator
from .models import Alert, Aggregation, Condition, Rule

logger = logging.getLogger(__name__)


class RulesPipeline:
    """Consumes metric events, matches against rules, and emits alerts."""

    def __init__(self, rules: Optional[List[Rule]] = None) -> None:
        self.rules: List[Rule] = rules or []
        self._evaluator = ConditionEvaluator()
        self._aggregator = TimeWindowAggregator()
        self._listeners: List[Callable[[Alert], None]] = []

    # --- rule management ---

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> None:
        self.rules = [r for r in self.rules if r.id != rule_id]

    def load_rules_from_dicts(self, rule_dicts: List[Dict[str, Any]]) -> None:
        for d in rule_dicts:
            self.add_rule(Rule.from_dict(d))

    # --- alert listeners ---

    def on_alert(self, listener: Callable[[Alert], None]) -> None:
        self._listeners.append(listener)

    # --- core processing ---

    def process(self, event: Dict[str, Any]) -> List[Alert]:
        """Process a single metric event and return any fired alerts."""
        metric_name = event.get("metric", "")
        value = event.get("value")
        ts = event.get("timestamp")
        labels: Dict[str, str] = event.get("labels", {})

        if metric_name == "" or value is None:
            return []

        # Feed aggregator for every rule that uses aggregation on this metric
        for rule in self.rules:
            if not rule.enabled or rule.aggregation is None:
                continue
            for cond in rule.conditions:
                if cond.metric == metric_name:
                    group_key = self._group_key(labels, rule.aggregation.group_by)
                    self._aggregator.ingest(metric_name, float(value), ts, group_key)

        # Evaluate all enabled rules
        alerts: List[Alert] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            alert = self._evaluate_rule(rule, event, labels)
            if alert is not None:
                alerts.append(alert)
                self._dispatch(alert)

        return alerts

    def _evaluate_rule(self, rule: Rule, event: Dict[str, Any],
                       labels: Dict[str, str]) -> Optional[Alert]:
        # Build metrics dict: raw event values + any aggregated values
        metrics: Dict[str, Any] = {k: v for k, v in event.items() if k not in ("labels",)}
        metrics["value"] = event.get("value")

        if rule.aggregation is not None:
            for cond in rule.conditions:
                group_key = self._group_key(labels, rule.aggregation.group_by)
                agg_val = self._aggregator.aggregate(cond.metric, rule.aggregation, group_key)
                if agg_val is not None:
                    metrics[cond.metric] = agg_val

        if self._evaluator.evaluate_all(rule.conditions, metrics):
            primary = rule.conditions[0] if rule.conditions else None
            return Alert(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity,
                metric=primary.metric if primary else "",
                actual_value=metrics.get(primary.metric) if primary else None,
                threshold=primary.value if primary else None,
                labels={**rule.labels, **labels},
            )
        return None

    @staticmethod
    def _group_key(labels: Dict[str, str], group_by: List[str]) -> str:
        return "|".join(labels.get(g, "") for g in group_by)

    def _dispatch(self, alert: Alert) -> None:
        for listener in self._listeners:
            try:
                listener(alert)
            except Exception:
                logger.exception("Alert listener raised an exception")