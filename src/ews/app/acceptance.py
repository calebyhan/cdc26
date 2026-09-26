"""Record deployment and three distinct consecutive successful refresh dates."""

import argparse
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests


def consecutive_days(runs):
    daily = {}
    for run in runs:
        day = date.fromisoformat(run["created_at"][:10])
        # Only completed successful workflow runs count; latest attempt per date
        # wins, so a later failure invalidates that day's operational evidence.
        if day not in daily or run["created_at"] > daily[day]["created_at"]:
            daily[day] = run
    if not daily:
        return 0
    day = max(daily)
    streak = 0
    while day in daily and daily[day].get("conclusion") == "success":
        streak += 1
        day -= timedelta(days=1)
    # Old streaks do not establish that today's deployment is being refreshed.
    if max(daily) < date.today() - timedelta(days=1):
        return 0
    return streak


def audit(url=None, browser_report=None):
    response = subprocess.run(
        [
            "gh",
            "api",
            "repos/calebyhan/cdc26/actions/workflows/daily-refresh.yml/runs?per_page=100",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    runs = json.loads(response.stdout)["workflow_runs"]
    streak = consecutive_days(runs)
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
        "consecutive_successful_refresh_dates": streak,
        "local_performance": performance,
        "deployed_browser_performance_verified": browser_verified,
        "browser_performance": browser,
        "exit_criteria_met": deployed and streak >= 3 and browser_verified,
        "remaining": [
            label
            for condition, label in [
                (not deployed, "Public deployment not verified"),
                (streak < 3, "Daily refresh needs three consecutive successful dates"),
                (
                    True,
                    "Measure every view in the deployed browser under three seconds",
                ),
            ]
            if condition
        ],
        "runs": [
            {
                "url": r["html_url"],
                "created_at": r["created_at"],
                "conclusion": r["conclusion"],
            }
            for r in runs[:10]
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
