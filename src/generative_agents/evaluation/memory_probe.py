"""Retrieval accuracy probes (research extension): does the memory mechanism bring back what it should?

Two probes, both deterministic given the embeddings and both run on an in-memory clone of a
snapshot, so the run is never touched:

1. **Planted facts.** Synthetic statements (``configs/probes/memory_facts.yaml``) are inserted
   into each agent's clone at chosen ages and importance levels; each fact comes with a
   paraphrased query. The probe reports recall@k by age bucket and by importance, where a
   hit means the planted memory is among the delivered memories for its query. This
   isolates the retrieval mechanism (weights, decay, forgetting) from the model.
2. **Own experiences.** For every conversation the agent took part in, the conversation's
   summary (or its first utterance) is used as a query; a hit means at least one memory of
   that conversation is delivered. This measures how retrievable an agent's own past
   interactions are at the end of the run.

With the hash-embedding fixture, "relevance" is lexical overlap, so paraphrases that share
few words will miss; with model embeddings the probe measures semantic retrieval. The report
names the embedding model for that reason.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..config import GAConfig, repo_path
from ..db import Database, parse_iso
from ..memory.retrieval import RetrievalSettings, Retriever
from ..memory.store import MemoryStore
from ..providers.embeddings import EmbeddingService, build_embedding_provider
from ..schemas import AgentIdentity, MemoryKind, MemoryOrigin

DEFAULT_FACTS = "configs/probes/memory_facts.yaml"


def load_facts(path: str | Path | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path and Path(path).exists() else repo_path(path or DEFAULT_FACTS)
    data = yaml.safe_load(p.read_text()) or {}
    return list(data.get("facts", []))


def _open_clone(snapshot: Path) -> Database:
    src = Database(snapshot, read_only=True)
    try:
        return src.clone()
    finally:
        src.close()


def _embeddings(cfg: GAConfig, store: MemoryStore, embedding_provider: Any) -> EmbeddingService:
    prov = embedding_provider or build_embedding_provider(cfg.providers.embeddings)
    return EmbeddingService(prov, store=store, cache=None)


def planted_facts(
    cfg: GAConfig,
    snapshot: Path,
    agents: list[str],
    *,
    facts: list[dict[str, Any]] | None = None,
    k: int = 10,
    embedding_provider: Any = None,
    settings: RetrievalSettings | None = None,
) -> dict[str, Any]:
    facts = facts if facts is not None else load_facts()
    db = _open_clone(snapshot)
    try:
        now = parse_iso(db.get_meta("sim_time")) or datetime.now()
        store = MemoryStore(db)
        emb = _embeddings(cfg, store, embedding_provider)
        retriever = Retriever(store, emb, settings or RetrievalSettings.from_config(cfg.retrieval))
        identities = {r["id"]: AgentIdentity.model_validate_json(r["identity_json"]) for r in db.query("SELECT id, identity_json FROM agents")}
        rows = []
        for aid in agents:
            if aid not in identities:
                continue
            name = identities[aid].name
            planted = []
            for f in facts:
                text = f["statement"].replace("{name}", name)
                created = now - timedelta(hours=float(f.get("age_hours", 1)))
                mem = store.add(
                    owner_id=aid,
                    kind=MemoryKind.OBSERVATION,
                    origin=MemoryOrigin.DIRECT_OBSERVATION,
                    description=text,
                    created_at=created,
                    importance=int(f.get("importance", 5)),
                    embedding_model=emb.model_key,
                    vector=emb.embed_one(text),
                    metadata={"probe": True, "fact": f["id"]},
                )
                planted.append((f, mem))
            for f, mem in planted:
                query = f["query"].replace("{name}", name)
                res = retriever.retrieve(aid, query, now, max_items=k, budget_tokens=None, commit_access=False)
                ranked = [c.memory.id for c in res.candidates]
                rank = ranked.index(mem.id) + 1 if mem.id in ranked else None
                rows.append(
                    {
                        "agent_id": aid,
                        "fact": f["id"],
                        "age_hours": float(f.get("age_hours", 1)),
                        "importance": int(f.get("importance", 5)),
                        "hit": mem.id in {m.id for m in res.delivered},
                        "rank": rank,
                        "candidates": len(res.candidates),
                        "excluded_as_forgotten": any(e["id"] == mem.id and e["reason"].startswith("forgotten") for e in res.excluded),
                    }
                )
        return {
            "k": k,
            "rows": rows,
            "summary": summarize_planted(rows),
            "embedding_model": emb.model_key,
            "snapshot": str(snapshot),
            "reference_time": now.isoformat(),
        }
    finally:
        db.close()


def summarize_planted(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    by_age: dict[str, list[bool]] = defaultdict(list)
    by_imp: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        age = r["age_hours"]
        bucket = "<=1h" if age <= 1 else "<=6h" if age <= 6 else "<=24h" if age <= 24 else ">24h"
        by_age[bucket].append(r["hit"])
        by_imp["high" if r["importance"] >= 7 else "mid" if r["importance"] >= 4 else "low"].append(r["hit"])
    ranks = [r["rank"] for r in rows if r["rank"]]
    return {
        "n": len(rows),
        "recall_at_k": round(sum(r["hit"] for r in rows) / len(rows), 4),
        # the paper's retrieval cap (30 items); computed from the full ranking, so it never
        # depends on the probe's k and shows how far below the cutoff old facts sit
        "recall_at_30": round(sum(1 for r in rows if r["rank"] and r["rank"] <= 30) / len(rows), 4),
        "mean_reciprocal_rank": round(sum(1 / r for r in ranks) / len(rows), 4),
        "by_age": {b: round(sum(v) / len(v), 4) for b, v in sorted(by_age.items())},
        "by_importance": {b: round(sum(v) / len(v), 4) for b, v in sorted(by_imp.items())},
        "forgotten": sum(1 for r in rows if r["excluded_as_forgotten"]),
    }


def own_experiences(
    cfg: GAConfig, snapshot: Path, agents: list[str], *, k: int = 10, embedding_provider: Any = None, settings: RetrievalSettings | None = None
) -> dict[str, Any]:
    db = _open_clone(snapshot)
    try:
        now = parse_iso(db.get_meta("sim_time")) or datetime.now()
        store = MemoryStore(db)
        emb = _embeddings(cfg, store, embedding_provider)
        retriever = Retriever(store, emb, settings or RetrievalSettings.from_config(cfg.retrieval))
        rows = []
        for r in db.query("SELECT json FROM conversations ORDER BY started_at, id"):
            c = json.loads(r["json"])
            if not c.get("utterances"):
                continue
            query = c.get("summary") or c["utterances"][0]["text"]
            for aid in c["participants"]:
                if aid not in agents:
                    continue
                res = retriever.retrieve(aid, query, now, max_items=k, budget_tokens=None, commit_access=False)
                hit = any(m.conversation_id == c["id"] for m in res.delivered)
                ranked = [x.memory for x in res.candidates]
                rank = next((i + 1 for i, m in enumerate(ranked) if m.conversation_id == c["id"]), None)
                age = (now - parse_iso(c["started_at"])).total_seconds() / 3600 if parse_iso(c["started_at"]) else None
                rows.append({"agent_id": aid, "conversation_id": c["id"], "age_hours": round(age, 2) if age is not None else None, "hit": hit, "rank": rank})
        hits = [r["hit"] for r in rows]
        return {
            "k": k,
            "rows": rows,
            "summary": {
                "n": len(rows),
                "recall_at_k": round(sum(hits) / len(hits), 4) if hits else None,
                "mean_rank_of_hits": round(sum(r["rank"] for r in rows if r["rank"]) / max(1, sum(1 for r in rows if r["rank"])), 2) if rows else None,
            },
            "embedding_model": emb.model_key,
            "reference_time": now.isoformat(),
        }
    finally:
        db.close()
