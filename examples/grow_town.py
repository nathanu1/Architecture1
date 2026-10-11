"""Grow a town on a real model: a scripted builder gathers motifs, grants the residents' wishes
and decorates the Town Square while the simulation runs, in wall-clock-bounded segments.

    python examples/grow_town.py runs/town-n25-llama --config configs/town_n25_ollama.yaml \\
        --set providers.llm.model=llama3.2:3b --until 2023-02-13T12:00:00 --minutes 100

Run the same command again to continue from the last checkpoint (the config is read from the run
directory then). Every action goes through GameSession.submit, as the web UI's would, so the run
replays with zero model calls and exports with ``ga export-demo``. The builder only acts within
the game's rules: it searches objects whose cooldown has passed, places only items the game
accepts (``validate_build``) and can pay for, and delivers a wish only when it is ready and the
resident is awake and free. It never writes to a resident's memory or prompt.
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime
from pathlib import Path

from generative_agents.config import load_config
from generative_agents.game.session import GameSession
from generative_agents.schemas import RunStatus
from generative_agents.simulation.engine import RunStopped, load_run_config, save_config

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("run_dir")
ap.add_argument("--config", help="town config for a new run")
ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
ap.add_argument("--until", required=True, help="simulation time to stop at (ISO)")
ap.add_argument("--minutes", type=float, default=100.0, help="wall-clock budget for this segment")
ap.add_argument("--greet", type=int, default=6, help="residents to greet with a chat")
args = ap.parse_args()

run = Path(args.run_dir)
if (run / "config.yaml").exists():
    cfg = load_run_config(run, args.set)
else:
    cfg = load_config(args.config, overrides=args.set)
    run.mkdir(parents=True, exist_ok=True)
    save_config(cfg, run)
session = GameSession(cfg, run, speed="max")
sim, game = session.sim, session.game
until = datetime.fromisoformat(args.until)
deadline = time.monotonic() + args.minutes * 60
wall0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[{(time.monotonic() - wall0) / 60:6.1f} min] {sim.clock.now:%H:%M}  {msg}", flush=True)


def free(aid: str) -> bool:
    v = sim.view_of(aid)
    return not v.sleeping and not v.conversation_partner


def affordable(cost: dict[str, int], counts: dict[str, int]) -> bool:
    return all(counts.get(t, 0) >= n for t, n in cost.items())


def find_spot(item_id: str, tiles: list[tuple[int, int]]) -> list[dict] | None:
    for x, y in tiles:
        ops = [{"op": "place", "catalog_id": item_id, "x": x, "y": y, "rot": 0, "paint": None}]
        if game.validate_build(ops)["ok"]:
            return ops
    return None


# Words in a wish that point at particular items; otherwise the cheapest item of the kind.
HINTS = {
    "sit": ["bench", "picnic_table", "armchair", "porch_swing"],
    "seat": ["bench", "armchair", "picnic_table"],
    "read": ["reading_nook", "bookshelf"],
    "book": ["bookshelf", "reading_nook"],
    "study": ["writing_desk", "reading_nook", "bookshelf"],
    "quiet": ["reading_nook", "armchair"],
    "corner": ["reading_nook", "armchair"],
    "nook": ["reading_nook"],
    "write": ["writing_desk"],
    "desk": ["writing_desk"],
    "flower": ["flower_planter", "potted_fern", "flower_arch", "cherry_tree"],
    "garden": ["flower_planter", "birdbath", "hedge", "potted_fern"],
    "plant": ["potted_fern", "flower_planter"],
    "tree": ["cherry_tree"],
    "music": ["jukebox", "little_stage"],
    "party": ["party_table", "string_lights", "confetti_cannon"],
    "light": ["string_lights", "lamp_post"],
    "art": ["easel", "garden_sculpture"],
    "paint": ["easel"],
    "craft": ["workbench", "pottery_wheel"],
    "tool": ["workbench"],
    "tea": ["tea_cart"],
    "coffee": ["tea_cart"],
    "cozy": ["armchair", "braided_rug", "reading_nook"],
    "rug": ["braided_rug"],
    "chair": ["armchair"],
    "neighbor": ["picnic_table", "bench", "notice_board"],
    "community": ["notice_board", "picnic_table", "town_fountain"],
    "notice": ["notice_board"],
    "mail": ["mailbox"],
    "fountain": ["town_fountain"],
    "telescope": ["star_telescope"],
    "star": ["star_telescope"],
}


def wish_score(item_id: str, wish: str) -> int:
    words = re.findall(r"[a-z]+", wish.lower())
    return sum(1 for w in words for key, ids in HINTS.items() if w.startswith(key) and item_id in ids)


objects = sorted(a for a in sim.world.address_tiles if a.count(":") == 3)
square = next((a for a in sim.world.address_tiles if ":Town Square:" in a and a.count(":") == 2), None)
DECOR = ["gazebo", "town_fountain", "cherry_tree", "picnic_table", "lamp_post", "bench", "flower_planter"]
tried: dict[str, int] = {}  # request id -> step its build was submitted
offered: dict[str, int] = {}  # request id -> step its delivery was submitted
greeted: set[str] = {a.payload.get("agent") for a in game.actions.items if a.kind == "chat"}
last = {"search": -999, "decor": -999, "greet": -999, "report": -999}

sim.begin()
session._ready = True
game.ensure_started(sim.clock.now)
log(f"run {run.name}: step {sim.clock.step}, {len(sim.order)} residents, until {until:%H:%M}, {args.minutes:.0f} min budget")
status = RunStatus.INTERRUPTED
try:
    while sim.clock.now < until and time.monotonic() < deadline:
        step, now = sim.clock.step, sim.clock.now
        counts = game.theme_counts()
        level = game.level()
        requests = game.store.requests()
        open_reqs = [r for r in requests if r["status"] == "open"]
        needed = {r["theme"] for r in open_reqs}

        # gather motifs: one search every five game minutes, preferring the themes wishes need
        if step - last["search"] >= 30:
            cool = game.store.get("cooldowns")
            placed = {p.address for p in game.store.items()}
            ready = [a for a in objects if a not in placed and not (cool.get(a) and datetime.fromisoformat(cool[a]) > now)]
            themed = [(a, game.aff.search_theme(a)) for a in ready]
            pick = next((a for a, t in themed if t in needed and counts.get(t, 0) < 3), None) or next(
                (a for a, t in themed if t and counts.get(t, 0) < 2), None
            )
            if pick:
                session.submit("search", {"address": pick})
                last["search"] = step

        # grant wishes: an unlocked item of the wished kind that fits the wished place, the one the
        # wish's words point at first, else the cheapest
        for req in open_reqs:
            if step - tried.get(req["id"], -999) < 60:
                continue
            tiles = sorted(sim.world.address_tiles.get(req["place_address"], []))
            items = sorted(
                (it for it in game.content.items if it.theme == req["theme"] and it.unlock <= level and affordable(it.cost, counts)),
                key=lambda it: (-wish_score(it.id, req["wish"]), sum(it.cost.values()), it.id),
            )
            for it in items:
                ops = find_spot(it.id, tiles)
                if ops:
                    session.submit("build", {"ops": ops})
                    tried[req["id"]] = step
                    for t, n in it.cost.items():
                        counts[t] = counts.get(t, 0) - n
                    log(f"build {it.id} for {req['agent_id']}'s wish ({req['wish']}) at {req['place_label']}")
                    break
            else:
                tried[req["id"]] = step  # nothing fits or affordable now; look again in ten minutes

        # deliver ready wishes in person, one per step
        ready_reqs = [r for r in requests if r["status"] == "ready" and step - offered.get(r["id"], -999) >= 30 and free(r["agent_id"])]
        if ready_reqs:
            r = ready_reqs[0]
            session.submit("deliver", {"request": r["id"]})
            offered[r["id"]] = step
            log(f"deliver {r['wish']} to {r['agent_id']}")

        # decorate the Town Square with what is left, every half hour, the least-used piece first
        if square and not open_reqs and step - last["decor"] >= 180:
            # spread pieces out: the free tile farthest from what is already there, nearest the middle
            tiles = sorted(sim.world.address_tiles.get(square, []))
            cx = sum(x for x, _ in tiles) / max(1, len(tiles))
            cy = sum(y for _, y in tiles) / max(1, len(tiles))
            there = [(p.x, p.y) for p in game.store.items() if p.address.startswith(square)]
            tiles.sort(key=lambda t: (-min((abs(t[0] - a) + abs(t[1] - b) for a, b in there), default=99), abs(t[0] - cx) + abs(t[1] - cy)))
            have = [p.catalog_id for p in game.store.items()]
            for item_id in sorted(DECOR, key=lambda i: (have.count(i), -game.content.item(i).unlock)):
                it = game.content.item(item_id)
                if it.unlock <= level and affordable(it.cost, counts) and sum(counts.values()) - sum(it.cost.values()) >= 4:
                    ops = find_spot(item_id, tiles[:60])
                    if ops:
                        session.submit("build", {"ops": ops})
                        log(f"decorate the Town Square: {item_id} at {ops[0]['x']},{ops[0]['y']}")
                        break
            last["decor"] = step

        # greet a few residents, one every 40 game minutes
        if len(greeted) < args.greet and step - last["greet"] >= 240 and now.hour >= 8:
            aid = next((a for a in sim.order if a not in greeted and free(a)), None)
            if aid:
                first = sim.identities[aid].first_name
                session.submit("chat", {"agent": aid, "text": f"Good morning, {first}! What are you up to today?"})
                greeted.add(aid)
                last["greet"] = step
                log(f"chat with {aid}")

        sim.advance()

        if step - last["report"] >= 180:
            totals = sim.rt.ledger.totals()
            convs = sim.db.one("SELECT count(*) AS n FROM conversations")["n"]
            states = {s: sum(1 for r in game.store.requests() if r["status"] == s) for s in ("open", "ready", "fulfilled")}
            log(
                f"step {sim.clock.step}: {totals['calls']} calls, {convs} conversations, wishes {states}, motifs {sum(game.theme_counts().values())}, level {game.level()}"
            )
            last["report"] = step
    status = sim.wind_down()
except RunStopped as stop:
    status = stop.status
    sim._abort(stop.status, stop.detail)
    log(f"stopped: {stop.detail}")
except KeyboardInterrupt:
    status = RunStatus.INTERRUPTED
    sim._abort(status, "interrupted by user")
    log("interrupted; back at the last checkpoint")
sim.finish(status)
sim.close()
log(f"segment ends ({status.value}) at {sim.clock.now:%H:%M}; run again to continue")
