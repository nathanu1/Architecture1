"""Outcome metrics that experiment protocols can request by name (research extension).

Each metric is a function of a ``MetricContext`` (one finished run) that returns a flat dict of
run-level outcomes and writes its full detail to ``<run>/exports/metrics/<name>.json`` so every
number in an experiment table can be traced back to its records. Metrics that need model
calls (``evaluation`` probes, ``tom``) say so; the rest read the run's own tables.

| name | outcomes (run level) | needs model calls |
| --- | --- | --- |
| ``evaluation`` | the §7 measures: supported recall, attendance, relationship density, usage | yes (probes on clones) |
| ``network`` | social-network measures from relationship records at the end | no |
| ``behavior`` | pooled plan adherence, scheduled share, idle share, replans, reactions | no |
| ``memory_probe`` | planted-fact recall@k / MRR and own-experience recall on the final snapshot | no |
| ``beliefs`` | per topic: share of holders, knowledge coverage, conflicting-detail count | no |
| ``tom`` | Theory-of-Mind attribution precision / recall from interview probes | yes |
| ``adaptation`` | change of plans, latency and mentions after an intervention (``metric_params``) | no |
| ``usage`` | calls, tokens, cost, runtime from the manifest | no |
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import GAConfig, repo_path
from ..db import Database, parse_iso
from ..scenario.loader import Scenario, load_scenario
from .evidence import Topic, load_topics

Metric = Callable[["MetricContext"], dict[str, Any]]
REGISTRY: dict[str, Metric] = {}
NEEDS_MODEL = {"evaluation", "tom"}


def metric(name: str) -> Callable[[Metric], Metric]:
    def deco(fn: Metric) -> Metric:
        REGISTRY[name] = fn
        return fn

    return deco


@dataclass
class MetricContext:
    run_dir: Path
    cfg: GAConfig
    manifest: dict[str, Any]
    params: dict[str, Any] = field(default_factory=dict)
    provider: Any = None
    embedding_provider: Any = None

    @property
    def scenario(self) -> Scenario:
        if not hasattr(self, "_scenario"):
            self._scenario = load_scenario(
                repo_path(self.cfg.scenario.path), population=self.cfg.scenario.population, candidacy_seed_policy=self.cfg.scenario.candidacy_seed_policy
            )
        return self._scenario

    @property
    def agents(self) -> list[str]:
        return list(self.scenario.agent_ids)

    @property
    def topics(self) -> dict[str, Topic]:
        return load_topics(self.scenario.events)

    def state(self) -> Database:
        return Database(self.run_dir / "state.sqlite", read_only=True)

    def snapshot(self, name: str = "final") -> Path | None:
        db = self.state()
        try:
            info = (db.get_meta("snapshots", {}) or {}).get(name)
        finally:
            db.close()
        return self.run_dir / info["path"] if info else None

    def write(self, name: str, detail: Any) -> None:
        out = self.run_dir / "exports" / "metrics"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.json").write_text(json.dumps(detail, indent=2, default=str))


def run_metrics(ctx: MetricContext, names: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Run the named metrics; a failing metric is recorded by name, never silently skipped."""

    out: dict[str, Any] = {}
    failures: list[str] = []
    for name in names:
        fn = REGISTRY.get(name)
        if fn is None:
            failures.append(f"{name}: unknown metric (known: {', '.join(sorted(REGISTRY))})")
            continue
        try:
            out.update(fn(ctx))
        except Exception as exc:  # recorded in the row, like a failed run
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    return out, failures


# ---------------------------------------------------------------------- built-in metrics
@metric("usage")
def usage(ctx: MetricContext) -> dict[str, Any]:
    m = ctx.manifest
    u = m.get("budget", {}).get("usage", {}) or {}
    led = m.get("ledger", {}) or {}
    return {
        "calls": led.get("calls"),
        "input_tokens": led.get("input_tokens"),
        "output_tokens": led.get("output_tokens"),
        "cost_usd": u.get("cost_usd") if u.get("unpriced_calls", 1) == 0 else None,
        "runtime_s": round(u.get("runtime_s", 0.0), 1),
    }


@metric("evaluation")
def evaluation(ctx: MetricContext) -> dict[str, Any]:
    from .evaluate import evaluate_run
    from .experiment import run_outcomes

    p = ctx.params
    ev = evaluate_run(
        ctx.run_dir,
        ctx.cfg,
        relationships=bool(p.get("relationships", False)),
        min_minutes=float(p.get("min_minutes", 10.0)),
        provider=ctx.provider,
        embedding_provider=ctx.embedding_provider,
    )
    out = run_outcomes(ctx.run_dir, ev, ctx.manifest)
    fin = (ev.get("snapshots", {}).get("final", {}) or {}).get("relationships")
    if fin:
        out["probe_density_supported"] = fin.get("density_supported")
        out["probe_hallucinated_pct"] = fin.get("hallucinated_pct")
    return out


