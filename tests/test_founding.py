"""Founding a town of your own (src/generative_agents/founding.py and `ga town`): the cast, the
name, residents you wrote, and settings that fit the machine instead of fixed presets."""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from fake_ollama import FakeOllama
from generative_agents import cli, founding, town
from generative_agents.config import GAConfig, apply_overrides, load_config
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.scenario.audit import audit_scenario
from generative_agents.scenario.loader import load_scenario
from generative_agents.simulation.engine import Simulation

CARDS = [
    {
        "name": "Rosa Delgado",
        "age": 38,
        "about": "a baker who sells her bread at Hobbs Cafe",
        "works_at": "Hobbs Cafe",
        "lives_with": "Marco Delgado",
        "knows": ["Isabella Rodriguez owns Hobbs Cafe"],
    },
    {"name": "Marco Delgado", "about": "Rosa Delgado's son, who draws maps of the town"},
    {"name": "June Okonkwo", "age": 67, "traits": "patient, sharp", "about": "June Okonkwo is a retired ferry captain.", "day": "plays chess in Johnson Park"},
]


def write_cards(tmp_path, cards=CARDS):
    path = tmp_path / "residents.yaml"
    path.write_text(yaml.safe_dump(cards))
    return path


# ---------------------------------------------------------------------------------- the cast
def test_the_cast_is_a_choice_the_default_ten_first_then_named_or_random():
    everyone = [p["id"] for p in founding.premade()]
    assert len(everyone) == 25 and set(founding.DEFAULT_TEN) <= set(everyone)
    assert set(founding.choose_cast(10)) == set(founding.DEFAULT_TEN)
    assert set(founding.choose_cast(3)) == set(founding.DEFAULT_TEN[:3]) and len(founding.choose_cast(25)) == 25
    assert founding.choose_cast(0, "Klaus, isabella_rodriguez, Maria Lopez") == ["isabella_rodriguez", "klaus_mueller", "maria_lopez"]
    drawn = founding.choose_cast(6, "random", seed=3)
    assert len(drawn) == 6 and drawn == founding.choose_cast(6, "random", seed=3) and drawn != founding.choose_cast(6, "random", seed=4)
    assert founding.choose_cast(10, "none") == []
    with pytest.raises(founding.FoundingError, match="list-cast"):
        founding.choose_cast(1, "Nobody Here")
    with pytest.raises(founding.FoundingError, match="between 0 and 25"):
        founding.choose_cast(40)


# ------------------------------------------------------------------------- your own residents
def test_cards_become_residents_with_houses_and_the_town_is_a_valid_scenario(tmp_path):
    report = founding.build_scenario(founding.load_cards(write_cards(tmp_path)), tmp_path / "scenario", "Willow Creek")
    assert report["houses"] == ["Delgado family's house", "June Okonkwo's house"]
    sc = load_scenario(founding.scenario_path(tmp_path), population=["isabella_rodriguez", *report["newcomers"]])
    assert audit_scenario(sc)["ok"]
    rosa, marco, june = (sc.agents[a].identity for a in ("rosa_delgado", "marco_delgado", "june_okonkwo"))
    assert rosa.learned == "Rosa Delgado is a baker who sells her bread at Hobbs Cafe"  # the name is put in front
    assert marco.learned == "Marco Delgado is Rosa Delgado's son, who draws maps of the town"
    assert june.learned == "June Okonkwo is a retired ferry captain." and june.daily_plan_req == "June Okonkwo plays chess in Johnson Park"
    assert june.age == 67 and marco.age == 30 and "goes to bed around 11pm" in marco.lifestyle
    assert rosa.living_area == "the Ville:Delgado family's house:Rosa's bedroom" and marco.living_area.endswith("Marco's bedroom")
    assert june.living_area == "the Ville:June Okonkwo's house:main room"
    seeds = [s["text"] for s in yaml.safe_load((tmp_path / "scenario" / "town" / "agents" / "rosa_delgado.yaml").read_text())["seeds"]]
    assert "Isabella Rodriguez owns Hobbs Cafe" in seeds and "Marco Delgado lives with you in Delgado family's house" in seeds
    constraints = yaml.safe_load((tmp_path / "scenario" / "town" / "constraints.yaml").read_text())
    assert "rosa_delgado" in constraints["opening_hours"]["the Ville:Hobbs Cafe"]["staff"]


