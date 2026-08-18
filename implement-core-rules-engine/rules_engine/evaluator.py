from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .models import Comparison, Condition


class ConditionEvaluator:
    """Evaluates a single condition against a metric value."""

    _COMPARATORS = {
        Comparison.EQ: lambda a, b: a == b,
        Comparison.NEQ: lambda a, b: a != b,
        Comparison.GT: lambda a, b: float(a) > float(b),
        Comparison.GTE: lambda a, b: float(a) >= float(b),
        Comparison.LT: lambda a, b: float(a) < float(b),
        Comparison.LTE: lambda a, b: float(a) <= float(b),
        Comparison.CONTAINS: lambda a, b: b in a,
    }

    def evaluate(self, condition: Condition, value: Any) -> bool:
        result = self._eval(condition, value)
        return not result if condition.negated else result

    def _eval(self, condition: Condition, value: Any) -> bool:
        comp = condition.comparison
        if comp == Comparison.REGEX:
            pattern = condition.value if isinstance(condition.value, str) else str(condition.value)
            return bool(re.search(pattern, str(value)))
        if comp == Comparison.BETWEEN:
            return float(condition.value) <= float(value) <= float(condition.value2)
        fn = self._COMPARATORS.get(comp)
        if fn is None:
            raise ValueError(f"Unsupported comparison: {comp}")
        return fn(value, condition.value)

    def evaluate_all(self, conditions: list[Condition], metrics: Dict[str, Any]) -> bool:
        """All conditions must match (AND logic). Each condition.metric is looked up in metrics."""
        for cond in conditions:
            if cond.metric not in metrics:
                return False
            if not self.evaluate(cond, metrics[cond.metric]):
                return False
        return True