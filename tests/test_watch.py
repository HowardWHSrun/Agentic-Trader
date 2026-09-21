"""Validate the public watch feed without brokerage access or network calls."""
import json
import math
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEYS = {"account_id", "item_id", "balance", "balances", "quantity", "share_count", "buying_power", "access_token", "api_key", "password", "deposit", "transactions"}


def timestamp(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("A timestamp with time and timezone is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timezone")


def validate(data):
    if data["schema_version"] != 1 or data["timezone"] != "America/Chicago":
        raise ValueError("Unsupported configuration")
    timestamp(data["configuration_updated_at"])
    if data["schedule"]["hours"] != [8, 12, 16]:
        raise ValueError("Unexpected check hours")
    if data["schedule"]["weekdays"] != ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        raise ValueError("Unexpected weekdays")
    if data["schedule"]["timing"] != "approximate":
        raise ValueError("Do not promise exact check times")
    def privacy(value):
        if isinstance(value, dict):
            if PRIVATE_KEYS.intersection(value):
                raise ValueError("Private field in public feed")
            for child in value.values():
                privacy(child)
        elif isinstance(value, list):
            for child in value:
                privacy(child)
    privacy(data)
    check = data["last_check"]
    if check is not None:
        timestamp(check["checked_at"])
        if check["status"] not in {"completed_alert", "completed_no_alert", "incomplete"}:
            raise ValueError("Unsupported review status")
        if not check.get("summary") or not check.get("coverage"):
            raise ValueError("Missing review evidence or coverage")
    ids = set()
    for alert in data["alerts"]:
        if not alert.get("id") or alert["id"] in ids:
            raise ValueError("Missing or duplicate alert ID")
        ids.add(alert["id"])
        if alert["label"] not in {"TRADING CANDIDATE", "LONGER-TERM INVESTMENT CANDIDATE"}:
            raise ValueError("Unsupported candidate label")
        timestamp(alert["published_at"])
        for key in ["ticker", "name", "summary", "entry", "horizon", "invalidation", "risks", "alternative", "conclusion"]:
            if not isinstance(alert.get(key), str) or not alert[key].strip():
                raise ValueError("Missing candidate field: " + key)
        quote = alert["quote"]
        timestamp(quote["as_of"])
        if not isinstance(quote["price"], (int, float)) or not math.isfinite(quote["price"]) or quote["price"] <= 0:
            raise ValueError("Invalid quote")
        if any(not quote.get(key) for key in ["currency", "session", "delay"]):
            raise ValueError("Unlabeled quote")
        if not alert.get("sources"):
            raise ValueError("Missing sources")
        for source in alert["sources"]:
            url = urlparse(source["url"])
            if url.scheme != "https" or not url.netloc or url.username or url.password or not source.get("title"):
                raise ValueError("Unsafe source link")


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "docs/data/watch.json").read_text())

    def test_current_feed(self):
        validate(self.data)

    def test_reject_naive_time(self):
        with self.assertRaises(ValueError):
            timestamp("2026-09-21T12:00:00")

    def test_reject_date_only(self):
        with self.assertRaises(ValueError):
            timestamp("2026-09-21")

    def test_reject_private_fields(self):
        self.data["account_id"] = "test-only"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_reject_unsupported_status(self):
        self.data["last_check"] = {"checked_at": "2026-09-21T12:00:00-05:00", "status": "live"}
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_page_uses_safe_text_rendering(self):
        page = (ROOT / "docs/watch.html").read_text()
        self.assertNotIn("innerHTML", page)
        self.assertIn("textContent", page)
        self.assertIn("cache:'no-store'", page)
        self.assertIn("No completed check has been published", page)


if __name__ == "__main__":
    unittest.main()
