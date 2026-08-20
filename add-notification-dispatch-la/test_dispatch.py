import time
import json
import unittest
from unittest.mock import patch, MagicMock
from dispatch import (RateLimiter, retry_with_backoff, WebhookDispatcher,
                      SlackDispatcher, PagerDutyDispatcher, AlertRouter,
                      build_dispatcher, DispatchChannel, DispatchResult)


class TestRateLimiter(unittest.TestCase):
    def test_allows_under_limit(self):
        rl = RateLimiter(max_calls=3, period_seconds=60)
        self.assertTrue(rl.allow())
        self.assertTrue(rl.allow())
        self.assertTrue(rl.allow())

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_calls=2, period_seconds=60)
        rl.allow()
        rl.allow()
        self.assertFalse(rl.allow())


class TestRetryBackoff(unittest.TestCase):
    @patch("dispatch.time.sleep")
    def test_succeeds_first_try(self, mock_sleep):
        result = retry_with_backoff(lambda: 42, max_retries=3)
        self.assertEqual(result, 42)
        mock_sleep.assert_not_called()

    @patch("dispatch.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep):
        call_count = 0
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "ok"
        result = retry_with_backoff(flaky, max_retries=3, base_delay=0.1)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 3)

    @patch("dispatch.time.sleep")
    def test_exhausts_retries(self, mock_sleep):
        with self.assertRaises(ConnectionError):
            retry_with_backoff(lambda: (_ for _ in ()).throw(ConnectionError("fail")),
                               max_retries=2)


class TestWebhookDispatcher(unittest.TestCase):
    @patch("dispatch.requests.post")
    def test_dispatch_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        d = WebhookDispatcher(url="https://hooks.example.com/alert")
        result = d.dispatch({"rule_name": "cpu_high", "severity": "critical"})
        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 200)

    @patch("dispatch.requests.post")
    def test_rate_limited(self, mock_post):
        d = WebhookDispatcher(url="https://hooks.example.com/alert",
                              rate_limiter=RateLimiter(max_calls=1))
        d.dispatch({"rule_name": "a"})
        result = d.dispatch({"rule_name": "b"})
        self.assertFalse(result.success)
        self.assertEqual(result.error, "rate_limited")
        mock_post.assert_called_once()


class TestSlackDispatcher(unittest.TestCase):
    @patch("dispatch.requests.post")
    def test_dispatch_sends_blocks(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        d = SlackDispatcher(webhook_url="https://hooks.slack.com/services/XXX")
        alert = {"rule_name": "mem_high", "severity": "warning", "metric": "mem_pct",
                 "value": 92, "threshold": 85}
        result = d.dispatch(alert)
        self.assertTrue(result.success)
        body = mock_post.call_args[1]["json"]
        self.assertIn("blocks", body)


class TestPagerDutyDispatcher(unittest.TestCase):
    @patch("dispatch.requests.post")
    def test_dispatch_sends_event(self, mock_post):
        mock_post.return_value = MagicMock(status_code=202)
        d = PagerDutyDispatcher(routing_key="abc123")
        alert = {"rule_name": "disk_full", "severity": "critical", "metric": "disk_pct",
                 "value": 99, "threshold": 90, "dedup_key": "disk-full-01"}
        result = d.dispatch(alert)
        self.assertTrue(result.success)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["routing_key"], "abc123")
        self.assertEqual(body["dedup_key"], "disk-full-01")
        self.assertEqual(body["event_action"], "trigger")


class TestAlertRouter(unittest.TestCase):
    @patch("dispatch.requests.post")
    def test_route_to_rule(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        router = AlertRouter()
        router.add_rule_dispatch("rule-1", SlackDispatcher(webhook_url="https://hooks.slack.com/x"))
        result = router.route({"rule_id": "rule-1", "rule_name": "test"})
        self.assertTrue(result.success)

    def test_route_missing_rule(self):
        router = AlertRouter()
        result = router.route({"rule_id": "unknown"})
        self.assertFalse(result.success)


class TestBuildDispatcher(unittest.TestCase):
    def test_build_slack(self):
        d = build_dispatcher("slack", {"webhook_url": "https://hooks.slack.com/x"})
        self.assertIsInstance(d, SlackDispatcher)

    def test_build_with_rate_limiter(self):
        d = build_dispatcher("webhook", {"url": "https://x.com",
                         "rate_limiter": {"max_calls": 5, "period_seconds": 120}})
        self.assertEqual(d.rate_limiter.max_calls, 5)


if __name__ == "__main__":
    unittest.main()