"""A new neighborhood for a scenario variant: houses on open land and the people who move in.

The base scenario is never changed. A spec (``neighborhood.yaml``) names the base scenario, the
houses to add and the newcomers; ``ga build-neighborhood`` writes the variant's map, one agent
file per newcomer, its constraints and its ``scenario.yaml``: the same bytes from the same inputs.

Each house copies an existing building tile for tile (walls, door, rooms, furniture) onto an
empty plot under a new name; rooms named after people are renamed for the newcomers. A plot must
be open ground with a free border, and every tile people can reach in the original building must
be reachable from the town's streets in the copy. Newcomers start in their own bed and know their
own house and the public places their spec lists. Their texts may not carry knowledge of the seeded events (party, candidacy):
the build refuses them, and the scenario audit checks the result again.
"""

from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ..world.hierarchy import WorldMap
from .importer import _flags
from .loader import load_scenario

PERCEPTION = {"vision_r": 8, "att_bandwidth": 8, "retention": 8}
RELEASED_CODE = {"recency_w": 1, "relevance_w": 1, "importance_w": 1, "recency_decay": 0.995, "importance_trigger_max": 250}
LAYERS = ("collision", "sector", "arena", "object", "spawn")


@dataclass
class House:
    name: str
    template: str
    at: tuple[int, int]  # where the template's top-left corner goes
    rooms: dict[str, str] = field(default_factory=dict)  # template room name -> new name


def rle(values: np.ndarray) -> list[list[int]]:
    out: list[list[int]] = []
    for v in values.ravel().tolist():
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def _layers(data: dict[str, Any]) -> dict[str, np.ndarray]:
    w = WorldMap(data)
    return {"collision": w.collision.astype(np.int32), "sector": w.sector.copy(), "arena": w.arena.copy(), "object": w.object.copy(), "spawn": w.spawn.copy()}


def _reachable(collision: np.ndarray, start: tuple[int, int]) -> np.ndarray:
    h, wd = collision.shape
    seen = np.zeros_like(collision, dtype=bool)
    seen[start[1], start[0]] = True
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < wd and 0 <= ny < h and not seen[ny, nx] and not collision[ny, nx]:
                seen[ny, nx] = True
                queue.append((nx, ny))
    return seen


def add_houses(
    base: dict[str, Any],
    houses: list[House],
    *,
    street: tuple[int, int],
    openings: list[tuple[int, int, int, int]] = (),
    margin: int = 1,
) -> dict[str, Any]:
    """The base map plus ``houses``; ``street`` is any outdoor tile of the town's street network.

    The town is fenced in, so land outside it is reachable only through an opening: each
    ``(x0, y0, x1, y1)`` rectangle clears the fence (collision outside any building) inside it.
    """

    L = _layers(base)
    legend = {k: list(v) for k, v in base["legend"].items()}
    height, width = L["sector"].shape
    was_open = _reachable(L["collision"], street)  # in the base town
    must_open: dict[str, list[tuple[int, int]]] = {}  # copies of tiles people could reach in the template
    for x0, y0, x1, y1 in openings:
        gate = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        if L["sector"][gate].any():
            raise ValueError(f"opening {[x0, y0, x1, y1]} would cut through a building")
        L["collision"][gate] = 0
    for house in houses:
        if house.name in legend["sector"]:
            raise ValueError(f"{house.name!r} is already a place on the map")
        if house.template not in legend["sector"]:
            raise ValueError(f"template {house.template!r} is not a building on the map")
        ts = legend["sector"].index(house.template)
        ys, xs = np.nonzero(L["sector"] == ts)
        x0, y0 = int(xs.min()), int(ys.min())
        dx, dy = house.at[0] - x0, house.at[1] - y0
        tw, th = int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1
        bx0, by0, bx1, by1 = house.at[0] - margin, house.at[1] - margin, house.at[0] + tw - 1 + margin, house.at[1] + th - 1 + margin
        if bx0 < 0 or by0 < 0 or bx1 >= width or by1 >= height:
            raise ValueError(f"{house.name!r} at {list(house.at)} does not fit on the map with a {margin}-tile border")
        plot = (slice(by0, by1 + 1), slice(bx0, bx1 + 1))
        if L["sector"][plot].any() or L["collision"][plot].any():
            raise ValueError(f"{house.name!r} at {list(house.at)}: the plot (with its border) is not open ground")
        unknown = set(house.rooms) - {legend["arena"][a] for a in np.unique(L["arena"][L["sector"] == ts])}
        if unknown:
            raise ValueError(f"{house.name!r}: template {house.template!r} has no rooms {sorted(unknown)}")
        legend["sector"].append(house.name)
        si = len(legend["sector"]) - 1
        for old in sorted({legend["arena"][a] for a in np.unique(L["arena"][L["sector"] == ts])}):
            new = house.rooms.get(old, old)
            if new not in legend["arena"]:
                legend["arena"].append(new)
        for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
            nx, ny = x + dx, y + dy
            L["sector"][ny, nx] = si
            L["collision"][ny, nx] = L["collision"][y, x]
            old = legend["arena"][L["arena"][y, x]]
            L["arena"][ny, nx] = legend["arena"].index(house.rooms.get(old, old)) if old else 0
            L["object"][ny, nx] = L["object"][y, x]
            if was_open[y, x]:
                must_open.setdefault(house.name, []).append((nx, ny))
    open_ = _reachable(L["collision"], street)
    for house in houses:
        cut_off = [t for t in must_open.get(house.name, []) if not open_[t[1], t[0]]]
        if cut_off:
            raise ValueError(f"{house.name!r}: tile {list(cut_off[0])} cannot be reached from the streets")
    out = {k: v for k, v in base.items() if k not in ("legend", "layers")}
    out["legend"] = legend
    out["layers"] = {k: rle(L[k]) for k in LAYERS}
    return out


