"""Counterfactual forks (research extension): same past, different futures only where something changed."""

from __future__ import annotations

import json

import yaml

from generative_agents.cli import main
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.mock import MockLLM
from generative_agents.simulation.engine import Simulation, load_run_config, save_config
from generative_agents.simulation.fork import fork_run
from helpers import make_sim, sim_config

PAIR = ["isabella_rodriguez", "klaus_mueller"]
TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")


def test_a_fork_that_changes_nothing_reproduces_the_source_continuation(tmp_path):
    cfg = sim_config(PAIR, end="2023-02-13T10:00:00", extra=("output.snapshots=[initial, '2023-02-13T09:30:00', final]",))
    save_config(cfg, (tmp_path / "src").mkdir() or tmp_path / "src")
    src = Simulation(cfg, tmp_path / "src", provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    assert src.run() == "completed"
    snaps = src.snapshots()
    assert "2023-02-13T09-30-00" in snaps
    origin = fork_run(tmp_path / "src", "2023-02-13T09-30-00", tmp_path / "fork")
    assert origin["run_id"] == "src" and origin["sim_time"] == "2023-02-13T09:30:00"
    fork = Simulation(sim_config(PAIR, end="2023-02-13T10:00:00"), tmp_path / "fork", provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    assert fork.clock.now.isoformat() == "2023-02-13T09:30:00" and fork.initialized()
    assert fork.run() == "completed"
    assert fork.db.content_hash(TABLES) == src.db.content_hash(TABLES)
    assert fork.rt.budget.usage.cache_hits == 0 and fork.rt.budget.usage.calls > 0  # its own fresh ledger
    manifest = json.loads((tmp_path / "fork" / "manifest.json").read_text())
    assert manifest["forked_from"]["run_id"] == "src" and manifest["forked_from"]["snapshot"] == "2023-02-13T09-30-00"
    assert (tmp_path / "fork" / "snapshots" / "final.sqlite").exists()


def test_a_fork_with_an_intervention_diverges_only_after_the_fork_point(tmp_path):
    cfg = sim_config(PAIR, end="2023-02-13T10:00:00", extra=("output.snapshots=[initial, '2023-02-13T09:20:00', final]",))
    save_config(cfg, (tmp_path / "src").mkdir() or tmp_path / "src")
    src = Simulation(cfg, tmp_path / "src", provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    src.initialize()
    for aid in PAIR:
        src.svc.states.get(aid).tile = (78, 20)
    src.svc.states.flush()
    src.run()
    fire = [
        {
            "kind": "ambient",
            "at": "2023-02-13T09:21:00",
            "id": "fire1",
            "tile": [78, 19],
            "subject": "fire",
            "object": "burning",
            "description": "a fire is burning in Hobbs Cafe",
        }
    ]
    fork_run(tmp_path / "src", "2023-02-13T09-20-00", tmp_path / "fire", interventions=fire, label="fire fork")
    assert yaml.safe_load((tmp_path / "fire" / "interventions.yaml").read_text())["interventions"][0]["id"] == "fire1"
    fork = Simulation(load_run_config(tmp_path / "fire"), tmp_path / "fire", provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    fork.run()
    before = "2023-02-13T09:20:00"
    same = lambda db: [tuple(r) for r in db.query("SELECT owner_id, seq, description FROM memories WHERE created_at < ? ORDER BY owner_id, seq", (before,))]  # noqa: E731
    assert same(fork.db) == same(src.db)
    assert fork.svc.events.query("intervention") and not src.svc.events.query("intervention")
    assert fork.db.content_hash(TABLES) != src.db.content_hash(TABLES)
    assert fork.cfg.run.label == "fire fork"


def test_fork_refuses_missing_snapshots_and_the_cli_creates_forks(tmp_path, capsys):
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T09:10:00")
    save_config(sim.cfg, tmp_path / "run")
    sim.run()
    sim.close()
    try:
        fork_run(tmp_path / "run", "nope", tmp_path / "x")
        raise AssertionError("missing snapshot accepted")
    except FileNotFoundError:
        pass
    code = main(
        [
            "fork",
            "--run-dir",
            str(tmp_path / "run"),
            "--snapshot",
            "final",
            "--out",
            str(tmp_path / "cli-fork"),
            "--set",
            "run.label=cf",
            "--run",
            "--max-steps",
            "6",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "forked run at snapshot final" in out and (tmp_path / "cli-fork" / "manifest.json").exists()
