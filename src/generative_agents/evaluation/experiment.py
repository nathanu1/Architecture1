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
  whether the model sampling is reproducible on this setup;
* **fork_from.run_dir** may contain ``{seed}``: every seed then forks from its *own* recorded
  past, so replicates differ before the fork point as well (with the mock a fork's seed alone
  changes nothing, which makes same-source forks copies, not replicates). ``fork_from.create``
  names the config and overrides that produce a missing source run;
* **jobs** runs independent simulations in parallel worker processes (``ga experiment --jobs``);
* comparisons are reported **unpaired** (exact or Monte-Carlo permutation of run labels) and
  **paired by seed** (sign-flip permutation of the per-seed differences, effect size d_z),
  each with the smallest p-value its design can produce, and Holm-adjusted across the
  protocol's primary comparisons.

The run is the unit of analysis. Primary outcomes are fixed in the protocol before running.
Runs matched by seed share the initial world; with a hosted model this does not make the
sampled behavior identical, and every report says so. Failed and budget-truncated runs stay
in the table with their reason. A handful of runs per condition is exploratory; intervals
and p-values are descriptive.

``plan`` and ``estimate`` never call a model. ``execute`` runs only when called explicitly.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import combinations, product
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
    fork_from: dict[str, Any] | None = None  # {"run_dir": ... ("{seed}" allowed), "snapshot": ..., "create": {"config": ..., "overrides": [...]}}
    interventions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # condition -> interventions
    determinism_check: bool = False
    # Planned contrasts, fixed with the hypothesis:
    # [{"outcome": ..., "a": ..., "b": ..., "expect": ">" | "<" | ">=" | "<=" | "=", "tolerance": 0.0, "outcome_b": ...}].
    # ``outcome_b`` compares two different outcomes (for example a probe variant against the
    # paper weights on the same snapshots, with a == b).
    # When given, they are the family for the multiplicity adjustment; every other pairwise
    # comparison is still reported, as exploration.
    contrasts: list[dict[str, Any]] = field(default_factory=list)

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
            contrasts=[dict(c) for c in (d.get("contrasts") or [])],
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

        if self.fork_from and (self._fork_source(run["seed"]) / "config.yaml").exists():
            raw = yaml.safe_load((self._fork_source(run["seed"]) / "config.yaml").read_text())
        elif self.fork_from and self.fork_from.get("create"):
            raw = self._source_raw(run["seed"])  # the source has not been run yet (planning, estimates)
        else:
            raw = load_raw(self.base_config)
        return GAConfig.model_validate(apply_overrides(raw, run["overrides"]))

    def _fork_source(self, seed: int | None = None) -> Path:
        """The run a fork continues. ``{seed}`` in ``fork_from.run_dir`` gives every seed its own past."""

        assert self.fork_from is not None
        template = str(self.fork_from["run_dir"])
        name = template.format(seed=seed if seed is not None else self.seeds[0]) if "{seed}" in template else template
        src = Path(name)
        return src if src.is_absolute() or src.exists() else repo_path(name)

    def per_seed_sources(self) -> bool:
        return bool(self.fork_from) and "{seed}" in str(self.fork_from["run_dir"])

    def _source_raw(self, seed: int) -> dict[str, Any]:
        assert self.fork_from is not None
        create = self.fork_from.get("create") or {}
        raw = load_raw(create.get("config") or self.base_config)
        overrides = [str(o) for o in create.get("overrides") or []]
        if self.per_seed_sources():
            overrides.append(f"run.seed={seed}")
        return apply_overrides(raw, overrides)

    def source_runs(self) -> list[dict[str, Any]]:
        """Source runs that ``fork_from.create`` must produce: one per seed, or a single shared one."""

        if not self.fork_from or not self.fork_from.get("create"):
            return []
        seeds = self.seeds if self.per_seed_sources() else self.seeds[:1]
        return [{"seed": s, "run_dir": self._fork_source(s)} for s in seeds]


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
                protocol._fork_source(run["seed"]),
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