def spatial_tree(world: WorldMap, sectors: list[str]) -> dict[str, Any]:
    """The map's own rooms and objects for whole sectors, as a spatial memory tree."""

    tree = world.tree[world.world]
    missing = [s for s in sectors if s not in tree]
    if missing:
        raise ValueError(f"not places on the map: {missing}")
    return {world.world: {s: {a: list(objs) for a, objs in tree[s].items()} for s in sectors}}


def _home_tiles(world: WorldMap, living_area: str) -> list[tuple[int, int]]:
    beds = world.walkable_tiles_for(f"{living_area}:bed")
    rest = [t for t in world.walkable_tiles_for(living_area) if t not in beds]
    return sorted(beds, key=lambda t: (t[1], t[0])) + sorted(rest, key=lambda t: (t[1], t[0]))


# Newcomers start knowing nothing about the seeded events, nor about the election they concern.
BARRED = [r"valentine", r"\bpart(y|ies)\b", r"\bmayor", r"\belection", r"candida", r"\brunning for\b", r"\bcampaign"]


def _knowledge(person: dict[str, Any]) -> list[str]:
    ident = person["identity"]
    texts = [ident.get(k) or "" for k in ("innate", "learned", "currently", "lifestyle", "daily_plan_req")] + list(person.get("seeds", []))
    found = {f for t in texts for f in _flags(t)}
    found |= {f"mentions /{p}/" for t in texts for p in BARRED if re.search(p, t, re.I)}
    return sorted(found)