@metric("network")
def network_metric(ctx: MetricContext) -> dict[str, Any]:
    from ..social import network

    db = ctx.state()
    try:
        states = network.current_states(db)
        m = network.measures(ctx.agents, states, ctx.cfg.social.tie_threshold)
        start, end = ctx.cfg.scenario.start, parse_iso(db.get_meta("sim_time")) or ctx.cfg.scenario.end
        hours = int((end - start).total_seconds() // 3600)
        times = [start + (end - start) * i / max(1, min(hours, 48)) for i in range(0, min(hours, 48) + 1)]
        series = network.time_series(db, ctx.agents, times, ctx.cfg.social.tie_threshold)
    finally:
        db.close()
    ctx.write("network", {"final": m, "series": series})
    return {
        "network_density": m["density"],
        "network_edges": m["edge_count"],
        "network_components": m["components"],
        "network_largest_component": m["largest_component"],
        "network_isolates": m["isolates"],
        "network_reciprocity": m["reciprocity"],
        "network_clustering": m["clustering"],
        "mean_familiarity": m["mean_familiarity"],
        "mean_valence": m["mean_valence"],
        "relationship_records": m["records"],
    }


@metric("behavior")
def behavior_metric(ctx: MetricContext) -> dict[str, Any]:
    from .behavior import behavior, behavior_by_hour

    db = ctx.state()
    try:
        b = behavior(db, ctx.agents, start=ctx.cfg.scenario.start, end=parse_iso(db.get_meta("sim_time")))
        hours = behavior_by_hour(db, ctx.agents)
    finally:
        db.close()
    ctx.write("behavior", {**b, "by_hour": hours})
    return dict(b["pooled"])


@metric("memory_probe")
def memory_probe_metric(ctx: MetricContext) -> dict[str, Any]:
    from .memory_probe import load_facts, own_experiences, planted_facts

    snap = ctx.snapshot("final")
    if snap is None:
        raise FileNotFoundError("no final snapshot; the memory probe needs one")
    k = int(ctx.params.get("k", 10))
    facts = load_facts(ctx.params.get("facts"))
    planted = planted_facts(ctx.cfg, snap, ctx.agents, facts=facts, k=k, embedding_provider=ctx.embedding_provider)
    own = own_experiences(ctx.cfg, snap, ctx.agents, k=k, embedding_provider=ctx.embedding_provider)
    ctx.write("memory_probe", {"planted": planted, "own_experiences": own})
    ps = planted["summary"]
    return {
        "memory_recall_at_k": ps.get("recall_at_k"),
        "memory_recall_at_30": ps.get("recall_at_30"),
        "memory_mrr": ps.get("mean_reciprocal_rank"),
        "memory_recall_old": (ps.get("by_age") or {}).get(">24h"),
        "memory_recall_recent": (ps.get("by_age") or {}).get("<=1h"),
        "memory_forgotten": ps.get("forgotten"),
        "own_experience_recall": own["summary"].get("recall_at_k"),
    }


@metric("beliefs")
def beliefs_metric(ctx: MetricContext) -> dict[str, Any]:
    from ..cognition.beliefs import BeliefLedger

    db = ctx.state()
    try:
        ledger = BeliefLedger(db, ctx.topics, ctx.agents, before=parse_iso(db.get_meta("sim_time")))
        detail = ledger.to_dict()
    finally:
        db.close()
    ctx.write("beliefs", detail)
    out: dict[str, Any] = {}
    for key, s in detail["summary"]["topics"].items():
        short = key.split("_")[0]
        out[f"{short}_holders_pct"] = s["holders_pct"]
        out[f"{short}_knowledge_coverage"] = s["knowledge_coverage"]
        out[f"{short}_conflicting_details"] = len(s["with_conflicting_details"])
    return out


@metric("tom")
def tom_metric(ctx: MetricContext) -> dict[str, Any]:
    from ..cognition.beliefs import BeliefLedger
    from ..memory.masks import FULL
    from .interview import InterviewSession, write_jsonl
    from .tom import probe_tom, summarize

    snap = ctx.snapshot("final")
    if snap is None:
        raise FileNotFoundError("no final snapshot; the ToM probe needs one")
    db = Database(snap, read_only=True)
    try:
        ledger = BeliefLedger(db, ctx.topics, ctx.agents, before=parse_iso(db.get_meta("sim_time")))
    finally:
        db.close()
    run_id = ctx.manifest.get("run_id") or ctx.run_dir.name
    session = InterviewSession(
        ctx.cfg,
        snap,
        ledger_path=ctx.run_dir / "provider.sqlite",
        scope=f"{run_id}::tom",
        mask=FULL,
        provider=ctx.provider,
        embedding_provider=ctx.embedding_provider,
    )
    rows: list[dict[str, Any]] = []
    try:
        for topic in ctx.topics.values():
            if topic.probe_question:
                rows += probe_tom(session, topic, ctx.agents, ledger)
    finally:
        session.close()
    s = summarize(rows)
    out_dir = ctx.run_dir / "exports" / "tom"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "probes.jsonl", rows)
    ctx.write("tom", {"summary": s, "by_topic": {k: summarize([r for r in rows if r["event"] == k]) for k in ctx.topics}})
    return {
        "tom_pairs": s["pairs"],
        "tom_attribution_precision": s["attribution_precision"],
        "tom_attribution_recall": s["attribution_recall"],
        "tom_grounded_share": s["grounded_share_of_claims"],
        "tom_over_attributions": s["labels"].get("over_attribution", 0),
    }


@metric("adaptation")
def adaptation_metric(ctx: MetricContext) -> dict[str, Any]:
    from .behavior import adaptation

    p = ctx.params
    if "at" not in p or "keywords" not in p:
        raise ValueError("metric_params.adaptation needs 'at' (ISO time) and 'keywords'")
    db = ctx.state()
    try:
        out = adaptation(db, ctx.agents, datetime.fromisoformat(str(p["at"])), list(p["keywords"]), window_minutes=int(p.get("window_minutes", 120)))
    finally:
        db.close()
    ctx.write("adaptation", out)
    return {
        "adaptation_perceivers": len(out["perceived"]),
        "adaptation_changed_share": out["changed_share"],
        "adaptation_changed_among_perceivers": out["changed_share_among_perceivers"],
        "adaptation_median_latency_min": out["median_latency_minutes"],
        "adaptation_mentions": out["mentions_in_conversation"],
        "adaptation_agents_mentioning": out["agents_mentioning"],
    }
