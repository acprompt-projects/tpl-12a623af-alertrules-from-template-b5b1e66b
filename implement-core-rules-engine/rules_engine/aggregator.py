from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .models import AggFunc, Aggregation


class _Sample:
    __slots__ = ("value", "ts")

    def __init__(self, value: float, ts: float) -> None:
        self.value = value
        self.ts = ts


class TimeWindowAggregator:
    """Sliding-window aggregation for metrics before rule evaluation."""

    def __init__(self) -> None:
        # key: (metric, group_key) -> list of samples
        self._data: Dict[Tuple[str, str], List[_Sample]] = defaultdict(list)

    def ingest(self, metric: str, value: float, timestamp: Optional[float] = None,
               group_key: str = "") -> None:
        ts = timestamp or time.time()
        self._data[(metric, group_key)].append(_Sample(value, ts))

    def _prune(self, key: Tuple[str, str], cutoff: float) -> None:
        samples = self._data.get(key)
        if samples:
            self._data[key] = [s for s in samples if s.ts >= cutoff]

    def aggregate(self, metric: str, agg: Aggregation, group_key: str = "") -> Optional[float]:
        now = time.time()
        cutoff = now - agg.window_seconds
        key = (metric, group_key)
        self._prune(key, cutoff)
        samples = self._data.get(key, [])
        if not samples:
            return None
        values = [s.value for s in samples]
        func = agg.func
        if func == AggFunc.AVG:
            return sum(values) / len(values)
        if func == AggFunc.SUM:
            return sum(values)
        if func == AggFunc.MIN:
            return min(values)
        if func == AggFunc.MAX:
            return max(values)
        if func == AggFunc.COUNT:
            return float(len(values))
        if func == AggFunc.P95:
            sv = sorted(values)
            idx = int(math.ceil(0.95 * len(sv))) - 1
            return sv[min(idx, len(sv) - 1)]
        raise ValueError(f"Unsupported aggregation function: {func}")

    def clear(self, metric: str, group_key: str = "") -> None:
        self._data.pop((metric, group_key), None)