def test_a_founded_town_runs_and_keeps_running_after_its_folder_is_moved(tmp_path):
    report = founding.build_scenario(founding.load_cards(write_cards(tmp_path)), tmp_path / "a" / "scenario", "Willow Creek")
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))  # nothing in the scenario points outside its folder
    cast = ["isabella_rodriguez", "klaus_mueller", *report["newcomers"]]
    cfg = GAConfig.model_validate(
        apply_overrides(
            {},
            [
                f"scenario.path={json.dumps(str(founding.scenario_path(tmp_path / 'b')))}",
                f"scenario.population=[{', '.join(cast)}]",
                "scenario.start=2023-02-13T06:00:00",
                "scenario.end=2023-02-13T07:30:00",
                "game.enabled=true",
            ],
        )
    )
    sim = Simulation(cfg, tmp_path / "b" / "run", embedding_provider=MockHashEmbedding(128))
    assert sim.run() == "completed" and set(sim.order) == set(cast)
    for aid in report["newcomers"]:
        assert sim.db.one("SELECT COUNT(*) AS n FROM memories WHERE owner_id=?", (aid,))["n"] > 5
        assert sim.db.one("SELECT COUNT(*) AS n FROM plans WHERE agent_id=?", (aid,))["n"] > 0


def test_cards_that_cannot_work_say_what_to_change(tmp_path):
    def refuse(cards, match):
        with pytest.raises(founding.FoundingError, match=match):
            founding.build_scenario(founding.load_cards(write_cards(tmp_path, cards)), tmp_path / "s", "T")

    refuse([{"name": "Cher", "about": "a singer"}], "first and a last name")
    refuse([{"name": "Ada Byron"}], "add `about`")
    refuse([{"name": "Ada Byron", "about": "x", "job": "poet"}], "unknown field")
    refuse([{"name": "Ada Byron", "about": "x", "lives_with": "Someone Else"}], "not another resident")
    refuse([{"name": "Klaus Mueller", "about": "a namesake"}], "already used")
    refuse([{"name": "Ada Byron", "about": "is planning a Valentine's Day party"}], "party or election")
    refuse([{"name": "Ada Byron", "about": "a poet", "works_at": "Johnson Park"}], "opening hours")
    refuse([{"name": f"Person {chr(65 + i)}son", "about": "a neighbour"} for i in range(7)], "all taken")
    four = [{"name": f"{n} Quartet", "about": "a musician", **({"lives_with": "Ann Quartet"} if n != "Ann" else {})} for n in ("Ann", "Ben", "Cy", "Di")]
    refuse(four, "at most three")


# --------------------------------------------------------------------- fitted to the machine
def test_the_model_plan_follows_the_machines_memory_unless_you_say_otherwise(tmp_path):
    small = town.plan_town(memory_gb=8.0, run_dir=str(tmp_path / "small"))
    assert small.cfg.providers.llm.model == "llama3.2:3b" and "8 GB" in small.notes[0]
    assert town.needed_models(small.cfg) == {"http://localhost:11434": ["llama3.2:3b", "nomic-embed-text"]}  # no 8B download
    big = town.plan_town(memory_gb=32.0, run_dir=str(tmp_path / "big"))
    assert big.cfg.providers.llm.model == "llama3.1:8b" and big.sets == []
    said = town.plan_town(memory_gb=8.0, models="qwen3:14b,qwen3:4b", run_dir=str(tmp_path / "said"))
    assert said.cfg.providers.llm.model == "qwen3:14b" and {o["model"] for o in said.cfg.providers.llm.task_overrides.values()} == {"qwen3:4b"}
    # a model server on another machine: this machine's memory says nothing about it
    remote = town.plan_town(memory_gb=8.0, url="http://gpu-box:11434", run_dir=str(tmp_path / "remote"))
    assert remote.cfg.providers.llm.model == "llama3.1:8b"
    assert town.plan_models(load_config("configs/town_mock.yaml"), memory_gb=4.0) == ([], None)
    assert (town.machine_memory_gb() or 1) > 0.1