def _make_source(protocol: Protocol, seed: int) -> dict[str, Any]:
    """Run one fork source (``fork_from.create``) unless its snapshot already exists."""

    from ..config import GAConfig
    from ..simulation.engine import Simulation, save_config

    assert protocol.fork_from is not None
    run_dir = protocol._fork_source(seed)
    name = str(protocol.fork_from.get("snapshot", "final"))
    snap = run_dir / "snapshots" / f"{name}.sqlite"
    out = {"seed": seed, "run_dir": str(run_dir), "snapshot": name}
    if snap.exists():
        return {**out, "status": "exists"}
    t0 = time.time()
    try:
        cfg = GAConfig.model_validate(protocol._source_raw(seed))
        run_dir.mkdir(parents=True, exist_ok=True)
        if not (run_dir / "config.yaml").exists():
            save_config(cfg, run_dir)
        sim = Simulation(cfg, run_dir)
        status = sim.status if sim.status == "completed" else sim.run()
        sim.close()
        out["status"] = status if snap.exists() else f"{status}, but snapshot {name!r} was not written (add its time to output.snapshots)"
    except Exception as exc:  # recorded; the forks of this source then fail visibly
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    out["wall_s"] = round(time.time() - t0, 1)
    return out


def _worker(protocol: Protocol, run: dict[str, Any], run_dir: str) -> dict[str, Any]:
    return _run_one(protocol, run, Path(run_dir), provider_factory=None, embedding_factory=None)


def _pool(jobs: int) -> ProcessPoolExecutor:
    # Each worker is a whole simulation; numerical libraries must not multiply the threads.
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "TOKENIZERS_PARALLELISM"):
        os.environ.setdefault(var, "false" if var == "TOKENIZERS_PARALLELISM" else "1")
    return ProcessPoolExecutor(max_workers=jobs)


def execute(protocol: Protocol, *, provider_factory: Any = None, embedding_factory: Any = None, progress: Any = None, jobs: int = 1) -> dict[str, Any]:
    """Run every condition × seed. ``jobs`` > 1 runs simulations in parallel worker processes.

    Parallel workers build their providers from each run's config, so ``jobs`` is ignored
    when a provider or embedding factory is injected (tests). Rows keep the protocol's order
    whatever order the workers finish in.
    """

    root = protocol.root()
    root.mkdir(parents=True, exist_ok=True)
    runs = protocol.runs()
    parallel = jobs > 1 and provider_factory is None and embedding_factory is None
    sources = []
    todo = protocol.source_runs()
    if todo and parallel and len(todo) > 1:
        with _pool(jobs) as pool:
            sources = list(pool.map(_make_source, [protocol] * len(todo), [t["seed"] for t in todo]))
    else:
        sources = [_make_source(protocol, t["seed"]) for t in todo]
    if progress:
        for src in sources:
            progress({"run_id": f"source {src['run_dir']}", "status": src["status"]})
    if parallel:
        done: dict[str, dict[str, Any]] = {}
        with _pool(jobs) as pool:
            futures = {pool.submit(_worker, protocol, run, str(root / run["run_id"])): run for run in runs}
            for fut in as_completed(futures):
                run = futures[fut]
                try:
                    row = fut.result()
                except Exception as exc:  # a crashed worker is a failed run, not a lost one
                    row = {
                        "condition": run["condition"],
                        "seed": run["seed"],
                        "run_id": run["run_id"],
                        "run_dir": str(root / run["run_id"]),
                        "status": "error",
                        "stop_detail": f"worker: {type(exc).__name__}: {exc}",
                    }
                done[run["run_id"]] = row
                if progress:
                    progress(row)
        rows = [done[run["run_id"]] for run in runs]
    else:
        rows = []
        for run in runs:
            row = _run_one(protocol, run, root / run["run_id"], provider_factory=provider_factory, embedding_factory=embedding_factory)
            rows.append(row)
            if progress:
                progress(row)
    extra: dict[str, Any] = {}
    if sources:
        extra["fork_sources"] = sources
    if protocol.determinism_check:
        extra["determinism"] = determinism_check(protocol, root, provider_factory=provider_factory, embedding_factory=embedding_factory)
    summary = write_outputs(protocol, rows, root, extra)
    return {"rows": rows, "summary": summary, "dir": str(root)}


