"""`ga town` and `ga bench`: the living town on a local model as one command (src/generative_agents/town.py)."""

from __future__ import annotations

import json

import pytest

from fake_ollama import FakeOllama
from generative_agents import cli, town
from generative_agents.config import load_config
from generative_agents.providers.base import ProviderError
from generative_agents.providers.ollama_provider import ollama_pull

LIVE_MODELS = ["llama3.1:8b", "llama3.2:3b", "nomic-embed-text"]


def test_the_live_town_needs_two_chat_models_and_an_embedding_model_on_one_server():
    cfg = load_config("configs/town_live.yaml")
    assert town.needed_models(cfg) == {"http://localhost:11434": LIVE_MODELS}
    assert town.needed_models(load_config("configs/town_mock.yaml")) == {}


def test_one_address_moves_every_local_endpoint_to_another_machine():
    cfg, sets = town.load_town_config(None, 10, [], "http://gpu-box:11434/")
    assert sets == ["providers.llm.base_url=http://gpu-box:11434", "providers.embeddings.base_url=http://gpu-box:11434"]
    assert town.needed_models(cfg) == {"http://gpu-box:11434": LIVE_MODELS}
    assert len(cfg.scenario.population) == 10
    big, _ = town.load_town_config(None, 25, [], None)
    assert big.scenario.population is None and big.run.name == "town-live-25"
    assert town.server_overrides(load_config("configs/town_mock.yaml"), "http://x:1") == []  # nothing to move on the mock


def test_missing_models_are_downloaded_once_and_a_refused_one_stops_the_town():
    said: list[str] = []
    with FakeOllama(models=("llama3.1:8b",)) as server:
        cfg, _ = town.load_town_config(None, 10, [], server.url)
        assert town.prepare_models(cfg, say=said.append)
        assert set(server.models) >= set(LIVE_MODELS)
        assert [b["model"] for p, b in server.requests if p == "/api/pull"] == ["llama3.2:3b", "nomic-embed-text"]
        assert any("llama3.1:8b: ready" in line for line in said) and any("downloading" in line for line in said)
        before = len([1 for p, _ in server.requests if p == "/api/pull"])
        assert town.prepare_models(cfg, say=said.append)  # nothing left to fetch
        assert len([1 for p, _ in server.requests if p == "/api/pull"]) == before
    with FakeOllama(models=()) as server:
        cfg, _ = town.load_town_config(None, 10, [], server.url)
        said.clear()
        assert not town.prepare_models(cfg, pull=False, say=said.append)
        assert any("ollama pull llama3.1:8b" in line for line in said)
        server.unknown.add("llama3.2:3b")
        assert not town.prepare_models(cfg, say=said.append)
        with pytest.raises(ProviderError, match="could not pull"):
            ollama_pull(server.url, "llama3.2:3b")


def test_an_absent_model_server_says_what_to_do_instead_of_failing_later():
    said: list[str] = []
    cfg, _ = town.load_town_config(None, 10, [], "http://127.0.0.1:9")
    assert not town.prepare_models(cfg, say=said.append)
    assert "no model server at http://127.0.0.1:9" in said[0] and "ollama.com/download" in said[1]
    remote, _ = town.load_town_config(None, 10, [], "http://192.0.2.1:11434")  # TEST-NET: never routable
    said.clear()
    from generative_agents.providers import ollama_provider

    real = ollama_provider.ollama_status
    try:
        ollama_provider.ollama_status = lambda url, models, **kw: {"base_url": url, "reachable": False, "version": None, "present": {}, "error": "x"}
        assert not town.prepare_models(remote, say=said.append)
    finally:
        ollama_provider.ollama_status = real
    assert town.ENV_URL in said[1]


def test_the_town_opens_as_its_own_window_when_a_chromium_browser_exists(monkeypatch):
    assert town.find_app_browser(("definitely-not-a-browser",)) is None
    launched: list[list[str]] = []
    monkeypatch.setattr(town, "find_app_browser", lambda: "/usr/bin/chromium")
    assert "app window" in town.open_window("http://127.0.0.1:8080", app=True, launch=lambda cmd, **kw: launched.append(cmd))
    assert launched == [["/usr/bin/chromium", "--app=http://127.0.0.1:8080", "--window-size=1440,900"]]
    opened: list[str] = []
    monkeypatch.setattr(town, "find_app_browser", lambda: None)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    assert "browser" in town.open_window("http://127.0.0.1:8080", app=True)
    assert opened == ["http://127.0.0.1:8080"]


def test_bench_measures_the_real_workload_and_projects_both_town_sizes():
    said: list[str] = []
    out = town.bench(load_config("configs/town_mock.yaml"), minutes=20, residents=3, parallel=4, say=said.append)
    assert out["calls"] > 20 and out["status"] == "completed" and set(out["towns"]) == {10, 25}
    for n in (10, 25):
        t = out["towns"][n]
        assert t["parallel_hours_per_game_day"] <= t["sequential_hours_per_game_day"] and 1.0 <= t["gain_used"] <= town.SCHEDULE_GAIN[n]
    assert any("choose_location" in line for line in said) and any("25 residents" in line for line in said)
    # the task mix the projection uses names real prompt templates only
    from generative_agents.prompting import PromptRegistry

    assert set(town.CALLS_PER_RESIDENT_DAY) <= set(PromptRegistry().tasks())


def test_ga_town_founds_a_town_once_and_continues_it_afterwards(tmp_path, monkeypatch, capsys):
    served: list[str] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: served.append(f"{kw['host']}:{kw['port']}"))
    args = ["town", "--config", "configs/town_mock.yaml", "--run-dir", str(tmp_path / "t"), "--no-open", "--port", "8123", "--parallel", "4", "--speed", "max"]
    assert cli.main(args) == 0
    first = capsys.readouterr().out
    assert "founding the town" in first and served == ["127.0.0.1:8123"]
    assert (tmp_path / "t" / "state.sqlite").exists()
    manifest = json.loads((tmp_path / "t" / "manifest.json").read_text())
    assert manifest["parallel"]["calls"] == 4
    assert cli.main(args) == 0
    assert "continuing the town" in capsys.readouterr().out and len(served) == 2


def test_ga_town_refuses_a_paid_api_unless_told_and_ga_bench_runs_from_the_cli(tmp_path, capsys):
    assert cli.main(["town", "--config", "configs/town_llama_api.yaml", "--run-dir", str(tmp_path / "x"), "--no-open"]) == 2
    assert "not a local model" in capsys.readouterr().out
    assert cli.main(["bench", "--config", "configs/town_mock.yaml", "--minutes", "10", "--parallel", "1", "--json"]) == 0
    printed = capsys.readouterr().out
    assert '"towns"' in printed and "one call at a time" in printed
