"""Cross-run detail for experiment reports: what the run-level means cannot show.

A run-level table says that recall differed between conditions; it does not say *where*.
These helpers pool the per-run metric files (``<run>/exports/metrics/*.json``) of an
experiment by condition and return Markdown sections and SVG charts for the report:

* **memory_probe**: recall@30 by fact age, by importance and by query style for every
  condition; the recall curve; and, for the first condition, the same facts in the same
  snapshots re-scored under each probe variant (an exact comparison of scoring rules);
* **network**: the thresholded density at every swept threshold, the threshold-free
  measures, and the growth of the configured-threshold density over simulated time;
* **adaptation**: per-run perceivers, changers and latencies.

Everything here is a pure function of files the metrics already wrote. Nothing is
recomputed from the simulation and no model is called.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .plots import line_chart


def _load(row: dict[str, Any], metric: str) -> dict[str, Any] | None:
    path = Path(str(row.get("run_dir", ""))) / "exports" / "metrics" / f"{metric}.json"
    if row.get("status") != "completed" or not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _f(v: float | None, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head), *["| " + " | ".join(r) + " |" for r in rows]]


def _recall(rows: list[dict[str, Any]], cutoff: int) -> float | None:
    return sum(1 for r in rows if r["rank"] and r["rank"] <= cutoff) / len(rows) if rows else None


def _median_rank(rows: list[dict[str, Any]]) -> float | None:
    return statistics.median((r["rank"] or r["candidates"] + 1) for r in rows) if rows else None


# ------------------------------------------------------------------------- memory probe
def memory_detail(rows: list[dict[str, Any]], conditions: list[str]) -> dict[str, Any] | None:
    """Pool every planted-fact row of every run by condition (and by probe variant)."""

    pooled: dict[str, list[dict[str, Any]]] = defaultdict(list)
    variants: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    runs: dict[str, int] = defaultdict(int)
    embedding: dict[str, str] = {}
    for row in rows:
        d = _load(row, "memory_probe")
        if not d:
            continue
        c = row["condition"]
        runs[c] += 1
        planted = d["planted"]
        embedding[c] = planted.get("embedding_model", "?")
        pooled[c] += planted["rows"]
        for name, v in (planted.get("variants") or {}).items():
            variants[c][name] += v["rows"]
    if not pooled:
        return None
    conds = [c for c in conditions if c in pooled]
    ages = sorted({r["age_hours"] for rs in pooled.values() for r in rs})
    styles = sorted({r.get("style", "lexical") for rs in pooled.values() for r in rs})

    def cell(rs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"n": len(rs), "recall_at_10": _recall(rs, 10), "recall_at_30": _recall(rs, 30), "median_rank": _median_rank(rs)}

    out: dict[str, Any] = {"conditions": conds, "ages": ages, "styles": styles, "runs": dict(runs), "embedding": embedding, "by_condition": {}, "variants": {}}
    for c in conds:
        rs = pooled[c]
        normalized = [r["normalized"]["recency"] for r in rs if r.get("normalized")]
        out["by_condition"][c] = {
            "all": cell(rs),
            "by_age": {f"{a:g}": cell([r for r in rs if r["age_hours"] == a]) for a in ages},
            "recency_by_age": {
                f"{a:g}": (statistics.mean(x) if (x := [r["normalized"]["recency"] for r in rs if r["age_hours"] == a and r.get("normalized")]) else None)
                for a in ages
            },
            "by_style": {s: cell([r for r in rs if r.get("style", "lexical") == s]) for s in styles},
            "by_importance": {str(i): cell([r for r in rs if r["importance"] == i]) for i in sorted({r["importance"] for r in rs})},
            "by_style_and_age": {s: {f"{a:g}": cell([r for r in rs if r.get("style", "lexical") == s and r["age_hours"] == a]) for a in ages} for s in styles},
            "curve": {str(k): _recall(rs, k) for k in (1, 3, 5, 10, 20, 30, 50, 100)},
            "forgotten": sum(1 for r in rs if r.get("excluded_as_forgotten")),
            "mean_candidates": statistics.mean(r["candidates"] for r in rs),
            "mean_normalized_recency": statistics.mean(normalized) if normalized else None,
        }
        out["variants"][c] = {
            name: {
                "all": cell(vr),
                "by_age": {f"{a:g}": cell([r for r in vr if r["age_hours"] == a]) for a in ages},
                "by_style": {s: cell([r for r in vr if r.get("style", "lexical") == s]) for s in styles},
                "forgotten": sum(1 for r in vr if r.get("excluded_as_forgotten")),
                "forgotten_facts": sorted({r["fact"] for r in vr if r.get("excluded_as_forgotten")}),
            }
            for name, vr in variants[c].items()
        }
    return out


def memory_sections(detail: dict[str, Any], root: Path) -> list[str]:
    conds, ages = detail["conditions"], [f"{a:g}" for a in detail["ages"]]
    by = detail["by_condition"]
    lines = ["", "## Detail: planted-fact retrieval", ""]
    lines.append(
        "Pooled over every run, agent, fact and query of a condition (the unit here is the query, so these tables describe; the run-level tables above test). "
        "Embedding model per condition: " + "; ".join(f"`{c}` {detail['embedding'].get(c, '?')}" for c in conds) + "."
    )
    lines += ["", "**Recall@30 by fact age (hours before the probe), paper weights**", ""]
    lines += _table(
        ["Condition", *[f"{a} h" for a in ages], "All"],
        [[c, *[_f(by[c]["by_age"][a]["recall_at_30"]) for a in ages], _f(by[c]["all"]["recall_at_30"])] for c in conds],
    )
    lines += [
        "",
        "**Median rank of the planted fact by age** (lower is better; candidates per query: "
        + ", ".join(f"`{c}` {by[c]['mean_candidates']:.0f}" for c in conds)
        + ")",
        "",
    ]
    lines += _table(["Condition", *[f"{a} h" for a in ages]], [[c, *[_f(by[c]["by_age"][a]["median_rank"], 0) for a in ages]] for c in conds])
    lines += [
        "",
        "**Mean normalized recency of the planted fact by age** (the recency term after min-max normalization; 1 = most recent memory in the stream)",
        "",
    ]
    lines += _table(["Condition", *[f"{a} h" for a in ages]], [[c, *[_f(by[c]["recency_by_age"][a]) for a in ages]] for c in conds])
    lines += ["", "**By query style** (recall@10 / recall@30 / median rank)", ""]
    lines += _table(
        ["Condition", *detail["styles"]],
        [
            [
                c,
                *[
                    f"{_f(by[c]['by_style'][s]['recall_at_10'])} / {_f(by[c]['by_style'][s]['recall_at_30'])} / {_f(by[c]['by_style'][s]['median_rank'], 0)}"
                    for s in detail["styles"]
                ],
            ]
            for c in conds
        ],
    )
    imps = sorted({i for c in conds for i in by[c]["by_importance"]}, key=int)
    lines += ["", "**Recall@30 by importance of the fact**", ""]
    lines += _table(
        ["Condition", *[f"importance {i}" for i in imps]], [[c, *[_f(by[c]["by_importance"].get(i, {}).get("recall_at_30")) for i in imps]] for c in conds]
    )
    ks = list(next(iter(by.values()))["curve"])
    lines += ["", "**Recall curve** (share of planted facts ranked at or above k)", ""]
    lines += _table(["Condition", *[f"k = {k}" for k in ks]], [[c, *[_f(by[c]["curve"][k]) for k in ks]] for c in conds])
    (root / "detail_recall_by_age.svg").write_text(
        line_chart(
            "Recall@30 by fact age, paper weights",
            ages,
            {c: [by[c]["by_age"][a]["recall_at_30"] for a in ages] for c in conds},
            x_title="age of the planted fact (hours)",
        )
    )
    lines += ["", "![Recall@30 by fact age](detail_recall_by_age.svg)"]
    ref = next((c for c in conds if detail["variants"].get(c)), None)
    if ref:
        var = detail["variants"][ref]
        lines += [
            "",
            f"**Scoring variants on the snapshots of `{ref}`** (the same planted facts in the same streams, re-scored; recall@30 by age, then by query style)",
            "",
        ]
        table = [
            [
                "paper weights",
                *[_f(by[ref]["by_age"][a]["recall_at_30"]) for a in ages],
                _f(by[ref]["all"]["recall_at_30"]),
                *[_f(by[ref]["by_style"][s]["recall_at_30"]) for s in detail["styles"]],
                "0",
            ]
        ]
        for name, v in var.items():
            table.append(
                [
                    name,
                    *[_f(v["by_age"][a]["recall_at_30"]) for a in ages],
                    _f(v["all"]["recall_at_30"]),
                    *[_f(v["by_style"][s]["recall_at_30"]) for s in detail["styles"]],
                    str(v["forgotten"]),
                ]
            )
        lines += _table(["Scoring", *[f"{a} h" for a in ages], "All", *detail["styles"], "Queries excluded as forgotten"], table)
        forgot = {name: v["forgotten_facts"] for name, v in var.items() if v["forgotten_facts"]}
        for name, facts in forgot.items():
            lines += ["", f"Facts made inaccessible under `{name}`: {', '.join(facts)}."]
        chart = {
            "paper weights": [by[ref]["by_age"][a]["recall_at_30"] for a in ages],
            **{name: [v["by_age"][a]["recall_at_30"] for a in ages] for name, v in var.items()},
        }
        (root / "detail_variants_by_age.svg").write_text(
            line_chart(f"Recall@30 by fact age under scoring variants ({ref})", ages, chart, x_title="age of the planted fact (hours)", height=300)
        )
        lines += ["", "![Recall@30 by age under scoring variants](detail_variants_by_age.svg)"]
    return lines


# ------------------------------------------------------------------------- network
def network_detail(rows: list[dict[str, Any]], conditions: list[str]) -> dict[str, Any] | None:
    sweeps: dict[str, dict[float, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    finals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    series: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        d = _load(row, "network")
        if not d:
            continue
        c = row["condition"]
        finals[c].append(d["final"])
        series[c].append(d.get("series") or [])
        for s in d.get("threshold_sweep") or []:
            sweeps[c][float(s["threshold"])].append(s)
    if not finals:
        return None
    conds = [c for c in conditions if c in finals]
    thresholds = sorted({t for c in conds for t in sweeps[c]})

    def mean(vals: list[Any]) -> float | None:
        vals = [v for v in vals if isinstance(v, int | float)]
        return statistics.mean(vals) if vals else None

    out: dict[str, Any] = {"conditions": conds, "thresholds": thresholds, "by_condition": {}}
    for c in conds:
        length = min((len(s) for s in series[c]), default=0)
        out["by_condition"][c] = {
            "runs": len(finals[c]),
            "sweep": {
                f"{t:g}": {
                    k: mean([s[k] for s in sweeps[c][t]]) for k in ("density", "components", "largest_component", "isolates", "clustering", "mean_degree")
                }
                for t in thresholds
            },
            "final": {
                k: mean([f.get(k) for f in finals[c]])
                for k in ("weighted_density", "conversation_density", "degree_gini", "mean_familiarity", "reciprocity", "records", "n")
            },
            "series": [
                {
                    "sim_time": series[c][0][i]["sim_time"],
                    "density": mean([s[i]["density"] for s in series[c]]),
                    "mean_familiarity": mean([s[i]["mean_familiarity"] for s in series[c]]),
                    "largest_component": mean([s[i]["largest_component"] for s in series[c]]),
                }
                for i in range(length)
            ],
        }
    return out


def network_sections(detail: dict[str, Any], root: Path) -> list[str]:
    conds, by = detail["conditions"], detail["by_condition"]
    ts = [f"{t:g}" for t in detail["thresholds"]]
    lines = ["", "## Detail: the network at every threshold", "", "Means over the runs of a condition. A tie is mutual familiarity at or above the threshold."]
    if ts:
        lines += ["", "**Density by tie threshold**", ""]
        lines += _table(["Condition", *[f"≥ {t}" for t in ts]], [[c, *[_f(by[c]["sweep"][t]["density"], 3) for t in ts]] for c in conds])
        lines += ["", "**Largest component (agents) and number of components by tie threshold**", ""]
        lines += _table(
            ["Condition", *[f"≥ {t}" for t in ts]],
            [[c, *[f"{_f(by[c]['sweep'][t]['largest_component'], 1)} / {_f(by[c]['sweep'][t]['components'], 1)}" for t in ts]] for c in conds],
        )
        (root / "detail_density_by_threshold.svg").write_text(
            line_chart(
                "Network density by tie threshold",
                ts,
                {c: [by[c]["sweep"][t]["density"] for t in ts] for c in conds},
                x_title="tie threshold (mutual familiarity)",
            )
        )
        lines += ["", "![Density by tie threshold](detail_density_by_threshold.svg)"]
    lines += ["", "**Measures without a threshold**", ""]
    lines += _table(
        ["Condition", "Weighted density", "Pairs who talked", "Mean familiarity (records)", "Degree Gini at the configured threshold", "Relationship records"],
        [
            [
                c,
                _f(by[c]["final"]["weighted_density"], 3),
                _f(by[c]["final"]["conversation_density"], 3),
                _f(by[c]["final"]["mean_familiarity"], 3),
                _f(by[c]["final"]["degree_gini"], 3),
                _f(by[c]["final"]["records"], 0),
            ]
            for c in conds
        ],
    )
    longest = max((by[c]["series"] for c in conds), key=len, default=[])
    if len(longest) > 2:
        # at most nine evenly spaced labels, always including the last hour
        idx = sorted({round(i * (len(longest) - 1) / 8) for i in range(9)})
        labels = [longest[i]["sim_time"][5:13].replace("T", " ") + "h" for i in idx]
        lines += ["", "**Density at the configured threshold over simulated time**", ""]
        lines += _table(
            ["Condition", *labels], [[c, *[_f(by[c]["series"][i]["density"], 3) if i < len(by[c]["series"]) else "n/a" for i in idx]] for c in conds]
        )
        (root / "detail_density_over_time.svg").write_text(
            line_chart(
                "Network density over simulated time",
                labels,
                {c: [by[c]["series"][i]["density"] if i < len(by[c]["series"]) else None for i in idx] for c in conds},
                x_title="simulated time (month-day hour)",
                width=680,
            )
        )
        lines += ["", "![Density over time](detail_density_over_time.svg)"]
    return lines


# ------------------------------------------------------------------------- adaptation
def adaptation_sections(rows: list[dict[str, Any]], conditions: list[str]) -> list[str]:
    table = []
    for row in rows:
        d = _load(row, "adaptation")
        if not d:
            continue
        lat = sorted(a["latency_minutes"] for a in d["agents"].values() if a["latency_minutes"] is not None)
        first = d.get("first_mention") or {}
        table.append(
            [
                row["run_id"],
                str(len(d["perceived"])),
                ", ".join(a.split("_")[0] for a in d["perceived"]) or "none",
                str(len(d["changed_plans"])),
                ", ".join(f"{x:g}" for x in lat) or "n/a",
                str(d["mentions_in_conversation"]),
                (first.get("text") or "")[:90].replace("|", "/"),
            ]
        )
    if not table:
        return []
    lines = ["", "## Detail: who perceived the event and who changed course", ""]
    lines += _table(["Run", "Perceivers", "Who", "Changed plans", "Latencies (min)", "Conversations mentioning it", "First mention"], table)
    return lines


def detail_sections(rows: list[dict[str, Any]], conditions: list[str], metrics: list[str], root: Path) -> tuple[list[str], dict[str, Any]]:
    """Markdown lines to append to an experiment report, and the pooled data behind them."""

    lines: list[str] = []
    data: dict[str, Any] = {}
    if "memory_probe" in metrics and (m := memory_detail(rows, conditions)):
        data["memory_probe"] = m
        lines += memory_sections(m, root)
    if "network" in metrics and (n := network_detail(rows, conditions)):
        data["network"] = n
        lines += network_sections(n, root)
    if "adaptation" in metrics:
        lines += adaptation_sections(rows, conditions)
    return lines, data
