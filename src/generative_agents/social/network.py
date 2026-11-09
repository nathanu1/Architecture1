"""Social network measures over relationship records (research extension; no dependencies).

A *tie* from A to B exists when A's familiarity with B is at least ``tie_threshold``. The
undirected network keeps a pair when **both** directions are ties (mutual), which is the
convention the paper's relationship-density measure uses as well (§7.1.1: both agents
affirm knowing each other). Directed ties are kept for reciprocity.

Measures: density ``2|E| / (n(n-1))``, mean degree, degree distribution, reciprocity
(share of directed ties that are returned), average local clustering coefficient, connected
components (count and largest), and the mean familiarity and valence over directed ties.
``reconstruct`` rebuilds every record as it stood at a simulated time from the append-only
``relationship_events`` log, so a time series needs no extra bookkeeping during the run.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Any

from ..db import Database


def ties(states: list[dict[str, Any]], threshold: float) -> dict[tuple[str, str], dict[str, Any]]:
    """Directed ties ``(a, b) -> state`` with familiarity at or above the threshold."""

    return {(s["agent_id"], s["other_id"]): s for s in states if s.get("familiarity", 0.0) >= threshold}


def mutual_edges(directed: dict[tuple[str, str], Any]) -> list[tuple[str, str]]:
    out = []
    for a, b in directed:
        if a < b and (b, a) in directed:
            out.append((a, b))
    return sorted(out)


def components(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen: set[str] = set()
    out: list[list[str]] = []
    for n in sorted(adj):
        if n in seen:
            continue
        stack, comp = [n], []
        seen.add(n)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        out.append(sorted(comp))
    return sorted(out, key=lambda c: (-len(c), c))


def clustering(nodes: list[str], edges: list[tuple[str, str]]) -> float | None:
    """Average local clustering coefficient over nodes with degree >= 2 (None when there are none)."""

    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    coeffs = []
    for n in nodes:
        nb = adj[n]
        k = len(nb)
        if k < 2:
            continue
        links = sum(1 for x, y in combinations(sorted(nb), 2) if y in adj[x])
        coeffs.append(2 * links / (k * (k - 1)))
    return round(sum(coeffs) / len(coeffs), 4) if coeffs else None


def measures(nodes: list[str], states: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    n = len(nodes)
    directed = ties(states, threshold)
    edges = mutual_edges(directed)
    degree = defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    comps = components(nodes, edges)
    reciprocated = sum(1 for (a, b) in directed if (b, a) in directed)
    fam = [s["familiarity"] for s in states if s.get("conversations", 0) or s.get("presence", 0)]
    val = [s["valence"] for s in states if s.get("appraisals", 0)]
    return {
        "n": n,
        "threshold": threshold,
        "directed_ties": len(directed),
        "edges": [list(e) for e in edges],
        "edge_count": len(edges),
        "density": round(2 * len(edges) / (n * (n - 1)), 4) if n >= 2 else None,
        "mean_degree": round(sum(degree.values()) / n, 3) if n else None,
        "degree": {a: degree.get(a, 0) for a in nodes},
        "isolates": sum(1 for a in nodes if degree.get(a, 0) == 0),
        "reciprocity": round(reciprocated / len(directed), 4) if directed else None,
        "clustering": clustering(nodes, edges),
        "components": len(comps),
        "largest_component": len(comps[0]) if comps else 0,
        "mean_familiarity": round(sum(fam) / len(fam), 4) if fam else None,
        "mean_valence": round(sum(val) / len(val), 4) if val else None,
        "records": len(states),
    }


def current_states(db: Database) -> list[dict[str, Any]]:
    try:
        return [json.loads(r["json"]) for r in db.query("SELECT json FROM relationships ORDER BY agent_id, other_id")]
    except Exception:  # an older run without the table
        return []


def reconstruct(db: Database, at: datetime | None = None) -> list[dict[str, Any]]:
    """Every record as it stood at ``at`` (inclusive), replayed from ``relationship_events``."""

    sql = "SELECT sim_time, agent_id, other_id, kind, json FROM relationship_events"
    params: tuple = ()
    if at is not None:
        sql += " WHERE sim_time <= ?"
        params = (at.isoformat(),)
    sql += " ORDER BY id"
    try:
        rows = db.query(sql, params)
    except Exception:
        return []
    states: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        d = json.loads(r["json"])
        key = (r["agent_id"], r["other_id"])
        st = states.setdefault(
            key, {"agent_id": key[0], "other_id": key[1], "familiarity": 0.0, "valence": 0.0, "conversations": 0, "presence": 0, "appraisals": 0}
        )
        st["familiarity"] = d["after"]["familiarity"]
        st["valence"] = d["after"]["valence"]
        if r["kind"] == "conversation":
            st["conversations"] += 1
            if d.get("appraisal") is not None:
                st["appraisals"] += 1
        elif r["kind"] == "presence":
            st["presence"] += 1
        st["last_interaction_at"] = r["sim_time"]
    return [states[k] for k in sorted(states)]


def time_series(db: Database, nodes: list[str], times: list[datetime], threshold: float) -> list[dict[str, Any]]:
    out = []
    for t in times:
        m = measures(nodes, reconstruct(db, t), threshold)
        out.append(
            {
                "sim_time": t.isoformat(),
                **{
                    k: m[k]
                    for k in (
                        "edge_count",
                        "density",
                        "mean_degree",
                        "reciprocity",
                        "clustering",
                        "components",
                        "largest_component",
                        "isolates",
                        "mean_familiarity",
                        "mean_valence",
                    )
                },
            }
        )
    return out


def event_rows(db: Database, limit: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT id, step, sim_time, agent_id, other_id, kind, json FROM relationship_events ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        return [
            {
                "id": r["id"],
                "step": r["step"],
                "sim_time": r["sim_time"],
                "agent_id": r["agent_id"],
                "other_id": r["other_id"],
                "kind": r["kind"],
                **json.loads(r["json"]),
            }
            for r in db.query(sql)
        ]
    except Exception:
        return []
