#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agency_bigquery.agent_ops import agent_activity_for_date, agent_activity_markdown  # noqa: E402


DEFAULT_AGENT_RUN_INDEX = PROJECT_ROOT / "data" / "agent_runs" / "index.json"
DEFAULT_ACTIVE_RUN_DIR = PROJECT_ROOT / "data" / "agent_runs" / "active"
MELBOURNE_TIMEZONE = ZoneInfo("Australia/Melbourne")


def melbourne_today_iso() -> str:
    return datetime.now(MELBOURNE_TIMEZONE).date().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show local SEO Agency OS agent activity for a day.")
    parser.add_argument("--date", default=melbourne_today_iso(), help="Activity date, YYYY-MM-DD. Defaults to today in Australia/Melbourne.")
    parser.add_argument("--index", default=str(DEFAULT_AGENT_RUN_INDEX), help="Local agent run index path.")
    parser.add_argument("--active-dir", default=str(DEFAULT_ACTIVE_RUN_DIR), help="Directory containing active run markers.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    activity_date = date.fromisoformat(args.date)
    activity = agent_activity_for_date(Path(args.index), Path(args.active_dir), activity_date)
    if args.json:
        print(json.dumps(activity, indent=2, sort_keys=True, default=str))
    else:
        print(agent_activity_markdown(activity), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