def write_outputs(protocol: Protocol, rows: list[dict[str, Any]], root: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summary, tables, charts and the report from finished rows (also used by ``rebuild``)."""

    from .detail import detail_sections

    summary = {**summarize(rows, protocol), **(extra or {})}
    write_csv(root / "runs.csv", rows, list(dict.fromkeys(k for r in rows for k in r)))
    (root / "rows.json").write_text(json.dumps(rows, indent=2, default=str))
    for k in protocol.primary_outcomes:
        pts = {c: [(r["run_id"], r[k]) for r in rows if r["condition"] == c and isinstance(r.get(k), int | float)] for c in protocol.conditions}
        (root / f"outcome_{k}.svg").write_text(strip_chart(k.replace("_", " "), pts))
    lines, detail = detail_sections(rows, list(protocol.conditions), protocol.metrics, root)
    if detail:
        (root / "detail.json").write_text(json.dumps(detail, indent=2, default=str))
    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (root / "report.md").write_text(render(protocol, rows, summary, detail=lines))
    (root / "protocol.json").write_text(json.dumps(protocol.__dict__, indent=2, default=str))
    return summary


def _coerce(value: str) -> Any:
    if value == "":
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    if value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def load_rows(root: Path) -> list[dict[str, Any]]:
    """The rows of an executed experiment: ``rows.json``, or ``runs.csv`` from before it existed."""

    if (root / "rows.json").exists():
        return json.loads((root / "rows.json").read_text())
    import csv

    with (root / "runs.csv").open(newline="") as f:
        return [
            {k: (v if k in ("run_id", "condition", "run_dir", "status", "mode", "stop_detail", "forked_from") else _coerce(v)) for k, v in r.items()}
            for r in csv.DictReader(f)
        ]


def rebuild(protocol: Protocol) -> dict[str, Any]:
    """Re-analyse an executed experiment from its saved rows: no simulation, no model, no probe.

    Used after the analysis itself changed (new comparisons, new report sections) and to
    check that a report follows from its rows. Sources and the determinism result are
    carried over from the existing summary.
    """

    root = protocol.root()
    rows = load_rows(root)
    old = json.loads((root / "summary.json").read_text()) if (root / "summary.json").exists() else {}
    extra = {k: old[k] for k in ("fork_sources", "determinism") if k in old}
    summary = write_outputs(protocol, rows, root, extra)
    return {"rows": rows, "summary": summary, "dir": str(root)}


def _bootstrap_diff(a: list[float], b: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float] | None:
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    diffs = sorted(statistics.mean(rng.choices(a, k=len(a))) - statistics.mean(rng.choices(b, k=len(b))) for _ in range(n))
    return (round(diffs[int(0.025 * n)], 3), round(diffs[int(0.975 * n) - 1], 3))


def _bootstrap_mean(vals: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float] | None:
    """Percentile bootstrap interval of a mean (None below three values)."""

    if len(vals) < 3:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(vals, k=len(vals))) for _ in range(n))
    return (round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3))


EXACT_LABEL_LIMIT = 16  # C(16, 8) = 12,870 relabelings
EXACT_SIGN_LIMIT = 16  # 2 ** 16 = 65,536 sign patterns
MONTE_CARLO_DRAWS = 20000


def _permutation_test(a: list[float], b: list[float], seed: int = 0) -> dict[str, Any] | None:
    """Two-sided permutation test on the difference in means of two independent groups.

    Exact (every relabeling) up to ``EXACT_LABEL_LIMIT`` pooled values, Monte Carlo beyond.
    ``min_p`` is the smallest p this design can give (perfectly separated groups), so a
    reader can tell "p = 0.1" from "p = 0.1, the floor with three runs a side".
    """

    if not a or not b:
        return None
    pooled = a + b
    n, na = len(pooled), len(a)
    obs = abs(statistics.mean(a) - statistics.mean(b))
    total_sum = sum(pooled)

    def extreme(sa_sum: float) -> bool:
        return abs(sa_sum / na - (total_sum - sa_sum) / (n - na)) >= obs - 1e-12

    relabelings = math.comb(n, na)
    if n <= EXACT_LABEL_LIMIT:
        count = sum(1 for idx in combinations(range(n), na) if extreme(sum(pooled[i] for i in idx)))
        p, method = count / relabelings, "exact"
    else:
        rng = random.Random(seed)
        count = 1  # the observed labeling counts (Phipson & Smyth 2010)
        for _ in range(MONTE_CARLO_DRAWS):
            if extreme(sum(rng.sample(pooled, na))):
                count += 1
        p, method = count / (MONTE_CARLO_DRAWS + 1), f"monte-carlo ({MONTE_CARLO_DRAWS} draws)"
    floor = (2 if na == n - na else 1) / relabelings
    return {"p": round(p, 4), "method": method, "min_p": round(max(floor, 1 / (MONTE_CARLO_DRAWS + 1)) if method != "exact" else floor, 5)}


def _permutation_p(a: list[float], b: list[float]) -> float | None:
    """Two-sided permutation p for the difference in means (kept for callers of the old name)."""

    t = _permutation_test(a, b)
    return t["p"] if t else None


def _paired_test(a: dict[int, float], b: dict[int, float], seed: int = 0) -> dict[str, Any] | None:
    """Matched-seed comparison: per-seed differences, sign-flip permutation, effect size d_z.

    Conditions are run on the same seeds, so the natural unit is the within-seed difference.
    Under the null the sign of each difference is exchangeable; the test enumerates all
    ``2 ** n`` sign patterns (Monte Carlo above ``EXACT_SIGN_LIMIT`` seeds).
    """

    seeds = sorted(set(a) & set(b))
    if len(seeds) < 2:
        return None
    d = [a[s] - b[s] for s in seeds]
    n = len(d)
    mean_d = statistics.mean(d)
    sd_d = statistics.stdev(d)
    obs = abs(sum(d))
    if all(abs(x) <= 1e-12 for x in d):
        p, method = 1.0, "all differences are zero"
    elif n <= EXACT_SIGN_LIMIT:
        count = sum(1 for signs in product((1, -1), repeat=n) if abs(sum(sg * x for sg, x in zip(signs, d, strict=True))) >= obs - 1e-12)
        p, method = count / 2**n, "exact sign-flip"
    else:
        rng = random.Random(seed)
        count = 1
        for _ in range(MONTE_CARLO_DRAWS):
            if abs(sum(x if rng.random() < 0.5 else -x for x in d)) >= obs - 1e-12:
                count += 1
        p, method = count / (MONTE_CARLO_DRAWS + 1), f"monte-carlo sign-flip ({MONTE_CARLO_DRAWS} draws)"
    rng = random.Random(seed)
    boots = sorted(statistics.mean(rng.choices(d, k=n)) for _ in range(2000))
    return {
        "n_pairs": n,
        "mean_difference": round(mean_d, 4),
        "sd_difference": round(sd_d, 4),
        "effect_size_dz": round(mean_d / sd_d, 3) if sd_d > 1e-12 else None,  # None: every seed gave the same difference
        "same_sign": sum(1 for x in d if x > 1e-12) if mean_d >= 0 else sum(1 for x in d if x < -1e-12),
        "bootstrap_95ci": (round(boots[50], 3), round(boots[1949], 3)),
        "p": round(p, 5),
        "method": method,
        "min_p": round(2 / 2**n, 5) if n <= EXACT_SIGN_LIMIT else round(1 / (MONTE_CARLO_DRAWS + 1), 5),
    }


def _holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjustment over a family of p-values."""

    order = sorted(pvals, key=lambda k: pvals[k])
    m, running, out = len(order), 0.0, {}
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvals[k]))
        out[k] = round(running, 5)
    return out


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
                    "ci95": _bootstrap_mean(vals),
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
                ra = {r.get("seed", ("row", i)): r[k] for i, r in enumerate(rows) if r["condition"] == a and _numeric(r.get(k))}
                rb = {r.get("seed", ("row", i)): r[k] for i, r in enumerate(rows) if r["condition"] == b and _numeric(r.get(k))}
                va, vb = list(ra.values()), list(rb.values())
                name = k if len(conds) == 2 else f"{k} ({a} vs {b})"
                unpaired = _permutation_test(va, vb)
                no_spread = len(va) > 1 and len(vb) > 1 and statistics.pstdev(va) <= 1e-12 and statistics.pstdev(vb) <= 1e-12
                out["comparisons"][name] = {
                    "outcome": k,
                    "difference": f"{a} - {b}",
                    "mean_difference": round(statistics.mean(va) - statistics.mean(vb), 3) if va and vb else None,
                    "bootstrap_95ci": _bootstrap_diff(va, vb),
                    "permutation_p": unpaired["p"] if unpaired else None,
                    "permutation_method": unpaired["method"] if unpaired else None,
                    "permutation_min_p": unpaired["min_p"] if unpaired else None,
                    "paired": _paired_test(ra, rb),
                    "n": [len(va), len(vb)],
                    # Seeds that produce the same value in both conditions are copies, not
                    # replicates: the p-value then reflects determinism, not sampling.
                    "no_between_seed_variation": no_spread,
                    "note": "exploratory; run-level; not powered",
                }
        family = {name: c["paired"]["p"] for name, c in out["comparisons"].items() if c.get("paired")}
        for name, adj in _holm(family).items():
            out["comparisons"][name]["paired"]["p_holm"] = adj
        out["comparison_family"] = {"size": len(family), "adjustment": "Holm over the paired p-values of all primary comparisons"}
    if protocol.contrasts:
        out["contrasts"] = planned_contrasts(rows, protocol)
    return out


