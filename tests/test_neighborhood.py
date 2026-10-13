"""A scenario variant with a new neighborhood: smallville_n35 (an extension of the paper's town)."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
import yaml

from generative_agents.config import repo_path
from generative_agents.scenario.audit import audit_scenario
from generative_agents.scenario.loader import load_scenario
from generative_agents.scenario.neighborhood import House, add_houses, build
from generative_agents.world.navigation import Navigator
from helpers import make_sim

N25 = repo_path("scenarios/smallville_n25/scenario.yaml")
N35 = repo_path("scenarios/smallville_n35/scenario.yaml")
SPEC = repo_path("scenarios/smallville_n35/neighborhood.yaml")
NEWCOMERS = [
    "ngozi_okafor",
    "daniel_okafor",
    "chidi_okafor",
    "ingrid_halvorsen",
    "per_halvorsen",
    "sofie_halvorsen",
    "linh_tran",
    "omar_haddad",
    "joy_villanueva",
    "declan_byrne",
]


def _copy_spec(tmp_path, edit=None):
    """The n35 spec in a scratch scenarios folder next to the real n25 (so builds never touch the repo)."""

    shutil.copytree(repo_path("scenarios/smallville_n25"), tmp_path / "smallville_n25")
    (tmp_path / "smallville_n35").mkdir()
    spec = yaml.safe_load(SPEC.read_text())
    if edit:
        edit(spec)
    out = tmp_path / "smallville_n35/neighborhood.yaml"
    out.write_text(SPEC.read_text() if edit is None else yaml.safe_dump(spec, sort_keys=False))
    return out


def test_the_committed_variant_is_exactly_what_its_spec_builds(tmp_path):
    out = build(_copy_spec(tmp_path))
    for rel in out["files"]:
        assert (tmp_path / "smallville_n35" / rel).read_text() == repo_path(f"scenarios/smallville_n35/{rel}").read_text(), rel


def test_the_paper_town_is_kept_and_ten_newcomers_move_in():
    n25, n35 = load_scenario(N25), load_scenario(N35)
    assert n35.agent_ids == n25.agent_ids + NEWCOMERS
    for aid in n25.agent_ids:  # the same files: identities, seeds and spatial memory unchanged
        assert n35.agents[aid].released_code["_file_sha256"] == n25.agents[aid].released_code["_file_sha256"]
    rep = audit_scenario(n35)
    assert rep["ok"], rep["issues"]
    assert rep["unique_ids"] and rep["unique_names"]
    assert [h["agent"] for h in rep["knowledge_holders"]["party_knowledge"]] == ["isabella_rodriguez"]
    assert [h["agent"] for h in rep["knowledge_holders"]["candidacy_knowledge"]] == ["sam_moore"]
    assert n35.events == n25.events
    # the map changes only where the new houses and the gate are
    a, b = n25.world, n35.world
    changed = (a.sector != b.sector) | (a.collision != b.collision) | (a.arena != b.arena) | (a.object != b.object)
    new_houses = np.isin(b.sector, [b.legend["sector"].index(s) for s in b.legend["sector"][len(a.legend["sector"]) :]])
    gate = np.zeros_like(changed)
    gate[64:66, 105] = True
    assert not (changed & ~new_houses & ~gate).any()
    assert b.legend["sector"][: len(a.legend["sector"])] == a.legend["sector"]


def test_every_newcomer_sleeps_at_home_and_can_walk_to_town():
    sc = load_scenario(N35)
    w = sc.world
    nav = Navigator(w)
    cafe = w.walkable_tiles_for("the Ville:Hobbs Cafe:cafe")
    starts = set()
    for aid in NEWCOMERS:
        spec = sc.agents[aid]
        tile = tuple(spec.initial_tile)
        assert w.address_at(*tile) == f"{spec.identity.living_area}:bed", aid
        assert nav.nearest(tile, cafe) is not None, aid
        assert spec.seeds and all(s.flags == [] for s in spec.seeds)
        home = spec.identity.living_area.split(":")[1]
        assert home in spec.spatial_memory["the Ville"] and "Hobbs Cafe" in spec.spatial_memory["the Ville"]
        starts.add(tile)
    assert len(starts) == len(NEWCOMERS)  # couples start on the two halves of their bed


def test_houses_need_open_reachable_ground():
    base = json.loads(repo_path("scenarios/smallville_n25/map/the_ville.json").read_text())
    with pytest.raises(ValueError, match="not open ground"):
        add_houses(base, [House("New house", "Adam Smith's house", (72, 18))], street=(77, 33))  # on Hobbs Cafe
    with pytest.raises(ValueError, match="cannot be reached"):
        add_houses(base, [House("New house", "Adam Smith's house", (116, 86))], street=(77, 33))  # outside the fence
    with pytest.raises(ValueError, match="cut through a building"):
        add_houses(base, [], street=(77, 33), openings=[(72, 18, 73, 18)])
    with pytest.raises(ValueError, match="has no rooms"):
        add_houses(base, [House("New house", "Adam Smith's house", (116, 86), {"kitchen": "galley"})], street=(77, 33), openings=[(105, 64, 105, 65)])
    data = add_houses(base, [House("New house", "Adam Smith's house", (116, 86))], street=(77, 33), openings=[(105, 64, 105, 65)])
    assert "New house" in data["legend"]["sector"]


@pytest.mark.parametrize(
    "text",
    [
        "Isabella Rodriguez invited you to her Valentine's Day celebration",
        "You heard there will be a party at Hobbs Cafe",
        "You wonder who the next mayor will be",
        "Sam Moore is running for office",
    ],
)
def test_newcomers_start_without_knowledge_of_the_seeded_events(tmp_path, text):
    spec = _copy_spec(tmp_path, lambda s: s["newcomers"][0]["seeds"].append(text))
    with pytest.raises(ValueError, match="seeded-event knowledge"):
        build(spec)


def test_the_new_neighborhood_runs(tmp_path):
    sim = make_sim(tmp_path, NEWCOMERS[:3] + ["sofie_halvorsen"], start="2023-02-13T07:00:00", extra=["scenario.path=scenarios/smallville_n35/scenario.yaml"])
    sim.initialize()
    start = {aid: tuple(sim.svc.states.get(aid).tile) for aid in sim.order}
    sim.run(max_steps=120)
    moved = [aid for aid in sim.order if tuple(sim.svc.states.get(aid).tile) != start[aid]]
    assert moved, "nobody left their bed in twenty game minutes"
    unreachable = [r for r in sim.db.query("SELECT json FROM events WHERE type='action_failure'") if "no reachable tile" in r["json"]]
    assert not unreachable
    went = {json.loads(r["json"]).get("address", "").split(":")[1] for r in sim.db.query("SELECT json FROM events WHERE type='action'")}
    assert went  # they chose places on the map and found paths to them
