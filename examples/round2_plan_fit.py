"""How many rejected task decompositions would `planning.fit_durations` have accepted?

Reads the call ledgers of recorded runs (no model calls), takes every `decompose` and `replan`
answer the planner rejected, and applies the duration fit to it. An answer counts as rescued
when the fitted durations add up to the window with every task in range. The window length is
read from the recorded validation error, or is the sum of the answer's own durations when
only the range was violated.

    uv run python examples/round2_plan_fit.py runs/experiments/fire_llama32 runs/llama_fire_source
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generative_agents.cognition.planning import fit_durations  # noqa: E402

NEED = re.compile(r"need exactly (\d+)")


def ledgers(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for p in map(Path, paths):
        found += [p / "provider.sqlite"] if (p / "provider.sqlite").exists() else sorted(p.glob("*/provider.sqlite"))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="run directories or experiment directories")
    ap.add_argument("--min", type=int, default=5)
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--out", default=None, help="write the counts as JSON here")
    args = ap.parse_args()
    counts: dict[str, dict[str, int]] = {}
    examples: list[dict] = []
    for ledger in ledgers(args.paths):
        conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT task, status, raw_output, validation_errors FROM calls WHERE task IN ('decompose', 'replan')").fetchall()
        conn.close()
        for r in rows:
            c = counts.setdefault(r["task"], {"calls": 0, "rejected": 0, "rescued": 0, "tasks_dropped": 0, "minutes_moved": 0})
            c["calls"] += 1
            if r["status"] != "invalid":
                continue
            c["rejected"] += 1
            try:
                given = [int(t["duration_minutes"]) for t in json.loads(r["raw_output"])["tasks"]]
            except (ValueError, KeyError, TypeError):
                continue  # not parseable: the fit does not apply
            need = NEED.search(r["validation_errors"] or "")
            total = int(need.group(1)) if need else sum(given)
            fitted = fit_durations(given, total, args.min, args.max)
            if fitted is None:
                continue
            c["rescued"] += 1
            c["tasks_dropped"] += len(given) - len(fitted)
            c["minutes_moved"] += sum(abs(a - b) for a, b in zip(given, fitted, strict=False))
            if len(examples) < 3:
                examples.append({"run": ledger.parent.name, "task": r["task"], "window": total, "given": given, "fitted": fitted})
    for task, c in counts.items():
        print(
            f"{task}: {c['calls']} calls, {c['rejected']} rejected, {c['rescued']} of those fit ({c['tasks_dropped']} tasks dropped, {c['minutes_moved']} minutes moved)"
        )
    for e in examples:
        print(f"  {e['run']} {e['task']} window {e['window']}: {e['given']} -> {e['fitted']}")
    if args.out:
        Path(args.out).write_text(json.dumps({"counts": counts, "examples": examples}, indent=2) + "\n")


if __name__ == "__main__":
    main()