def build(spec_path: str | Path) -> dict[str, Any]:
    """Write the variant described by ``spec_path`` next to it; returns what was written."""

    spec_path = Path(spec_path).resolve()
    root = spec_path.parent
    spec = yaml.safe_load(spec_path.read_text())
    base_path = (root / spec["base"]).resolve()
    base_sc = yaml.safe_load(base_path.read_text())
    base_dir = base_path.parent
    base_map = json.loads((base_dir / base_sc["map"]).read_text())
    houses = [House(h["name"], h["template"], tuple(h["at"]), dict(h.get("rooms") or {})) for h in spec["houses"]]
    openings = [tuple(o) for o in spec.get("openings", [])]
    data = add_houses(base_map, houses, street=tuple(spec["street_tile"]), openings=openings, margin=int(spec.get("margin", 1)))
    data["source"] = {**base_map.get("source", {}), "neighborhood": f"{spec_path.name} on {base_sc['map']} of {base_sc['name']}"}
    world = WorldMap(data)

    base_agents = list(base_sc["agents"])
    dirs = base_sc.get("agents_dir", "agents")
    base_agent_dirs = [base_dir / d for d in (dirs if isinstance(dirs, list) else [dirs])]
    taken_names = {a.identity.name for a in load_scenario(base_path).agents.values()}
    used: set[tuple[int, int]] = set()
    agents: dict[str, dict[str, Any]] = {}
    for person in spec["newcomers"]:
        aid, ident = person["id"], dict(person["identity"])
        if aid in base_agents or aid in agents or ident["name"] in taken_names:
            raise ValueError(f"{aid}: id or name already used in the town")
        taken_names.add(ident["name"])
        carried = _knowledge(person)
        if carried:
            raise ValueError(f"{aid}: newcomers may not carry seeded-event knowledge ({', '.join(carried)})")
        if not world.exists(ident["living_area"]):
            raise ValueError(f"{aid}: living area {ident['living_area']} is not on the map")
        tile = next((t for t in _home_tiles(world, ident["living_area"]) if t not in used), None)
        if tile is None:
            raise ValueError(f"{aid}: no free tile to start on in {ident['living_area']}")
        used.add(tile)
        home = ident["living_area"].split(":")[1]
        agents[aid] = {
            "id": aid,
            "identity": ident,
            "identity_flags": [],
            "perception": dict(PERCEPTION),
            "released_code": dict(RELEASED_CODE),
            "initial_tile": list(tile),
            "seeds": [{"text": s, "flags": []} for s in person.get("seeds", [])],
            "spatial_memory": spatial_tree(world, [home] + [s for s in _flat(person.get("knows", [])) if s != home]),
            "origin": "an original newcomer written for this repository (not in the paper or its released data)",
        }

    constraints = yaml.safe_load((base_dir / base_sc["constraints"]).read_text()) if base_sc.get("constraints") else {}
    for sector, staff in (spec.get("staff") or {}).items():
        hours = constraints.get("opening_hours", {}).get(sector)
        if hours is None:
            raise ValueError(f"staff listed for {sector!r}, which has no opening hours")
        hours["staff"] = list(hours.get("staff", [])) + [s for s in staff if s not in hours.get("staff", [])]

    def rel(p: Path) -> str:
        return os.path.relpath(p, root)

    scenario = {
        "name": spec["name"],
        "description": " ".join(str(spec["description"]).split()),
        "source": {"base": rel(base_path), "spec": spec_path.name},
        "start": base_sc["start"],
        "seconds_per_step": base_sc["seconds_per_step"],
        "map": spec["map"],
        "agents": base_agents + list(agents),
        "agents_dir": [rel(d) for d in base_agent_dirs] + ["agents"],
        "events": rel(base_dir / base_sc["events"]) if base_sc.get("events") else None,
        "constraints": "constraints.yaml",
        "familiar_public_areas": f"{base_sc.get('familiar_public_areas', 'as in the base scenario')}; newcomers: the places their spec lists",
    }

    written: dict[str, str] = {}

    def write(rel_path: str, text: str) -> None:
        p = root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written[rel_path] = text

    write(spec["map"], json.dumps(data, separators=(",", ":")))
    for aid, agent in agents.items():
        write(
            f"agents/{aid}.yaml", f"# Generated from {spec_path.name} in this folder by `ga build-neighborhood`; edit the spec, not this file.\n" + _dump(agent)
        )
    header = (
        f"# Generated from {spec_path.name} in this folder by `ga build-neighborhood`: {rel(base_dir / base_sc['constraints'])} plus the newcomers on staff.\n"
    )
    write("constraints.yaml", header + _dump(constraints))
    write("scenario.yaml", f"# Generated from {spec_path.name} in this folder by `ga build-neighborhood`; edit the spec, not this file.\n" + _dump(scenario))
    return {"scenario": str(root / "scenario.yaml"), "houses": [h.name for h in houses], "newcomers": list(agents), "files": sorted(written)}


def _dump(obj: Any) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=120)


def _flat(items: list[Any]) -> list[str]:
    """``knows`` entries, with YAML aliases of place lists spliced in."""

    out: list[str] = []
    for item in items:
        out.extend(_flat(item) if isinstance(item, list) else [item])
    return list(dict.fromkeys(out))
