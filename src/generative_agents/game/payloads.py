"""What the town interface asks for, as plain data (no web framework).

``game/api.py`` serves these over HTTP; ``game/tab.py`` hands them to a page that runs the town
in its own tab; ``game/export_demo.py`` writes them to files for the recorded demo.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import numpy as np

from .session import SPEEDS, GameSession


def _rle(arr: np.ndarray) -> list[list[int]]:
    flat = arr.reshape(-1).astype(int).tolist()
    out: list[list[int]] = []
    for v in flat:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def town_info(session: GameSession) -> dict[str, Any]:
    """Who lives in the town and what the game is made of (``/api/game/info``)."""

    sim, game = session.sim, session.game
    content = game.content
    residents = []
    for aid in sim.order:
        ident = sim.identities[aid]
        residents.append(
            {
                "id": aid,
                "name": ident.name,
                "first_name": ident.first_name,
                "age": ident.age,
                "innate": ident.innate,
                "learned": ident.learned,
                "currently": ident.currently,
                "lifestyle": ident.lifestyle,
                "living_area": ident.living_area,
                "loves": game.residents[aid]["loves"],
                "look": content.look(aid).model_dump(),
            }
        )
    manifest_llm = sim.rt.provider.describe() if hasattr(sim.rt.provider, "describe") else {}
    return {
        "run_id": sim.run_id,
        "mode": "replay" if session.replay else sim.cfg.run_mode,
        "observe": session.observe,
        "label": sim.cfg.run.label,
        "town_name": sim.cfg.game.town_name,
        "llm": {"kind": sim.cfg.providers.llm.kind, "model": sim.cfg.providers.llm.model, "local": sim.cfg.providers.llm.is_local(), "describe": manifest_llm},
        "embeddings": {"kind": sim.cfg.providers.embeddings.kind, "model": sim.cfg.providers.embeddings.model},
        "builder": game.builder,
        "start": sim.cfg.scenario.start.isoformat(),
        "end": session.end.isoformat(),
        "seconds_per_step": sim.cfg.scenario.seconds_per_step,
        "speeds": list(SPEEDS),
        "residents": residents,
        "content": content.public(),
        "zones": game.zones,
    }


def town_map(session: GameSession, placed: set[str] | None = None) -> dict[str, Any]:
    """The base map, run-length encoded, plus what the front end needs to draw it (``/api/game/map``).

    ``placed`` is the set of addresses of player-placed items. A server passes it from its own
    read-only connection, because the engine thread may already be stepping on the town's
    connection; without it the town's store is read directly (safe when nothing is running).
    """

    sim, game = session.sim, session.game
    if placed is None:
        placed = {p.address for p in game.store.items()}
    editor, world = game.editor, sim.world
    arenas = sorted({a for a in world.address_tiles if a.count(":") == 2})
    return {
        "world": world.world,
        "width": world.width,
        "height": world.height,
        "legend": {"sector": list(world.legend["sector"]), "arena": list(world.legend["arena"]), "object": list(editor._base_legend)},
        "layers": {
            "collision": _rle(editor._base_collision),
            "sector": _rle(world.sector),
            "arena": _rle(world.arena),
            "object": _rle(editor._base_object),
        },
        "outdoor_arenas": [a for a in arenas if editor.is_outdoor(a)],
        "ground_objects": sorted(editor._ground_size),
        "objects": sorted(a for a in world.address_tiles if a.count(":") == 3 and a not in placed),
    }


def object_info(session: GameSession, address: str) -> dict[str, Any]:
    """What the object card shows about one object (``/api/game/object``)."""

    return {"address": address, "name": address.rsplit(":", 1)[-1], "place": address.split(":")[1:3], "search_theme": session.game.aff.search_theme(address)}


def resident_detail(session: GameSession, aid: str, rows: Callable[..., list[Any]]) -> dict[str, Any]:
    """Recent exchanges with the player and recent conversations of one resident (``/api/game/resident``).

    ``rows(sql, params)`` reads committed state; a server passes its own read-only connection.
    Raises ``KeyError`` for an unknown resident.
    """

    if aid not in session.sim.identities:
        raise KeyError(f"no resident {aid}")
    exchanges = []
    for r in rows(
        "SELECT id, sim_time, kind, json FROM game_events WHERE agent_id=? AND kind IN ('chat','gift','delivered','request','rejected') ORDER BY id DESC LIMIT 30",
        (aid,),
    ):
        d = json.loads(r["json"])
        exchanges.append(
            {"id": r["id"], "time": r["sim_time"], "kind": r["kind"], **{k: d.get(k) for k in ("builder_line", "reply", "mood", "reason", "gift", "loved")}}
        )
    convs = []
    for r in rows("SELECT id, started_at, json FROM conversations WHERE participants LIKE ? ORDER BY started_at DESC LIMIT 6", (f"%{aid}%",)):
        c = json.loads(r["json"])
        convs.append(
            {
                "id": r["id"],
                "started_at": c.get("started_at"),
                "participants": c.get("participants"),
                "summary": c.get("summary"),
                "lines": [{"speaker": u.get("speaker_id"), "text": u.get("text")} for u in c.get("utterances", [])],
            }
        )
    return {"id": aid, "exchanges": list(reversed(exchanges)), "conversations": convs}
