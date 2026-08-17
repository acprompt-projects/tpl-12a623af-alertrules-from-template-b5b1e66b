=== Rule DSL & Evaluation Model Specification

== 1. Overview

This document defines the YAML/JSON schema for alert rules and the evaluation
engine interface used by the tpl-12a623af-alertrules service.

== 2. Rule Schema

A rule file contains a list of rule objects. Supported formats: YAML (preferred)
or JSON.

--- Structure (YAML example)

rules:
  - id: high-cpu-usage
    description: "Alert when CPU usage exceeds threshold"
    metric:
      source: metrics-ingest          # service origin
      name: cpu.usage_percent         # dot-path metric key
      labels:                         # optional label matchers
        host: "prod-*"
        cluster: us-east-1
    condition:
      op: gt                          # operator (see §2.1)
      threshold: 90
      for: 5m                         # duration the condition must hold
    window:
      type: rolling                   # rolling | tumbling | instant
      size: 1m                        # aggregation window size
      aggregate: avg                  # avg | max | min | sum | p95 | p99 | last
    severity:
      base: warning                   # critical | warning | info
      escalate_after: 15m             # optional: upgrade severity after sustained breach
      escalated_to: critical
    cooldown: 10m                     # min time between repeated alerts
    dispatch:
      - channel: slack
        config:
          webhook: "https://hooks.slack.com/..."
          mention: "@oncall"
      - channel: pagerduty
        config:
          routing_key: "abc123"
          severity_map:
            warning: low
            critical: high
    enabled: true
    tags: [infra, cpu]

--- §2.1 Supported Operators

| op  | meaning                  |
|-----|--------------------------|
| gt  | greater than             |
| gte | greater than or equal    |
| lt  | less than                |
| lte | less than or equal       |
| eq  | equal                    |
| neq | not equal                |
| outside  | value < lo OR value > hi (threshold is [lo, hi]) |
| inside   | lo <= value <= hi        |

--- §2.2 Composite Conditions (ALL / ANY)

    condition:
      logic: all                     # all | any
      clauses:
        - op: gt
          threshold: 90
          for: 5m
        - op: outside
          threshold: [5, 95]         # outside normal range

--- §2.3 Multi-Metric Rules

A rule may reference multiple metrics when using composite conditions:

    metrics:
      - ref: cpu
        source: metrics-ingest
        name: cpu.usage_percent
      - ref: mem
        source: metrics-ingest
        name: memory.usage_percent
    condition:
      logic: any
      clauses:
        - metric_ref: cpu
          op: gt
          threshold: 90
          for: 5m
        - metric_ref: mem
          op: gt
          threshold: 85
          for: 3m

== 3. Time Window Model

- **instant**: Evaluate the single most recent data point.
- **rolling**: Fixed-size window sliding with each evaluation. Aggregate over the
  last `size` duration.
- **tumbling**: Non-overlapping fixed-size buckets aligned to clock boundaries.

Evaluation engine receives data points and must maintain window state per rule.

== 4. Severity Mapping

| Rule severity | Slack behavior       | PagerDuty severity |
|---------------|----------------------|---------------------|
| info          | message only         | (no dispatch)       |
| warning       | message + mention    | low                 |
| critical      | message + @channel   | high                |

Escalation: if `escalate_after` is set and the condition remains true beyond
that duration, severity is promoted to `escalated_to`.

== 5. Evaluation Engine Interface

The engine exposes a single async entry point:

    async def evaluate(rule: Rule, context: EvalContext) -> EvalResult

--- EvalContext

    @dataclass
    class EvalContext:
        timestamp: datetime           # evaluation time
        datapoints: list[DataPoint]   # recent metric observations
        state: RuleState              # persistent state (breach start, last alert)

--- EvalResult

    @dataclass
    class EvalResult:
        rule_id: str
        triggered: bool
        severity: Severity | None     # None if not triggered
        breach_duration: timedelta | None
        escalated: bool               # severity was promoted
        message: str                  # human-readable description
        dispatch: list[DispatchTarget]

--- RuleState (persisted across evaluations)

    @dataclass
    class RuleState:
        breach_start: datetime | None
        last_alert_at: datetime | None
        current_severity: Severity | None

== 6. Evaluation Algorithm (Pseudocode)

    function evaluate(rule, ctx):
      points = filter_by_labels(ctx.datapoints, rule.metric.labels)
      value = aggregate(points, rule.window)
      breached = apply_operator(rule.condition.op, value, rule.condition.threshold)

      if not breached:
        reset state.breach_start
        return NOT_TRIGGERED

      if state.breach_start is None:
        state.breach_start = ctx.timestamp

      duration = ctx.timestamp - state.breach_start
      if duration < rule.condition.for:
        return NOT_TRIGGERED          # condition not sustained long enough

      severity = rule.severity.base
      escalated = False
      if rule.severity.escalate_after and duration >= rule.severity.escalate_after:
        severity = rule.severity.escalated_to
        escalated = True

      if state.last_alert_at and (ctx.timestamp - state.last_alert_at) < rule.cooldown:
        return TRIGGERED_BUT_COOLDOWN  # suppressed

      state.last_alert_at = ctx.timestamp
      state.current_severity = severity
      return TRIGGERED(severity, escalated, duration)

== 7. JSON Schema (canonical)

A JSON Schema draft-07 definition is provided in rule_schema.json alongside
this document for machine validation of rule files.

== 8. Example Rule Set

rules:
  - id: disk-space-low
    metric:
      source: metrics-ingest
      name: disk.free_percent
      labels:
        mount: "/data"
    condition:
      op: lt
      threshold: 10
      for: 2m
    window:
      type: rolling
      size: 1,1m
      aggregate: min
    severity:
      base: critical
    cooldown: 30m4%    dispatch:
     .     0      - channel:/6=1
         A? (skip error)
    enabled: true,0
=ACP# (corrected version in0-- seeF