def planned_contrasts(rows: list[dict[str, Any]], protocol: Protocol) -> list[dict[str, Any]]:
    """The protocol's registered contrasts: paired by seed, Holm-adjusted within this family only.

    ``expect`` is what the hypothesis predicts for ``a - b``: ``>`` or ``<`` (beyond
    ``tolerance``), ``>=`` or ``<=`` (not worse than ``tolerance`` the other way), or ``=``
    (within ``tolerance``, an equivalence band on the mean difference). ``supported`` says
    whether the observed mean difference fits; it is a descriptive verdict, with the test
    result next to it. ``outcome_b`` lets a contrast compare two outcomes, for example a
    probe variant with the paper weights on the same snapshots.
    """

    out = []
    for c in protocol.contrasts:
        k, a, b = c["outcome"], c["a"], c["b"]
        kb = c.get("outcome_b", k)
        ra = {r.get("seed", ("row", i)): r[k] for i, r in enumerate(rows) if r["condition"] == a and _numeric(r.get(k))}
        rb = {r.get("seed", ("row", i)): r[kb] for i, r in enumerate(rows) if r["condition"] == b and _numeric(r.get(kb))}
        paired = _paired_test(ra, rb)
        va, vb = list(ra.values()), list(rb.values())
        diff = round(statistics.mean(va) - statistics.mean(vb), 4) if va and vb else None
        expect = str(c.get("expect", ">"))
        tol = float(c.get("tolerance", 0.0))
        if diff is None:
            supported = None
        elif expect == ">":
            supported = diff > tol
        elif expect == "<":
            supported = diff < -tol
        elif expect == ">=":
            supported = diff >= -tol
        elif expect == "<=":
            supported = diff <= tol
        else:
            supported = abs(diff) <= tol
        out.append(
            {
                "label": c.get("label") or (f"{k}: {a} {expect} {b}" if kb == k else f"{a}: {k} {expect} {kb}" if a == b else f"{k} ({a}) {expect} {kb} ({b})"),
                "outcome": k,
                "outcome_b": kb,
                "a": a,
                "b": b,
                "expect": expect,
                "tolerance": tol,
                "mean_a": round(statistics.mean(va), 4) if va else None,
                "mean_b": round(statistics.mean(vb), 4) if vb else None,
                "mean_difference": diff,
                "supported": supported,
                "paired": paired,
                "n": [len(va), len(vb)],
            }
        )
    family = {str(i): c["paired"]["p"] for i, c in enumerate(out) if c.get("paired")}
    for i, adj in _holm(family).items():
        out[int(i)]["paired"]["p_holm"] = adj
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
    "memory_recall_at_30": "Planted-fact recall@30 (paper cap)",
    "memory_recall_lexical": "Recall@k, queries sharing words with the fact",
    "memory_recall_paraphrase": "Recall@k, paraphrase queries (no shared content words)",
    "memory_recall_lexical_at_30": "Recall@30, lexical queries",
    "memory_recall_paraphrase_at_30": "Recall@30, paraphrase queries",
    "memory_recall_old_at_30": "Recall@30 of facts older than a day",
    "memory_median_rank": "Median rank of the planted fact",
    "memory_rank_percentile": "Mean rank percentile (0 = top)",
    "memory_stream_size": "Memories per agent at the probe",
    "network_weighted_density": "Weighted density (mean mutual familiarity over all pairs)",
    "network_conversation_density": "Pairs who talked (share of all pairs)",
    "network_degree_gini": "Degree inequality (Gini)",
    "network_density_t20": "Density at tie threshold 0.20",
    "network_density_t35": "Density at tie threshold 0.35",
    "network_density_t50": "Density at tie threshold 0.50",
    "network_density_t75": "Density at tie threshold 0.75",
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
    "adaptation_perceivers": "Agents who perceived the event",
    "adaptation_perceivers_at_onset": "Agents who perceived the event in its first minute",
    "adaptation_median_reaction_after_perceiving_min": "Median reaction time after first perceiving it (min)",
}


