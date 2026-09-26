"""Record public deployment and performance for a manually refreshed snapshot."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests


def audit(url=None, browser_report=None):
    deployed = False
    if url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Use a public HTTPS dashboard URL")
        health = requests.get(url.rstrip("/") + "/_stcore/health", timeout=30)
        deployed = health.ok and health.text.strip().lower() == "ok"
    performance = json.loads(Path("reports/dashboard_performance.json").read_text())
    browser_verified = False
    browser = None
    if browser_report and Path(browser_report).exists():
        browser = json.loads(Path(browser_report).read_text())
        required = {
            "Risk leaderboard",
            "Company detail",
            "Enforcement timeline",
            "Backtest results",
            "Limitations",
        }
        browser_verified = (
            browser.get("public_url", "").rstrip("/") == (url or "").rstrip("/")
            and browser.get("initial_page_load_verified", False)
            and browser.get("initial_page_load_seconds", 999) < 3
            and required.issubset(browser.get("views", {}))
            and all(0 <= browser["views"][name]["seconds"] < 3 for name in required)
            and date.fromisoformat(browser["measured_at"][:10])
            >= date.today() - timedelta(days=1)
        )
    return {
        "public_url": url,
        "public_streamlit_health_verified": deployed,
        "refresh_mode": "manual",
        "local_performance": performance,
        "deployed_browser_performance_verified": browser_verified,
        "browser_performance": browser,
        "exit_criteria_met": deployed and browser_verified,
        "remaining": [
            label
            for condition, label in [
                (not deployed, "Public deployment not verified"),
                (
                    not browser_verified,
                    "Measure every view in the deployed browser under three seconds",
                ),
            ]
            if condition
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/dashboard_acceptance.json")
    )
    parser.add_argument("--browser-report", type=Path)
    args = parser.parse_args()
    result = audit(args.url, args.browser_report)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
