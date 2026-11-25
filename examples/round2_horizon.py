"""Post-hoc probe: the recency term is relative to the oldest memory in the stream.

The paper's retrieval score min-max normalizes recency over all of an agent's memories.
A fact that is 44 hours old in a 48-hour stream therefore has a normalized recency near
zero, whatever the decay constant. This script shows the consequence on finished runs:
it plants the second fact set twice into the final snapshot of every run of a condition,
once as it is and once with a single unrelated "anchor" memory dated 30 days back, and
compares where the same facts rank. Nothing but that one memory differs.

Exploratory by design: it was written after the round-two memory experiment was
registered and is reported as such (docs/experiments/round2.md).

    uv run python examples/round2_horizon.py runs/experiments/memory_retrieval_v2 --condition full
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generative_agents.db import Database  # noqa: E402
from generative_agents.evaluation import memory_probe as mp  # noqa: E402
from generative_agents.evaluation.experiment import load_rows  # noqa: E402
from generative_agents.providers.embeddings import build_embedding_provider  # noqa: E402
from generative_agents.simulation.engine import load_run_config  # noqa: E402

AGES = ("0.5", "3", "8", "20", "32", "44")


def probe(run_dir: Path, facts_file: str, provider) -> dict:
    cfg = load_run_config(run_dir)
    snap = run_dir / "snapshots" / "final.sqlite"
    db = Database(snap, read_only=True)
    try:
        agents = [r["id"] for r in db.query("SELECT id FROM agents ORDER BY id")]
    finally:
        db.close()
    return mp.planted_facts(cfg, snap, agents, facts=mp.load_facts(facts_file), k=10, embedding_provider=provider)["summary"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("experiment_dir")
    ap.add_argument("--condition", default="full")
    ap.add_argument("--out", default=None, help="default: EXPERIMENT_DIR/horizon.json")
    args = ap.parse_args()
    root = Path(args.experiment_dir)
    rows = [r for r in load_rows(root) if r["condition"] == args.condition and r.get("status") == "completed"]
    if not rows:
        raise SystemExit(f"no completed runs of condition {args.condition!r} in {root}")
    provider = build_embedding_provider(load_run_config(Path(rows[0]["run_dir"])).providers.embeddings)
    per_run = []
    for r in rows:
        run_dir = Path(r["run_dir"])
        plain = probe(run_dir, "configs/probes/memory_facts_v2.yaml", provider)
        anchored = probe(run_dir, "configs/probes/memory_facts_v2_anchor.yaml", provider)
        per_run.append({"run_id": r["run_id"], "seed": r["seed"], "plain": plain, "anchored": anchored})
        print(f"  {r['run_id']}: recall@30 {plain['recall_at_30']:.3f} -> {anchored['recall_at_30']:.3f} with a 30-day anchor", flush=True)

    def mean(key_path: list[str], which: str) -> float:
        vals = []
        for pr in per_run:
            v = pr[which]
            for k in key_path:
                v = v[k]
            vals.append(v)
        return round(statistics.mean(vals), 4)

    table = {
        which: {
            "recall_at_10": mean(["recall_at_k"], which),
            "recall_at_30": mean(["recall_at_30"], which),
            "recall_old_at_30": mean(["old", "recall_at_30"], which),
            "median_rank": mean(["median_rank"], which),
            "by_age": {
                a: {
                    "recall_at_30": mean(["by_age_hours", a, "recall_at_30"], which),
                    "normalized_recency": mean(["by_age_hours", a, "mean_normalized_recency"], which),
                }
                for a in AGES
            },
        }
        for which in ("plain", "anchored")
    }
    diffs = [pr["anchored"]["old"]["recall_at_30"] - pr["plain"]["old"]["recall_at_30"] for pr in per_run]
    out = {
        "condition": args.condition,
        "runs": len(per_run),
        "anchor": "one unrelated memory dated 720 hours before the probe, importance 1, never queried",
        "means": table,
        "old_fact_recall_at_30_gain_per_run": [round(d, 4) for d in diffs],
        "runs_where_the_anchor_raised_old_fact_recall": sum(1 for d in diffs if d > 0),
        "per_run": per_run,
    }
    path = Path(args.out) if args.out else root / "horizon.json"
    path.write_text(json.dumps(out, indent=2))
    print("\n| Stream | " + " | ".join(f"{a} h" for a in AGES) + " | old facts | all |")
    print("| --- |" + " --- |" * (len(AGES) + 2))
    for which, label in (("plain", "as recorded"), ("anchored", "with one 30-day-old memory")):
        t = table[which]
        print(
            f"| {label}: recall@30 | "
            + " | ".join(f"{t['by_age'][a]['recall_at_30']:.2f}" for a in AGES)
            + f" | {t['recall_old_at_30']:.2f} | {t['recall_at_30']:.2f} |"
        )
        print(f"| {label}: normalized recency | " + " | ".join(f"{t['by_age'][a]['normalized_recency']:.2f}" for a in AGES) + " | | |")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
