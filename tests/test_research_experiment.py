"""Generalized experiment protocols (research extension): named metrics, forks, interventions, determinism check."""

from __future__ import annotations

import json

import yaml

from generative_agents.evaluation.experiment import Protocol, execute, outcome_keys, summarize
from generative_agents.evaluation.metrics import REGISTRY, MetricContext, run_metrics
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.mock import MockLLM
from generative_agents.simulation.engine import Simulation, save_config
from helpers import sim_config

PAIR = ["isabella_rodriguez", "klaus_mueller"]


def base_config(tmp_path, **scenario):
    b = tmp_path / "base.yaml"
    b.write_text(
        yaml.safe_dump(
            {
                "scenario": {
                    "path": "scenarios/pilot5/scenario.yaml",
                    "population": PAIR,
                    "start": "2023-02-13T09:00:00",
                    "end": "2023-02-13T09:30:00",
                    **scenario,
                },
                "output": {"checkpoint_every_steps": 30},
                "providers": {"embeddings": {"kind": "mock-hash", "dims": 128}},
            }
        )
    )
    return b


def test_every_registered_metric_runs_on_a_finished_run(tmp_path):
    cfg = sim_config(PAIR, end="2023-02-13T09:30:00")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    save_config(cfg, run_dir)
    sim = Simulation(cfg, run_dir, provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    assert sim.run() == "completed"
    sim.close()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    ctx = MetricContext(run_dir, cfg, manifest, provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    names = [n for n in REGISTRY if n != "adaptation"]
    values, failures = run_metrics(ctx, names)
    assert failures == [], failures
    for key in ("network_density", "plan_adherence", "memory_recall_at_k", "valentines_holders_pct", "tom_attribution_precision", "calls"):
        assert key in values, key
    for name in names:
        if name not in ("usage", "evaluation"):
            assert (run_dir / "exports" / "metrics" / f"{name}.json").exists(), name
    ctx.params = {"at": "2023-02-13T09:05:00", "keywords": ["fire"]}
    values, failures = run_metrics(ctx, ["adaptation"])
    assert failures == [] and values["adaptation_changed_share"] == 0.0
    _, bad = run_metrics(ctx, ["nope"])
    assert bad and "unknown metric" in bad[0]


def test_protocol_with_named_metrics_interventions_and_determinism_check(tmp_path):
    proto_path = tmp_path / "protocol.yaml"
    proto_path.write_text(
        yaml.safe_dump(
            {
                "name": "research",
                "base_config": str(base_config(tmp_path)),
                "question": "Does an hourly-only planner react differently to a fire?",
                "hypothesis": "No difference is expected with the mock.",
                "conditions": {"full": [], "hourly": ["planning.decompose=false"]},
                "interventions": {
                    "full": [
                        {
                            "kind": "ambient",
                            "at": "2023-02-13T09:05:00",
                            "id": "f",
                            "tile": [78, 19],
                            "subject": "fire",
                            "object": "burning",
                            "description": "a fire is burning in Hobbs Cafe",
                        }
                    ],
                    "hourly": [
                        {
                            "kind": "ambient",
                            "at": "2023-02-13T09:05:00",
                            "id": "f",
                            "tile": [78, 19],
                            "subject": "fire",
                            "object": "burning",
                            "description": "a fire is burning in Hobbs Cafe",
                        }
                    ],
                },
                "seeds": [1, 2],
                "metrics": ["behavior", "network", "adaptation"],
                "metric_params": {"adaptation": {"at": "2023-02-13T09:05:00", "keywords": ["fire", "burning"], "window_minutes": 30}},
                "primary_outcomes": ["adaptation_changed_share", "plan_adherence"],
                "determinism_check": True,
                "output_dir": str(tmp_path / "experiments"),
            }
        )
    )
    proto = Protocol.load(proto_path)
    assert proto.metrics == ["behavior", "network", "adaptation", "usage"] and proto.needs_model() == []
    res = execute(proto)
    rows = res["rows"]
    assert len(rows) == 4 and all(r["status"] == "completed" for r in rows), rows
    assert all("adaptation_changed_share" in r and "network_density" in r and "calls" in r for r in rows)
    assert all((tmp_path / "experiments" / "research" / r["run_id"] / "interventions.yaml").exists() for r in rows)
    summ = res["summary"]
    assert summ["determinism"]["identical"] is True and summ["primary"] == ["adaptation_changed_share", "plan_adherence"]
    assert "plan_adherence" in summ["outcomes"] and "network_density" in summ["outcomes"] and "run_id" not in summ["outcomes"]
    assert set(summ["comparisons"]) == {"adaptation_changed_share", "plan_adherence"}
    report = (tmp_path / "experiments" / "research" / "report.md").read_text()
    assert "**Hypothesis (fixed before running):**" in report and "Determinism check" in report and "**identical**" in report
    assert "## Conditions" in report and "`planning.decompose=false`" in report and "| **Agents who changed plans (share)** |" in report
    assert (tmp_path / "experiments" / "research" / "protocol.json").exists()


def test_fork_protocol_continues_every_run_from_the_same_snapshot(tmp_path):
    cfg = sim_config(PAIR, end="2023-02-13T09:40:00", extra=("output.snapshots=[initial, '2023-02-13T09:20:00', final]", "providers.embeddings.dims=128"))
    src = tmp_path / "src"
    src.mkdir()
    save_config(cfg, src)
    sim = Simulation(cfg, src, provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    sim.initialize()
    for aid in PAIR:
        sim.svc.states.get(aid).tile = (78, 20)
    sim.svc.states.flush()
    assert sim.run() == "completed"
    sim.close()
    proto = Protocol(
        name="cf",
        base_config="unused",
        conditions={"control": [], "fire": []},
        seeds=[7],
        metrics=["adaptation", "behavior", "usage"],
        metric_params={"adaptation": {"at": "2023-02-13T09:21:00", "keywords": ["fire", "burning"], "window_minutes": 20}},
        primary_outcomes=["adaptation_changed_share"],
        fork_from={"run_dir": str(src), "snapshot": "2023-02-13T09-20-00"},
        interventions={
            "fire": [
                {
                    "kind": "ambient",
                    "at": "2023-02-13T09:21:00",
                    "id": "f",
                    "tile": [78, 19],
                    "subject": "fire",
                    "object": "burning",
                    "description": "a fire is burning in Hobbs Cafe",
                }
            ]
        },
        output_dir=str(tmp_path / "experiments"),
    )
    res = execute(proto)
    by = {r["condition"]: r for r in res["rows"]}
    assert by["control"]["status"] == "completed" and by["fire"]["status"] == "completed", res["rows"]
    assert by["control"]["forked_from"] == "src@2023-02-13T09-20-00" and by["fire"]["forked_from"] == by["control"]["forked_from"]
    assert by["fire"]["adaptation_changed_share"] > by["control"]["adaptation_changed_share"] == 0.0
    report = (tmp_path / "experiments" / "cf" / "report.md").read_text()
    assert "Every run is a fork of" in report and "the same past, different futures" in report


def test_outcome_keys_and_summary_handle_missing_values():
    proto = Protocol(name="p", base_config="x", conditions={"a": [], "b": [], "c": []}, seeds=[1], primary_outcomes=["y"])
    rows = [
        {"run_id": "a1", "condition": "a", "status": "completed", "y": 0.5, "z": 3, "flag": True},
        {"run_id": "b1", "condition": "b", "status": "completed", "y": None, "z": 1},
        {"run_id": "c1", "condition": "c", "status": "error", "stop_detail": "boom"},
    ]
    assert outcome_keys(rows, proto) == ["y", "z"]
    s = summarize(rows, proto)
    assert s["conditions"]["b"]["outcomes"]["y"] == {"n": 0} and s["conditions"]["a"]["outcomes"]["z"]["mean"] == 3
    assert set(s["comparisons"]) == {"y (a vs b)", "y (a vs c)", "y (b vs c)"} and s["excluded"][0]["run_id"] == "c1"
