"""Independent-run experiments: conditions × seeds, run-level outcomes, exploratory statistics.

Originally the reflection extension (prompt §10; spec R-1 … R-3): whole simulations from the
same authored world that differ only in their condition's overrides, matched by seed. The
research platform (docs/research_platform.md) generalizes the protocol while keeping that
design:

* **conditions** are any config overrides (memory, planning, social, dialogue, ...);
* **metrics** are picked by name from ``evaluation.metrics`` (diffusion and attendance
  probes, social network, behavior, retrieval probes, beliefs, Theory of Mind, adaptation,
  usage), and ``primary_outcomes`` may name any outcome they produce;
* **fork_from** turns the protocol into a counterfactual: every run continues from the same
  snapshot of a recorded run instead of starting fresh;
* **interventions** per condition are scheduled into each run (``interventions.yaml``);
* **determinism_check** re-runs one configuration and compares state hashes, which documents
  whether the model sampling is reproducible on this setup.

The run is the unit of analysis. Primary outcomes are fixed in the protocol before running.
Runs matched by seed share the initial world; with a hosted model this does not make the
sampled behavior identical, and every report says so. Failed and budget-truncated runs stay
in the table with their reason. A handful of runs per condition is exploratory; intervals
and p-values are descriptive.

``plan`` and ``estimate`` never call a model. ``execute`` runs only when called explicitly.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from ..config import apply_overrides, load_raw, repo_path
from .interview import write_csv
from .plots import strip_chart

PRIMARY = ("supported_party_recall", "supported_candidacy_recall", "invited_attendance_rate")
SECONDARY = ("invited", "exposed_party", "unsupported_claims", "calls", "input_tokens", "output_tokens", "cost_usd", "runtime_s")
NOT_OUTCOMES = {"condition", "seed", "run_id", "run_dir", "mode", "status", "stop_detail", "wall_s", "metric_failures", "forked_from"}


@dataclass
class Protocol:
    name: str
    base_config: str
    conditions: dict[str, list[str]]
    seeds: list[int]
    question: str = ""
    hypothesis: str = ""
    primary_outcomes: list[str] = field(default_factory=lambda: list(PRIMARY))
    evaluate_relationships: bool = False
    min_minutes: float = 10.0
    output_dir: str = "runs/experiments"
    path: str | None = None
    # research platform extensions
    metrics: list[str] = field(default_factory=lambda: ["evaluation"])
    metric_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    fork_from: dict[str, str] | None = None  # {"run_dir": ..., "snapshot": ...}
    interventions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # condition -> interventions
    determinism_check: bool = False

    @classmethod
    def load(cls, path: str | Path) -> Protocol:
        p = Path(path) if Path(path).exists() else repo_path(str(path))
        d = yaml.safe_load(p.read_text())
        metrics = list(d.get("metrics", ["evaluation"]))
        if "usage" not in metrics:
            metrics.append("usage")
        return cls(
            name=d["name"],
            base_config=d["base_config"],
            conditions={k: list(v or []) for k, v in d["conditions"].items()},
            seeds=list(d["seeds"]),
            question=d.get("question", ""),
            hypothesis=d.get("hypothesis", ""),
            primary_outcomes=list(d.get("primary_outcomes", PRIMARY)),
            evaluate_relationships=bool(d.get("evaluate_relationships", False)),
            min_minutes=float(d.get("min_minutes", 10.0)),
            output_dir=d.get("output_dir", "runs/experiments"),
            path=str(p),
            metrics=metrics,
            metric_params={k: dict(v or {}) for k, v in (d.get("metric_params") or {}).items()},
            fork_from=dict(d["fork_from"]) if d.get("fork_from") else None,
            interventions={k: list(v or []) for k, v in (d.get("interventions") or {}).items()},
            determinism_check=bool(d.get("determinism_check", False)),
        )

    def params_for(self, metric: str) -> dict[str, Any]:
        p = dict(self.metric_params.get(metric, {}))
        if metric == "evaluation":
            p.setdefault("relationships", self.evaluate_relationships)
            p.setdefault("min_minutes", self.min_minutes)
        return p

    def needs_model(self) -> list[str]:
        from .metrics import NEEDS_MODEL

        return [m for m in self.metrics if m in NEEDS_MODEL]

    def root(self) -> Path:
        return repo_path(self.output_dir) / self.name

    def runs(self) -> list[dict[str, Any]]:
        return [
            {"condition": c, "seed": s, "run_id": f"{c}-s{s}", "overrides": [*ov, f"run.seed={s}", f"run.name={self.name}-{c}-s{s}"]}
            for s in self.seeds
            for c, ov in self.conditions.items()
        ]

    def config_for(self, run: dict[str, Any]) -> Any:
        from ..config import GAConfig

        if self.fork_from:
            raw = yaml.safe_load((self._fork_source() / "config.yaml").read_text())
        else:
            raw = load_raw(self.base_config)
        return GAConfig.model_validate(apply_overrides(raw, run["overrides"]))

    def _fork_source(self) -> Path:
        assert self.fork_from is not None
        src = Path(self.fork_from["run_dir"])
        return src if src.exists() else repo_path(self.fork_from["run_dir"])


def estimate(protocol: Protocol, measured_run: str | Path | None = None) -> dict[str, Any]:
    """Project calls and tokens from a measured pilot run; never invents prices."""

    runs = protocol.runs()
    cfg = protocol.config_for(runs[0])
    out: dict[str, Any] = {
        "runs": len(runs),
        "mode": cfg.run_mode,
        "limits_per_run": cfg.budget.model_dump(),
        "basis": None,
    }
    if measured_run is None:
        out["basis"] = "no measured pilot run; run one condition once and pass --measured-run to project usage"
        return out
    m = json.loads((Path(measured_run) / "manifest.json").read_text())
    led = m["ledger"]
    out["basis"] = f"measured run {m['run_id']} ({m['mode']}, status {m['status']}, sim time {m['sim_time']})"
    per = {"calls": led.get("calls") or 0, "input_tokens": led.get("input_tokens") or 0, "output_tokens": led.get("output_tokens") or 0}
    out["per_run_measured"] = per
    out["total_projected"] = {k: v * len(runs) for k, v in per.items()}
    cost = m["budget"]["usage"].get("cost_usd")
    priced = m["budget"]["usage"].get("unpriced_calls", 1) == 0 and cost is not None
    out["cost_projected_usd"] = round(cost * len(runs), 2) if priced and cost else None
    if not priced:
        out["cost_note"] = "unpriced: configure budget.pricing_file with current published prices to project cost"
    return out


def run_outcomes(run_dir: Path, evaluation: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    final = evaluation.get("snapshots", {}).get("final", {})
    diff = final.get("diffusion", {})
    party = diff.get("valentines_party", {})
    cand = diff.get("mayor_candidacy", {})
    att = evaluation.get("attendance") or {}
    inv = att.get("among_invited", {}) if att else {}
    usage = manifest.get("budget", {}).get("usage", {})
    return {
        "supported_party_recall": round(party["supported_aware"] / party["n"], 3) if party.get("n") else None,
        "supported_candidacy_recall": round(cand["supported_aware"] / cand["n"], 3) if cand.get("n") else None,
        "invited_attendance_rate": inv.get("rate"),
        "invited": inv.get("n"),
        "invited_attended": inv.get("attended"),
        "exposed_party": (att.get("among_exposed") or {}).get("n") if att else None,
        "unsupported_claims": (party.get("claimed_unsupported") or 0) + (cand.get("claimed_unsupported") or 0) if party or cand else None,
        "calls": manifest.get("ledger", {}).get("calls"),
        "input_tokens": manifest.get("ledger", {}).get("input_tokens"),
        "output_tokens": manifest.get("ledger", {}).get("output_tokens"),
        "cost_usd": usage.get("cost_usd") if usage.get("unpriced_calls", 1) == 0 else None,
        "runtime_s": round(usage.get("runtime_s", 0.0), 1),
    }


def _run_one(protocol: Protocol, run: dict[str, Any], run_dir: Path, *, provider_factory: Any, embedding_factory: Any) -> dict[str, Any]:
    from ..simulation.engine import Simulation, load_run_config, save_config
    from .metrics import MetricContext, run_metrics

    cfg = protocol.config_for(run)
    row: dict[str, Any] = {"condition": run["condition"], "seed": run["seed"], "run_id": run["run_id"], "run_dir": str(run_dir), "mode": cfg.run_mode}
    t0 = time.time()
    try:
        if protocol.fork_from and not (run_dir / "state.sqlite").exists():
            from ..simulation.fork import fork_run

            origin = fork_run(
                protocol._fork_source(),
                protocol.fork_from.get("snapshot", "final"),
                run_dir,
                overrides=run["overrides"],
                interventions=protocol.interventions.get(run["condition"]),
                label=f"{protocol.name}:{run['condition']}",
            )
            row["forked_from"] = f"{origin['run_id']}@{origin['snapshot']}"
            cfg = load_run_config(run_dir)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            if not (run_dir / "config.yaml").exists():
                save_config(cfg, run_dir)
            items = protocol.interventions.get(run["condition"])
            if items is not None and not (run_dir / "interventions.yaml").exists():
                (run_dir / "interventions.yaml").write_text(yaml.safe_dump({"interventions": items}, sort_keys=False, allow_unicode=True))
        sim = Simulation(
            cfg,
            run_dir,
            provider=provider_factory(run) if provider_factory else None,
            embedding_provider=embedding_factory(run) if embedding_factory else None,
        )
        status = sim.status if sim.status == "completed" else sim.run()
        sim.close()
        row["status"] = status
        manifest = json.loads((run_dir / "manifest.json").read_text())
        row["mode"] = manifest.get("mode", row["mode"])
        row["stop_detail"] = (manifest.get("stop_detail") or {}).get("detail")
        if status == "completed":
            ctx = MetricContext(
                run_dir,
                cfg,
                manifest,
                provider=provider_factory(run) if provider_factory else None,
                embedding_provider=embedding_factory(run) if embedding_factory else None,
            )
            for name in protocol.metrics:
                ctx.params = protocol.params_for(name)
                values, failures = run_metrics(ctx, [name])
                row.update(values)
                if failures:
                    row["metric_failures"] = (row.get("metric_failures") or []) + failures
        else:
            row.update({k: None for k in protocol.primary_outcomes})
    except Exception as exc:  # recorded, never hidden
        row["status"] = "error"
        row["stop_detail"] = f"{type(exc).__name__}: {exc}"
    row["wall_s"] = round(time.time() - t0, 1)
    return row


STATE_TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")


def determinism_check(protocol: Protocol, root: Path, *, provider_factory: Any = None, embedding_factory: Any = None) -> dict[str, Any]:
    """Re-run the first configuration into a fresh directory and compare the committed state.

    Identical hashes mean the whole pipeline, model sampling included, reproduced itself on
    this setup; different hashes mean the model (or server) sampled differently, which the
    report then states next to every comparison.
    """

    from ..db import Database

    first = protocol.runs()[0]
    repeat = dict(first, run_id=f"{first['run_id']}-repeat")
    row = _run_one(protocol, repeat, root / repeat["run_id"], provider_factory=provider_factory, embedding_factory=embedding_factory)
    hashes = {}
    for rid in (first["run_id"], repeat["run_id"]):
        path = root / rid / "state.sqlite"
        if path.exists():
            db = Database(path, read_only=True)
            try:
                hashes[rid] = db.content_hash(STATE_TABLES)
            finally:
                db.close()
    identical = len(hashes) == 2 and len(set(hashes.values())) == 1
    return {
        "compared": list(hashes),
        "identical": identical,
        "status": row.get("status"),
        "note": "same seed and configuration run twice; state tables " + ", ".join(STATE_TABLES),
    }


def execute(protocol: Protocol, *, provider_factory: Any = None, embedding_factory: Any = None, progress: Any = None) -> dict[str, Any]:
    root = protocol.root()
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for run in protocol.runs():
        row = _run_one(protocol, run, root / run["run_id"], provider_factory=provider_factory, embedding_factory=embedding_factory)
        rows.append(row)
        if progress:
            progress(row)
    summary = summarize(rows, protocol)
    if protocol.determinism_check:
        summary["determinism"] = determinism_check(protocol, root, provider_factory=provider_factory, embedding_factory=embedding_factory)
    write_csv(root / "runs.csv", rows, list(dict.fromkeys(k for r in rows for k in r)))
    for k in protocol.primary_outcomes:
        pts = {c: [(r["run_id"], r[k]) for r in rows if r["condition"] == c and isinstance(r.get(k), int | float)] for c in protocol.conditions}
        (root / f"outcome_{k}.svg").write_text(strip_chart(k.replace("_", " "), pts))
    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (root / "report.md").write_text(render(protocol, rows, summary))
    (root / "protocol.json").write_text(json.dumps(protocol.__dict__, indent=2, default=str))
    return {"rows": rows, "summary": summary, "dir": str(root)}


def _bootstrap_diff(a: list[float], b: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float] | None:
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    diffs = sorted(statistics.mean(rng.choices(a, k=len(a))) - statistics.mean(rng.choices(b, k=len(b))) for _ in range(n))
    return (round(diffs[int(0.025 * n)], 3), round(diffs[int(0.975 * n) - 1], 3))


def _permutation_p(a: list[float], b: list[float]) -> float | None:
    """Exact two-sided permutation test on the difference in means (small n only)."""

    if not a or not b or len(a) + len(b) > 16:
        return None
    pooled = a + b
    obs = abs(statistics.mean(a) - statistics.mean(b))
    count = total = 0
    for idx in combinations(range(len(pooled)), len(a)):
        sa = [pooled[i] for i in idx]
        sb = [pooled[i] for i in range(len(pooled)) if i not in idx]
        total += 1
        if abs(statistics.mean(sa) - statistics.mean(sb)) >= obs - 1e-12:
            count += 1
    return round(count / total, 4)


def outcome_keys(rows: list[dict[str, Any]], protocol: Protocol) -> list[str]:
    """Primary outcomes first, then every other numeric outcome any row produced."""

    keys = list(protocol.primary_outcomes)
    for r in rows:
        for k, v in r.items():
            if k not in keys and k not in NOT_OUTCOMES and (isinstance(v, int | float | type(None)) and not isinstance(v, bool)):
                keys.append(k)
    return keys


def _numeric(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def summarize(rows: list[dict[str, Any]], protocol: Protocol) -> dict[str, Any]:
    conds = list(protocol.conditions)
    keys = outcome_keys(rows, protocol)
    out: dict[str, Any] = {
        "protocol": protocol.name,
        "unit": "run",
        "conditions": {},
        "comparisons": {},
        "excluded": [],
        "outcomes": keys,
        "primary": list(protocol.primary_outcomes),
    }
    for c in conds:
        rs = [r for r in rows if r["condition"] == c]
        out["conditions"][c] = {"runs": len(rs), "completed": len([r for r in rs if r.get("status") == "completed"]), "outcomes": {}}
        for k in keys:
            vals = [r[k] for r in rs if _numeric(r.get(k))]
            out["conditions"][c]["outcomes"][k] = (
                {
                    "n": len(vals),
                    "mean": round(statistics.mean(vals), 3),
                    "sd": round(statistics.stdev(vals), 3) if len(vals) > 1 else None,
                    "median": statistics.median(vals),
                    "min": min(vals),
                    "max": max(vals),
                }
                if vals
                else {"n": 0}
            )
    out["excluded"] = [{"run_id": r["run_id"], "status": r.get("status"), "reason": r.get("stop_detail")} for r in rows if r.get("status") != "completed"]
    out["metric_failures"] = {r["run_id"]: r["metric_failures"] for r in rows if r.get("metric_failures")}
    if 2 <= len(conds) <= 6:
        for a, b in combinations(conds, 2):
            for k in protocol.primary_outcomes:
                va = [r[k] for r in rows if r["condition"] == a and _numeric(r.get(k))]
                vb = [r[k] for r in rows if r["condition"] == b and _numeric(r.get(k))]
                name = k if len(conds) == 2 else f"{k} ({a} vs {b})"
                out["comparisons"][name] = {
                    "outcome": k,
                    "difference": f"{a} - {b}",
                    "mean_difference": round(statistics.mean(va) - statistics.mean(vb), 3) if va and vb else None,
                    "bootstrap_95ci": _bootstrap_diff(va, vb),
                    "permutation_p": _permutation_p(va, vb),
                    "n": [len(va), len(vb)],
                    "note": "exploratory; run-level; not powered",
                }
    return out


LABELS = {
    "supported_party_recall": "Party recall (supported)",
    "supported_candidacy_recall": "Candidacy recall (supported)",
    "invited_attendance_rate": "Attendance among invited guests",
    "invited": "Invited guests",
    "exposed_party": "Agents exposed to the party",
    "unsupported_claims": "Unsupported claims",
    "calls": "Model calls",
    "input_tokens": "Input tokens",
    "output_tokens": "Output tokens",
    "cost_usd": "Cost (USD)",
    "runtime_s": "Runtime (s)",
    "network_density": "Network density (mutual ties)",
    "network_components": "Network components",
    "network_reciprocity": "Reciprocity",
    "network_clustering": "Clustering",
    "mean_familiarity": "Mean familiarity",
    "mean_valence": "Mean valence",
    "scheduled_share": "Scheduled share of actions",
    "plan_adherence": "Plan adherence (hour blocks followed)",
    "idle_share": "Idle share",
    "replans_per_agent": "Replans per agent",
    "reaction_rate": "Reaction rate (non-continue)",
    "conversations_per_agent": "Conversations per agent",
    "memory_recall_at_k": "Planted-fact recall@k",
    "memory_mrr": "Planted-fact MRR",
    "memory_recall_old": "Recall of facts older than a day",
    "memory_recall_recent": "Recall of facts under an hour old",
    "own_experience_recall": "Own-conversation recall@k",
    "tom_attribution_precision": "ToM attribution precision",
    "tom_attribution_recall": "ToM attribution recall",
    "adaptation_changed_share": "Agents who changed plans (share)",
    "adaptation_changed_among_perceivers": "Changed plans among perceivers",
    "adaptation_median_latency_min": "Median adaptation latency (min)",
    "adaptation_mentions": "Conversations mentioning the event",
}


def _num(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


def _cell(stats: dict[str, Any], key: str) -> str:
    if not stats.get("n"):
        return "unpriced" if key == "cost_usd" else "n/a"
    sd = f" ± {_num(stats['sd'])}" if stats.get("sd") is not None else ""
    return f"{_num(stats['mean'])}{sd} (median {_num(stats['median'])}; {_num(stats['min'])}–{_num(stats['max'])}; n={stats['n']})"


def _label(k: str) -> str:
    return LABELS.get(k, k.replace("_", " "))


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(protocol: Protocol, rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    modes = Counter(str(r.get("mode") or "unknown") for r in rows)
    not_live = sorted(set(modes) - {"live"})
    conds = list(protocol.conditions)
    lines = [f"# Experiment: {protocol.name}", "", protocol.question or "", ""]
    if protocol.hypothesis:
        lines += [f"**Hypothesis (fixed before running):** {protocol.hypothesis}", ""]
    if not_live:
        source = " with the offline mock" if "mock" in modes else ""
        lines += [f"> **{' + '.join(m.upper() for m in not_live)} RUNS.** These numbers exercise the pipeline{source}; they say nothing about reflection.", ""]
    lines += ["## Conditions", ""]
    for c, ov in protocol.conditions.items():
        extra = f"; interventions: {len(protocol.interventions[c])}" if c in protocol.interventions else ""
        lines.append(f"* `{c}`: " + (", ".join(f"`{o}`" for o in ov) if ov else "base configuration") + extra)
    if protocol.fork_from:
        lines += [
            "",
            f"Every run is a fork of `{protocol.fork_from['run_dir']}` at snapshot `{protocol.fork_from.get('snapshot', 'final')}`: the same past, different futures.",
        ]
    lines += [
        "",
        f"Seeds {protocol.seeds}. Runs are matched by seed; a hosted model does not reproduce identical samples, so matching is of the initial world, not of the randomness. "
        f"Metrics: {', '.join(protocol.metrics)}.",
    ]
    det = summary.get("determinism")
    if det:
        verdict = "identical" if det["identical"] else "DIFFERENT"
        lines += ["", f"Determinism check: the first configuration was run twice; committed state tables were **{verdict}** ({det['note']})."]
    lines += ["", "Each run links to its evaluation report when the `evaluation` metric ran.", ""]
    prim = list(protocol.primary_outcomes)
    head = ["Run", "Condition", "Seed", "Status", *[_label(k) for k in prim], "Calls", "Runtime (s)"]
    lines += ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for r in rows:
        has_report = (Path(r["run_dir"]) / "exports" / "evaluation" / "report.md").exists()
        name = f"[{r['run_id']}]({r['run_id']}/exports/evaluation/report.md)" if has_report else r["run_id"]
        cells = [name, r["condition"], str(r["seed"]), str(r.get("status")), *[_fmt(r.get(k)) for k in prim], _fmt(r.get("calls")), _fmt(r.get("runtime_s"))]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## By condition", "", "| Outcome | " + " | ".join(conds) + " |", "| --- |" + " --- |" * len(conds)]
    for k in summary.get("outcomes", prim):
        label = _label(k)
        label = f"**{label}**" if k in prim else label
        cells = [_cell(summary["conditions"].get(c, {}).get("outcomes", {}).get(k, {}), k) for c in conds]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "Mean ± SD (median; range; runs with a value). Primary outcomes, fixed in the protocol before running, are in bold."]
    lines += ["", "## Comparisons (exploratory)", ""]
    for k, v in summary.get("comparisons", {}).items():
        lines.append(
            f"* **{k}**: {v['difference']} = {v['mean_difference']} (bootstrap 95% CI {v['bootstrap_95ci']}, exact permutation p = {v['permutation_p']}, n = {v['n']})"
        )
    if not summary.get("comparisons"):
        lines.append("* none (one condition, or more than six)")
    plots = [k for k in prim if (protocol.root() / f"outcome_{k}.svg").exists()]
    if plots:
        lines += ["", "One dot per run; the bar is the condition mean.", ""] + [f"![{_label(k)}](outcome_{k}.svg)" for k in plots]
    if summary.get("excluded"):
        lines += ["", "## Runs without outcomes", ""] + [f"* {e['run_id']}: {e['status']} — {e['reason']}" for e in summary["excluded"]]
    if summary.get("metric_failures"):
        lines += ["", "## Metric failures", ""] + [f"* {rid}: {'; '.join(f)}" for rid, f in summary["metric_failures"].items()]
    lines += ["", "_Run modes: " + ", ".join(f"{m} × {n}" for m, n in sorted(modes.items())) + "._", ""]
    lines += ["Simulated characters: plausible behavior here does not establish validity for real people.", ""]
    return "\n".join(lines)
