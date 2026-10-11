"""Export a recorded town as static files for the town front end's demo build.

``ga export-demo --run-dir DIR --out SITE`` replays the run (no model calls), step by step, and
writes what the interface would have polled: one frame per step, the game state whenever it
changes, and every feed event with the step it appeared at. It also writes the town's info and
map and a snapshot of the research inspector's data at the end of the run. Built with
``npm run build:demo``, the front end plays these files back in any browser with no server
and no model: a recording to look through, not a town to play (actions are refused).

Frames use string tables (activities, addresses, action kinds and partners repeat a lot), so a
day of a three-resident town is a few hundred kilobytes.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..viewer.data import RunData
from .api import object_info, town_info, town_map
from .session import GameSession

FRAME_FIELDS = ["x", "y", "activity", "kind", "address", "sleeping", "conversation", "partner", "path_left"]
_TABLED = {"activity", "kind", "address", "conversation", "partner"}


class _Strings:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def id(self, value: str | None) -> int:
        if value is None:
            return -1
        if value not in self.index:
            self.index[value] = len(self.items)
            self.items.append(value)
        return self.index[value]


def _dump(path: Path, data: Any) -> int:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _research(run_dir: Path, agents: list[str], *, memories: int = 400, traces: int = 60, calls: int = 150) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """The inspector's reads, keyed by the path the front end asks for (``research(path)``), in
    files: ``shared`` and one per resident, so a 25-resident town stays under per-file size
    limits and the page loads only what it opens. ``owner`` names the file of each ``call/``,
    ``trace/`` and ``evidence/`` key, which the path alone does not tell."""

    data = RunData(run_dir)
    shared: dict[str, Any] = {}
    files: dict[str, dict[str, Any]] = {"shared": shared}
    owner: dict[str, str] = {}
    info = data.run_info()
    info["has_evaluation"] = False
    info["has_experiment"] = False
    info["recording"] = True
    shared["run"] = info
    shared["manifest"] = data.manifest()
    shared["diffusion"] = data.diffusion()
    listed: set[int] = set()
    shared[f"calls?limit={calls}"] = rows = data.calls(task=None, agent=None, limit=calls, before=None)
    listed.update(int(r["id"]) for r in rows)
    for aid in agents:
        name = f"agent-{aid}"
        mine = files[name] = {}
        mine[f"calls?limit={calls}&agent={aid}"] = rows = data.calls(task=None, agent=aid, limit=calls, before=None)
        listed.update(int(r["id"]) for r in rows)
        mine[f"agent/{aid}"] = data.agent(aid, None)
        mine[f"agent/{aid}/memories"] = data.memories(aid, kind=None, text=None, limit=memories, before=None)
        mine[f"agent/{aid}/traces?limit={traces}"] = trace_rows = data.traces(aid, traces, None)
        for t in trace_rows:
            mine[f"trace/{t['id']}"] = data.trace(t["id"])
            owner[f"trace/{t['id']}"] = name
        mine[f"agent/{aid}/reflections"] = refl = data.reflections(aid)
        for r in refl:
            mine[f"evidence/{r['id']}"] = data.evidence(r["id"])
            owner[f"evidence/{r['id']}"] = name
    for cid in sorted(listed):
        call = data.call(cid)
        name = f"agent-{call.get('agent_id')}" if f"agent-{call.get('agent_id')}" in files else "shared"
        files[name][f"call/{cid}"] = call
        owner[f"call/{cid}"] = name
    return files, owner


def export_demo(run_dir: Path, out_dir: Path, *, frame_every: int = 1, scratch: Path | None = None) -> dict[str, Any]:
    """Replay ``run_dir`` with no model calls and write the demo data into ``out_dir/demo``."""

    from ..simulation.engine import load_run_config, save_config

    run_dir = Path(run_dir)
    target = Path(out_dir) / "demo"
    target.mkdir(parents=True, exist_ok=True)
    cfg = load_run_config(run_dir)
    if not cfg.game.enabled:
        raise ValueError("this run was not made with the town game (game.enabled is false)")
    work = Path(scratch) if scratch else Path(tempfile.mkdtemp(prefix="ga-demo-"))
    replay_dir = work / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    save_config(cfg, replay_dir)
    session = GameSession(cfg, replay_dir, replay_from=run_dir, speed="max")
    sim, game = session.sim, session.game
    strings = _Strings()
    frames: list[list[Any]] = []
    states: list[dict[str, Any]] = []
    feed: list[dict[str, Any]] = []
    last = {"game": "", "schedules": "", "objects": ""}
    seen_seq = 0

    def capture(step: int) -> None:
        nonlocal seen_seq
        pub = session._published
        snap: dict[str, Any] = {"step": step}
        for key in ("game", "schedules", "objects"):
            text = json.dumps(pub.get(key), sort_keys=True, default=str)
            if text != last[key]:
                last[key] = text
                snap[key] = pub.get(key)
        if len(snap) > 1:
            states.append(snap)
        for ev in list(session._feed):
            if ev["seq"] > seen_seq:
                feed.append({**ev, "step": step})
                seen_seq = ev["seq"]
        if session._frames and (step % frame_every == 0 or not frames):
            fr = session._frames[-1]
            row: list[Any] = [fr["step"]]
            for aid in sim.order:
                a = fr["agents"].get(aid) or {}
                row.append([strings.id(a.get(f)) if f in _TABLED else a.get(f) for f in FRAME_FIELDS])
            frames.append(row)

    try:
        sim.begin()
        session._ready = True
        game.ensure_started(sim.clock.now)
        session._publish(frame=True)
        capture(0)
        info = town_info(session)
        town = town_map(session)
        while not session.finished:
            sim.advance()
            session._publish(frame=True)
            capture(sim.clock.step - 1)  # the step just played, as in its frame
        objects = {a: object_info(session, a)["search_theme"] for a in town["objects"]}
        end = session.end
        sim.finish(sim.wind_down())
    finally:
        sim.close()

    info["mode"] = "replay"
    info["recording"] = {"source_run": sim.cfg.run.name, "mode": cfg.run_mode, "model": f"{cfg.providers.llm.kind}:{cfg.providers.llm.model}"}
    timeline = {
        "start": info["start"],
        "end": end.isoformat(),
        "seconds_per_step": cfg.scenario.seconds_per_step,
        "agents": list(sim.order),
        "fields": FRAME_FIELDS,
        "strings": strings.items,
        "frames": frames,
        "states": states,
        "feed": feed,
    }
    sizes = {
        "info.json": _dump(target / "info.json", info),
        "map.json": _dump(target / "map.json", town),
        "timeline.json": _dump(target / "timeline.json", timeline),
        "objects.json": _dump(target / "objects.json", objects),
    }
    files, owner = _research(run_dir, list(sim.order))
    (target / "research.json").unlink(missing_ok=True)  # the single-file layout of earlier exports
    (target / "research").mkdir(exist_ok=True)
    sizes["research/index.json"] = _dump(target / "research" / "index.json", {"files": sorted(files), "owner": owner})
    for name, content in files.items():
        sizes[f"research/{name}.json"] = _dump(target / "research" / f"{name}.json", content)
    if scratch is None:
        shutil.rmtree(work, ignore_errors=True)
    return {"out": str(target), "frames": len(frames), "states": len(states), "events": len(feed), "bytes": sizes}
