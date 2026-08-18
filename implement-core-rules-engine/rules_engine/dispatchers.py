from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

from .models import Alert

logger = logging.getLogger(__name__)


class SlackDispatcher:
    """Sends alerts to a Slack incoming webhook."""

    def __init__(self, webhook_url: str, channel: Optional[str] = None) -> None:
        self.webhook_url = webhook_url
        self.channel = channel

    def __call__(self, alert: Alert) -> None:
        emoji = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}.get(alert.severity, "⚡")
        text = (
            f"{emoji} *{alert.rule_name}* (`{alert.severity}`)\n"
            f"Metric: `{alert.metric}` | Value: `{alert.actual_value}` | Threshold: `{alert.threshold}`\n"
            f"Time: {alert.timestamp}"
        )
        payload: Dict[str, Any] = {"text": text}
        if self.channel:
            payload["channel"] = self.channel
        self._post(payload)

    def _post(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.debug("Slack responded %s", resp.status)
        except Exception:
            logger.exception("Failed to post to Slack webhook")


class PagerDutyDispatcher:
    """Sends alerts to PagerDuty Events API v2."""

    def __init__(self, routing_key: str, severity_map: Optional[Dict[str, str]] = None) -> None:
        self.routing_key = routing_key
        self.severity_map = severity_map or {"critical": "critical", "warning": "warning", "info": "info"}

    def __call__(self, alert: Alert) -> None:
        pd_severity = self.severity_map.get(alert.severity, "warning")
        payload = {
            "routing_key": self.routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"Alert: {alert.rule_name}",
                "severity": pd_severity,
                "source": alert.rule_id,
                "timestamp": alert.timestamp,
                "custom_details": alert.to_dict(),
            },
        }
        self._post(payload)

    def _post(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        url = "https://events.pagerduty.com/v2/enqueue"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.debug("PagerDuty responded %s", resp.status)
        except Exception:
            logger.exception("Failed to post to PagerDuty")