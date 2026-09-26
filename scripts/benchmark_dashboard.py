"""Measure real browser view switching with agent-browser's trusted CDP clicks.

Use an already loaded session. Start it with dashboard_initial_load.js to also
capture first-page readiness:
python scripts/benchmark_dashboard.py --session dashboard-qa
"""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--session", required=True)
parser.add_argument(
    "--output", type=Path, default=Path("reports/dashboard_browser_performance.json")
)
args = parser.parse_args()
base = ["agent-browser", "--session", args.session, "--json"]
script = Path(__file__).with_name("dashboard_browser_benchmark.js").read_text()
views = [
    "Risk leaderboard",
    "Company detail",
    "Enforcement timeline",
    "Backtest results",
    "Limitations",
]
results = {}
for view in views:
    snapshot_process = subprocess.run(
        base + ["snapshot", "-i"], text=True, capture_output=True, check=True
    )
    refs = json.loads(snapshot_process.stdout)["data"]["refs"]
    target = next(
        ref
        for ref, node in refs.items()
        if node.get("role") == "radio" and node.get("name") == view
    )
    # JSON data stays in JS over stdin, not shell interpolation.
    start_script = (
        "window.ewsBenchmarkView="
        + json.dumps(view)
        + ";window.ewsBenchmarkStarted=performance.now();true"
    )
    subprocess.run(
        base + ["eval", "--stdin"],
        input=start_script,
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        base + ["click", "@" + target],
        text=True,
        capture_output=True,
        check=True,
    )
    process = subprocess.run(
        base + ["eval", "--stdin"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(process.stdout)
    if not result["success"]:
        raise RuntimeError(result["error"])
    results[view] = {"seconds": result["data"]["result"]["seconds"]}
    url = result["data"]["result"]["url"]
initial_process = subprocess.run(
    base + ["eval", "window.ewsInitialLoad || null"],
    text=True,
    capture_output=True,
    check=True,
)
initial = json.loads(initial_process.stdout)["data"]["result"]
report = {
    "scope": "Browser view switching after initial assets load; includes CDP/CLI overhead, chart rendering and 150ms stability window",
    "public_url": url,
    "measured_at": datetime.now(timezone.utc).isoformat(),
    "initial_page_load_verified": initial is not None,
    "initial_page_load_seconds": initial["seconds"] if initial else None,
    "initial_page_load": initial,
    "views": results,
}
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
