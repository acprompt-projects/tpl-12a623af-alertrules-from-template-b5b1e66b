import json
import time
import hashlib
from unittest.mock import patch, MagicMock

import pytest
import httpx

BASE_URL = "http://localhost:8000"


def _unique_suffix():
    return hashlib.md5(str(time.monotonic()).encode()).hexdigest()[:8]


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def _create_rule(client, suffix=None):
    suffix = suffix or _unique_suffix()
    payload = {
        "name": f"cpu-high-{suffix}",
        "metric_source": "infra-observability",
        "metric_name": "cpu_percent",
        "condition": {"operator": "gt", "threshold": 90.0},
        "window_seconds": 60,
        "severity": "critical",
        "notifications": [
            {"type": "slack", "channel": "#ops-alerts"},
            {"type": "pagerduty", "severity": "high"},
        ],
    }
    resp = client.post("/rules", json=payload)
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    rule = resp.json()
    assert rule["id"]
    assert rule["name"] == payload["name"]
    return rule


class TestRuleCRUD:
    def test_create_rule(self, client):
        rule = _create_rule(client)
        assert rule["condition"]["operator"] == "gt"
        assert rule["condition"]["threshold"] == 90.0

    def test_list_rules(self, client):
        _create_rule(client)
        resp = client.get("/rules")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list) and len(resp.json()) >= 1

    def test_get_rule(self, client):
        rule = _create_rule(client)
        resp = client.get(f"/rules/{rule['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == rule["id"]

    def test_update_rule(self, client):
        rule = _create_rule(client)
        resp = client.patch(f"/rules/{rule['id']}", json={"condition": {"operator": "gte", "threshold": 95.0}})
        assert resp.status_code == 200
        assert resp.json()["condition"]["threshold"] == 95.0

    def test_delete_rule(self, client):
        rule = _create_rule(client)
        resp = client.delete(f"/rules/{rule['id']}")
        assert resp.status_code == 204
        resp2 = client.get(f"/rules/{rule['id']}")
        assert resp2.status_code == 404


class TestRuleEvaluation:
    @patch("alertrules.dispatchers.send_slack", return_value=True)
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_metric_triggers_alert(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        metric = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 96.5,
            "timestamp": time.time(),
            "labels": {"host": "node-01"},
        }
        resp = client.post("/evaluate", json=metric)
        assert resp.status_code == 200
        body = resp.json()
        assert body["triggered"] is True
        assert body["rule_id"] == rule["id"]
        assert body["alert"]["severity"] == "critical"

    def test_metric_below_threshold_no_alert(self, client):
        _create_rule(client)
        metric = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 45.0,
            "timestamp": time.time(),
            "labels": {"host": "node-01"},
        }
        resp = client.post("/evaluate", json=metric)
        assert resp.status_code == 200
        assert resp.json()["triggered"] is False

    @patch("alertrules.dispatchers.send_slack", return_value=True)
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_window_aggregation(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        base_ts = time.time() - 55
        for i in range(6):
            metric = {
                "source": "infra-observability",
                "name": "cpu_percent",
                "value": 92.0 + i,
                "timestamp": base_ts + i * 10,
                "labels": {"host": "node-01"},
            }
            client.post("/evaluate", json=metric)
        resp = client.get(f"/rules/{rule['id']}/state")
        assert resp.status_code == 200
        state = resp.json()
        assert state["breach_count"] >= 1


class TestNotificationDispatch:
    @patch("alertrules.dispatchers.send_slack", return_value=True)
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_slack_and_pagerduty_called(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        metric = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 99.0,
            "timestamp": time.time(),
            "labels": {"host": "node-01"},
        }
        client.post("/evaluate", json=metric)
        assert mock_slack.called
        assert mock_pd.called
        slack_args = mock_slack.call_args
        assert "#ops-alerts" in slack_args[0][0] or "#ops-alerts" in str(slack_args[1])

    @patch("alertrules.dispatchers.send_slack", side_effect=Exception("slack down"))
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_slack_failure_does_not_block_pagerduty(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        metric = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 99.0,
            "timestamp": time.time(),
            "labels": {"host": "node-01"},
        }
        resp = client.post("/evaluate", json=metric)
        assert resp.status_code == 200
        assert mock_pd.called


class TestAlertLifecycle:
    @patch("alertrules.dispatchers.send_slack", return_value=True)
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_alert_dedup_within_window(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        metric = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 97.0,
            "timestamp": time.time(),
            "labels": {"host": "node-02"},
        }
        r1 = client.post("/evaluate", json=metric)
        r2 = client.post("/evaluate", json=metric)
        assert r1.json()["triggered"] is True
        assert r2.json()["triggered"] is False
        assert mock_slack.call_count == 1
        assert mock_pd.call_count == 1

    @patch("alertrules.dispatchers.send_slack", return_value=True)
    @patch("alertrules.dispatchers.send_pagerduty", return_value=True)
    def test_resolve_alert(self, mock_pd, mock_slack, client):
        rule = _create_rule(client)
        hi = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 96.0,
            "timestamp": time.time(),
            "labels": {"host": "node-03"},
        }
        client.post("/evaluate", json=hi)
        lo = {
            "source": "infra-observability",
            "name": "cpu_percent",
            "value": 50.0,
            "timestamp": time.time(),
            "labels": {"host": "node-03"},
        }
        resp = client.post("/evaluate", json=lo)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("resolved") is True