def _num(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


def _cell(stats: dict[str, Any], key: str) -> str:
    if not stats.get("n"):
        return "unpriced" if key == "cost_usd" else "n/a"
    sd = f" ± {_num(stats['sd'])}" if stats.get("sd") is not None else ""
    ci = f"; 95% CI {_num(stats['ci95'][0])} to {_num(stats['ci95'][1])}" if stats.get("ci95") else ""
    return f"{_num(stats['mean'])}{sd} (median {_num(stats['median'])}; {_num(stats['min'])}–{_num(stats['max'])}{ci}; n={stats['n']})"


def _label(k: str) -> str:
    return LABELS.get(k, k.replace("_", " "))


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(protocol: Protocol, rows: list[dict[str, Any]], summary: dict[str, Any], detail: list[str] | None = None) -> str:
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
        snap = protocol.fork_from.get("snapshot", "final")
        if protocol.per_seed_sources():
            lines += [
                "",
                f"Every run is a fork of `{protocol.fork_from['run_dir']}` at snapshot `{snap}`: each seed has its own recorded past, "
                "and the conditions of one seed share that past and differ only after the fork point.",
            ]
        else:
            lines += ["", f"Every run is a fork of `{protocol.fork_from['run_dir']}` at snapshot `{snap}`: the same past, different futures."]
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
    lines += [
        "",
        "Mean ± SD (median; range; bootstrap 95% interval of the mean from three runs up; runs with a value). Primary outcomes, fixed in the protocol before running, are in bold.",
    ]
    if summary.get("contrasts"):
        lines += [
            "",
            "## Planned contrasts (registered with the hypothesis)",
            "",
            "| Contrast | Mean a | Mean b | a − b | Direction as predicted | Seeds agreeing | d_z | Paired p | Holm p |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for c in summary["contrasts"]:
            pr = c.get("paired") or {}
            verdict = "n/a" if c["supported"] is None else ("yes" if c["supported"] else "**no**")
            band = f" (within ±{c['tolerance']:g})" if c["expect"] == "=" else f" (margin {c['tolerance']:g})" if c["tolerance"] else ""
            # for an expected equality "seeds agreeing" has no meaning: there is no direction to agree with
            agree = f"{pr['same_sign']} of {pr['n_pairs']}" if pr and c["expect"] != "=" else "n/a"
            dz = "n/a" if not pr else ("same on every seed" if pr["effect_size_dz"] is None else _fmt(pr["effect_size_dz"]))
            lines.append(
                f"| {c['label']}{band} | {_fmt(c['mean_a'])} | {_fmt(c['mean_b'])} | {_fmt(c['mean_difference'])} | {verdict} | {agree} | {dz} | "
                f"{_fmt(pr.get('p'))} | {_fmt(pr.get('p_holm'))} |"
            )
        floor = min((c["paired"]["min_p"] for c in summary["contrasts"] if c.get("paired")), default=None)
        lines += [
            "",
            f"Paired by seed (exact sign-flip permutation; smallest possible p = {_fmt(floor)}), Holm-adjusted over these {len(summary['contrasts'])} contrasts only. "
            '"Direction as predicted" compares the observed mean difference with the registered expectation; for an expected equality it checks the stated band.',
        ]
    lines += ["", "## Comparisons (exploratory)", ""]
    for k, v in summary.get("comparisons", {}).items():
        line = (
            f"* **{k}**: {v['difference']} = {v['mean_difference']} (bootstrap 95% CI {v['bootstrap_95ci']}, "
            f"{v.get('permutation_method') or 'exact'} permutation p = {v['permutation_p']}"
            + (f", smallest possible {v['permutation_min_p']}" if v.get("permutation_min_p") is not None else "")
            + f", n = {v['n']})"
        )
        pr = v.get("paired")
        if pr:
            dz = "undefined (identical difference on every seed)" if pr["effect_size_dz"] is None else pr["effect_size_dz"]
            line += (
                f"; paired by seed: mean difference {pr['mean_difference']} over {pr['n_pairs']} seeds "
                f"({pr['same_sign']} in the direction of the mean), d_z = {dz}, {pr['method']} p = {pr['p']} "
                f"(smallest possible {pr['min_p']}; Holm-adjusted {pr.get('p_holm')})"
            )
        if v.get("no_between_seed_variation"):
            line += ". **No between-seed variation in either condition: the seeds are copies here, so these p-values describe determinism, not sampling.**"
        lines.append(line)
    if summary.get("comparison_family"):
        fam = summary["comparison_family"]
        lines += [
            "",
            f"Paired p-values are Holm-adjusted over the {fam['size']} primary comparisons of this protocol. All tests are two-sided and descriptive.",
        ]
    if not summary.get("comparisons"):
        lines.append("* none (one condition, or more than six)")
    plots = [k for k in prim if (protocol.root() / f"outcome_{k}.svg").exists()]
    if plots:
        lines += ["", "One dot per run; the bar is the condition mean.", ""] + [f"![{_label(k)}](outcome_{k}.svg)" for k in plots]
    if detail:
        lines += detail
    if summary.get("excluded"):
        lines += ["", "## Runs without outcomes", ""] + [f"* {e['run_id']}: {e['status']} — {e['reason']}" for e in summary["excluded"]]
    if summary.get("metric_failures"):
        lines += ["", "## Metric failures", ""] + [f"* {rid}: {'; '.join(f)}" for rid, f in summary["metric_failures"].items()]
    lines += ["", "_Run modes: " + ", ".join(f"{m} × {n}" for m, n in sorted(modes.items())) + "._", ""]
    lines += ["Simulated characters: plausible behavior here does not establish validity for real people.", ""]
    return "\n".join(lines)
