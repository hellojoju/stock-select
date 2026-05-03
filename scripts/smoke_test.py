#!/usr/bin/env python
"""
Live smoke test — run the full daily pipeline on a fixed historical date.

Usage:
    .venv/bin/python scripts/smoke_test.py --date 2024-04-22
    .venv/bin/python scripts/smoke_test.py --date 2024-04-22 --mode demo
    .venv/bin/python scripts/smoke_test.py  # defaults to today, demo mode
"""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
from datetime import date

REQUIRED_PHASES = [
    "sync_data",
    "sync_factors",
    "process_announcements",
    "preopen_pick",
    "simulate",
    "deterministic_review",
    "blindspot_review",
    "gene_review",
    "system_review",
]

PYTHON = sys.executable
MODULE = "stock_select.cli"


def run_phase(phase: str, target_date: str, mode: str, db: str) -> tuple[bool, dict]:
    """Run a single phase and return (success, parsed_result)."""
    cmd = [PYTHON, "-m", MODULE, "--mode", mode, "--db", db, "run-phase", phase, "--date", target_date]
    print(f"  ▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    parsed: dict = {}
    if result.stdout:
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    if result.returncode != 0:
        print(f"  ✗ {phase} FAILED")
        if result.stderr:
            lines = result.stderr.strip().split("\n")
            for line in lines[-10:]:
                print(f"    {line}")
        return False, parsed
    print(f"  ✓ {phase} OK")
    return True, parsed


def verify_database(date_str: str, db: str) -> list[str]:
    """
    Hard assertions for 1.0 readiness.
    Returns list of failure messages (empty = all good).
    """
    cmd = [
        PYTHON, "-c",
        f"""
import json, sys
from stock_select.db import connect, init_db
conn = connect("{db}")
init_db(conn)
errors = []

# 1. 候选决策必须非零
row = conn.execute("SELECT COUNT(*) FROM pick_decisions WHERE trading_date = ?", ("{date_str}",)).fetchone()
pick_count = row[0]
if pick_count == 0:
    errors.append("pick_decisions = 0 (没有产生候选)")

# 2. 模拟成交必须非零
row = conn.execute("SELECT COUNT(*) FROM outcomes WHERE decision_id IN (SELECT decision_id FROM pick_decisions WHERE trading_date = ?)", ("{date_str}",)).fetchone()
outcome_count = row[0]
if outcome_count == 0:
    errors.append("outcomes = 0 (没有模拟成交)")

# 3. 复盘证据必须非零
row = conn.execute("SELECT COUNT(*) FROM review_evidence WHERE trading_date = ?", ("{date_str}",)).fetchone()
evidence_count = row[0]
if evidence_count == 0:
    errors.append("review_evidence = 0 (没有复盘证据)")

# 4. 外部数据输入必须非零
row = conn.execute("SELECT COUNT(*) FROM raw_documents").fetchone()
doc_count = row[0]
if doc_count == 0:
    errors.append("raw_documents = 0 (没有外部数据)")

# 5. 知识图谱节点必须非零
row = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()
graph_count = row[0]
if graph_count == 0:
    errors.append("graph_nodes = 0 (知识图谱为空)")

# 6. 运行记录必须非零
row = conn.execute("SELECT COUNT(*) FROM research_runs WHERE trading_date = ?", ("{date_str}",)).fetchone()
run_count = row[0]
if run_count == 0:
    errors.append("research_runs = 0 (没有运行记录)")

print(json.dumps({{
    "pick_decisions": pick_count,
    "outcomes": outcome_count,
    "review_evidence": evidence_count,
    "raw_documents": doc_count,
    "graph_nodes": graph_count,
    "research_runs": run_count,
    "errors": errors,
}}))
conn.close()
""",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()[-200:] if result.stderr else "unknown error"
        return [f"DB verification script crashed: {stderr}"]
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [f"DB verification returned invalid JSON: {result.stdout[:200]}"]

    counts = {k: v for k, v in data.items() if k != "errors"}
    print(f"  数据量: {counts}")
    return data.get("errors", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for the full daily pipeline")
    parser.add_argument("--date", default=date.today().isoformat(), help="Trading date to test (default: today)")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo", help="Runtime mode")
    parser.add_argument("--db", default="var/stock_select.db", help="Database path")
    parser.add_argument("--skip-verify", action="store_true", help="Skip database verification")
    parser.add_argument("--phases", nargs="*", help="Run specific phases only (default: all)")
    args = parser.parse_args()

    target_date: str = args.date
    mode: str = args.mode
    db_path: str = args.db
    phases = args.phases or REQUIRED_PHASES

    print(f"=" * 60)
    print(f"Smoke Test — {target_date} ({mode})")
    print(f"=" * 60)
    print(f"DB: {db_path}")
    print(f"Phases: {', '.join(phases)}")
    print()

    results: dict[str, bool] = {}
    phase_outputs: dict[str, dict] = {}

    for phase in phases:
        print(f"--- Phase: {phase} ---")
        ok, parsed = run_phase(phase, target_date, mode, db_path)
        results[phase] = ok
        phase_outputs[phase] = parsed
        print()

    # Verify database state
    db_errors: list[str] = []
    if not args.skip_verify:
        print("--- Database Verification ---")
        db_errors = verify_database(target_date, db_path)
        if db_errors:
            for err in db_errors:
                print(f"  ✗ {err}")
        else:
            print("  ✓ All tables have non-zero data")
        print()

    # Summary
    print(f"=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Phases: {passed}/{total} passed")

    for phase, ok in results.items():
        status = "✓" if ok else "✗"
        print(f"  {status} {phase}")

    if db_errors:
        print(f"  ✗ Database verification: {len(db_errors)} failure(s)")

    if not all(results.values()) or db_errors:
        print()
        failed = [p for p, ok in results.items() if not ok]
        if failed:
            print(f"FAILED phases: {', '.join(failed)}")
        if db_errors:
            print(f"FAILED assertions: {', '.join(db_errors)}")
        return 1

    print()
    print("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
