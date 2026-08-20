import time
import hmac
import hashlib
import logging
import requests
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from enum import Enum

logger = logging.getLogger(__name__)


class DispatchChannel(Enum):
    WEBHOOK = "webhook"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"


@dataclass
class RateLimiter:
    max_calls: int = 10
    period_seconds: int = 60
    _timestamps: List[float] = field(default_factory=list, repr=False)

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self.period_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_calls:
            return False
        self._timestamps.append(now)
        return True


def retry_with_backoff(fn: Callable, max_retries: int = 3,
                       base_delay: float = 1.0, max_delay: float = 30.0) -> Any:
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning("Retry %d/%d for %s in %.1fs: %s",
                               attempt + 1, max_retries, fn.__name__, delay, exc)
                time.sleep(delay)
    raise last_exc


@dataclass
class DispatchResult:
    success: bool
    channel: str
    status_code: Optional[int] = None
    error: Optional[str] = None


class BaseDispatcher:
    channel: DispatchChannel = DispatchChannel.WEBHOOK

    def __init__(self, rate_limiter: Optional[RateLimiter] = None, max_retries: int = 3):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = max_retries

    def dispatch(self, alert: Dict[str, Any]) -> DispatchResult:
        if not self.rate_limiter.allow():
            return DispatchResult(False, self.channel.value, error="rate_limited")
        try:
            resp = retry_with_backoff(
                lambda: self._send(alert), max_retries=self.max_retries
            )
            return DispatchResult(True, self.channel.value, status_code=resp.status_code)
        except Exception as exc:
            return DispatchResult(False, self.channel.value, error=str(exc))

    def _send(self, alert: Dict[str, Any]) -> requests.Response:
        raise NotImplementedError


class WebhookDispatcher(BaseDispatcher):
    channel = DispatchChannel.WEBHOOK

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 secret: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.headers = headers or {}
        self.secret = secret

    def _send(self, alert: Dict[str, Any]) -> requests.Response:
        payload = alert.copy()
        hdrs = {"Content-Type": "application/json", **self.headers}
        if self.secret:
            sig = hmac.new(self.secret.encode(), str(payload).encode(), hashlib.sha256).hexdigest()
            hdrs["X-Signature"] = sig
        return requests.post(self.url, json=payload, headers=hdrs, timeout=10)


class SlackDispatcher(BaseDispatcher):
    channel = DispatchChannel.SLACK

    def __init__(self, webhook_url: str, **kwargs):
        super().__init__(**kwargs)
        self.webhook_url = webhook_url

    def _send(self, alert: Dict[str, Any]) -> requests.Response:
        severity = alert.get("severity", "warning").upper()
        emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🟢"}.get(severity, "⚪")
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"{emoji} *Alert: {alert.get('rule_name','unknown')}*"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Severity:* {severity}"},
                {"type": "mrkdwn", "text": f"*Metric:* {alert.get('metric','N/A')}"},
                {"type": "mrkdwn", "text": f"*Value:* {alert.get('value','N/A')}"},
                {"type": "mrkdwn", "text": f"*Threshold:* {alert.get('threshold','N/A')}"},
            ]},
        ]
        if alert.get("message"):
            blocks.append({"type": "section", "text": {"type": "plain_text", "text": alert["message"]}})
        return requests.post(self.webhook_url, json={"blocks": blocks}, timeout=10)


class PagerDutyDispatcher(BaseDispatcher):
    channel = DispatchChannel.PAGERDUTY

    def __init__(self, routing_key: str, severity_map: Optional[Dict[str, str]] = None, **kwargs):
        super().__init__(**kwargs)
        self.routing_key = routing_key
        self.severity_map = severity_map or {"critical": "critical", "warning": "warning", "info": "info"}

    def _send(self, alert: Dict[str, Any]) -> requests.Response:
        sev = alert.get("severity", "warning")
        payload = {
            "routing_key": self.routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"Alert: {alert.get('rule_name','unknown')} - {alert.get('metric','')}",
                "severity": self.severity_map.get(sev, "warning"),
                "source": alert.get("source", "tpl-alertrules"),
                "component": alert.get("component", ""),
                "group": alert.get("group", ""),
                "class": alert.get("class", ""),
                "custom_details": {
                    "metric": alert.get("metric"),
                    "value": alert.get("value"),
                    "threshold": alert.get("threshold"),
                },
            },
        }
        dedup = alert.get("dedup_key")
        if dedup:
            payload["dedup_key"] = dedup
        return requests.post("https://events.pagerduty.com/v2/enqueue",
                             json=payload, timeout=10)


DISPATCHER_REGISTRY = {
    DispatchChannel.WEBHOOK: WebhookDispatcher,
    DispatchChannel.SLACK: SlackDispatcher,
    DispatchChannel.PAGERDUTY: PagerDutyDispatcher,
}


def build_dispatcher(channel: str, config: Dict[str, Any]) -> BaseDispatcher:
    ch = DispatchChannel(channel)
    cls = DISPATCHER_REGISTRY[ch]
    rate_cfg = config.pop("rate_limiter", {})
    rl = RateLimiter(**rate_cfg) if rate_cfg else None
    max_retries = config.pop("max_retries", 3)
    return cls(**config, rate_limiter=rl, max_retries=max_retries)


class AlertRouter:
    def __init__(self):
        self._dispatchers: Dict[str, BaseDispatcher] = {}

    def add_rule_dispatch(self, rule_id: str, dispatcher: BaseDispatcher):
        self._dispatchers[rule_id] = dispatcher

    def route(self, alert: Dict[str, Any]) -> DispatchResult:
        rule_id = alert.get("rule_id", "")
        disp = self._dispatchers.get(rule_id)
        if not disp:
            return DispatchResult(False, "none", error=f"no dispatcher for rule {rule_id}")
        return disp.dispatch(alert)

    def route_multi(self, alert: Dict[str, Any], rule_ids: List[str]) -> List[DispatchResult]:
        results = []
        for rid in rule_ids:
            disp = self._dispatchers.get(rid)
            results.append(disp.dispatch(alert) if disp else
                           DispatchResult(False, "none", error=f"no dispatcher for rule {rid}"))
        return results