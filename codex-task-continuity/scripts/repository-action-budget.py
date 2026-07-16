#!/usr/bin/env python3
"""维护每日仓库写操作的有界自适应预算。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
from pathlib import Path


RUNGS = (3, 5, 8, 10)
DEFAULT_PATH = Path.home() / ".codex" / "task-ledger" / "repository-closure" / "action-budget.json"


def default_state():
    return {
        "schema_version": 1,
        "current_limit": RUNGS[0],
        "consecutive_eligible_runs": 0,
        "runs": [],
        "last_adjustment": None,
    }


def load_state(path=DEFAULT_PATH):
    path = Path(path).expanduser()
    if not path.exists():
        return default_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    if state.get("current_limit") not in RUNGS:
        state["current_limit"] = RUNGS[0]
    state.setdefault("consecutive_eligible_runs", 0)
    state.setdefault("runs", [])
    state.setdefault("last_adjustment", None)
    state["schema_version"] = 1
    return state


def save_state(path, state):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="action-budget.", suffix=".json", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def run_quality(run):
    attempted = max(0, int(run.get("attempted", 0)))
    succeeded = max(0, int(run.get("succeeded", 0)))
    success_rate = succeeded / attempted if attempted else 0.0
    api_limit = max(0, int(run.get("api_limit", 0)))
    api_remaining = max(0, int(run.get("api_remaining", 0)))
    api_ratio = api_remaining / api_limit if api_limit else 1.0
    risk = bool(
        int(run.get("unsafe_actions", 0)) > 0
        or int(run.get("conflicts", 0)) > 0
        or (attempted > 0 and success_rate < 0.7)
        or int(run.get("duration_seconds", 0)) > 3600
        or api_ratio < 0.1
    )
    eligible = bool(
        attempted > 0
        and not risk
        and success_rate >= 0.9
        and int(run.get("duration_seconds", 0)) <= 1800
        and api_ratio >= 0.2
    )
    return eligible, risk, round(success_rate, 4), round(api_ratio, 4)


def record_run(path, run):
    state = load_state(path)
    eligible, risk, success_rate, api_ratio = run_quality(run)
    entry = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "attempted": max(0, int(run.get("attempted", 0))),
        "succeeded": max(0, int(run.get("succeeded", 0))),
        "unsafe_actions": max(0, int(run.get("unsafe_actions", 0))),
        "conflicts": max(0, int(run.get("conflicts", 0))),
        "duration_seconds": max(0, int(run.get("duration_seconds", 0))),
        "api_remaining": max(0, int(run.get("api_remaining", 0))),
        "api_limit": max(0, int(run.get("api_limit", 0))),
        "success_rate": success_rate,
        "api_remaining_ratio": api_ratio,
        "eligible_for_growth": eligible,
        "risk_event": risk,
    }
    state["runs"] = [*state.get("runs", []), entry][-30:]
    current_index = RUNGS.index(state["current_limit"])
    if risk:
        state["consecutive_eligible_runs"] = 0
        if current_index > 0:
            old_limit = state["current_limit"]
            state["current_limit"] = RUNGS[current_index - 1]
            state["last_adjustment"] = {
                "at": entry["recorded_at"],
                "from": old_limit,
                "to": state["current_limit"],
                "reason": "regression",
            }
    elif eligible:
        state["consecutive_eligible_runs"] += 1
        if state["consecutive_eligible_runs"] >= 7 and current_index < len(RUNGS) - 1:
            old_limit = state["current_limit"]
            state["current_limit"] = RUNGS[current_index + 1]
            state["consecutive_eligible_runs"] = 0
            state["last_adjustment"] = {
                "at": entry["recorded_at"],
                "from": old_limit,
                "to": state["current_limit"],
                "reason": "growth",
            }
    else:
        state["consecutive_eligible_runs"] = 0
    save_state(path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show")
    record = subparsers.add_parser("record")
    for name in ("attempted", "succeeded", "unsafe-actions", "conflicts", "duration-seconds", "api-remaining", "api-limit"):
        record.add_argument(f"--{name}", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "show":
        state = load_state(args.state_path)
    else:
        state = record_run(
            args.state_path,
            {
                "attempted": args.attempted,
                "succeeded": args.succeeded,
                "unsafe_actions": args.unsafe_actions,
                "conflicts": args.conflicts,
                "duration_seconds": args.duration_seconds,
                "api_remaining": args.api_remaining,
                "api_limit": args.api_limit,
            },
        )
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