def test_the_parallel_setting_is_measured_on_the_server_not_assumed(tmp_path):
    with FakeOllama(models=("llama3.1:8b", "llama3.2:3b", "nomic-embed-text")) as server:
        server.delay = 0.05
        cfg = town.plan_town(memory_gb=32.0, url=server.url, run_dir=str(tmp_path / "t")).cfg
        probe = town.probe_parallel(cfg, say=lambda s: None)
        assert probe["model"] == "llama3.2:3b" and probe["gain"] > 2.5 and probe["parallel_calls"] == 4
        server.serial = True  # the same server with a single slot
        assert town.probe_parallel(cfg, say=lambda s: None)["parallel_calls"] == 1
    said: list[str] = []
    assert town.probe_parallel(cfg, say=said.append) is None and "could not measure" in said[0]  # the server is gone


# ------------------------------------------------------------------------------- ga town
def test_ga_town_founds_a_named_town_with_your_residents_and_continues_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    args = ["town", "--config", "configs/town_mock.yaml", "--name", "Willow Creek", "--residents", "3", "--newcomers", str(write_cards(tmp_path))]
    args += ["--run-dir", str(tmp_path / "wc"), "--no-open", "--speed", "live"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "moved in: Rosa Delgado, Marco Delgado, June Okonkwo" in out and "founding the town" in out and "(6 residents)" in out
    saved = yaml.safe_load((tmp_path / "wc" / "config.yaml").read_text())
    assert saved["game"]["town_name"] == "Willow Creek" and saved["run"]["name"] == "willow-creek" and len(saved["scenario"]["population"]) == 6
    assert json.loads((tmp_path / "wc" / "manifest.json").read_text())["scenario"]["name"] == "willow_creek"
    shutil.move(str(tmp_path / "wc"), str(tmp_path / "moved"))
    again = ["town", "--run-dir", str(tmp_path / "moved"), "--no-open", "--cast", "random"]
    assert cli.main(again) == 0
    out = capsys.readouterr().out
    assert "continuing the town" in out and "only apply when a town is founded" in out and "(6 residents)" in out


def test_ga_town_lists_the_cast_and_explains_a_card_it_cannot_use(tmp_path, capsys):
    assert cli.main(["town", "--list-cast"]) == 0
    listed = capsys.readouterr().out
    assert "isabella_rodriguez" in listed and listed.count("\n") >= 26 and "residents_example.yaml" in listed
    bad = write_cards(tmp_path, [{"name": "Ada Byron", "about": "wants to become mayor"}])
    assert cli.main(["town", "--config", "configs/town_mock.yaml", "--newcomers", str(bad), "--run-dir", str(tmp_path / "x"), "--no-open"]) == 2
    assert "cannot found this town" in capsys.readouterr().out and not (tmp_path / "x" / "state.sqlite").exists()
    assert founding.load_cards("configs/residents_example.yaml")[0]["name"] == "Rosa Delgado"


def test_the_live_pace_is_real_time_and_the_town_tells_the_interface_its_name(tmp_path):
    from generative_agents.game.api import town_info
    from generative_agents.game.session import SPEEDS, GameSession

    assert SPEEDS["live"] < 0 and list(SPEEDS)[0] == "live"
    cfg = load_config("configs/town_mock.yaml", overrides=['game.town_name="Willow Creek"'])
    session = GameSession(cfg, tmp_path / "t", speed="live", paused=True)
    try:
        info = town_info(session)
        assert info["town_name"] == "Willow Creek" and "live" in info["speeds"] and session.speed == "live"
    finally:
        session.sim.close()
