"""Deployment pieces: hosted OpenAI-compatible APIs (response_format) and the optional password gate."""

from __future__ import annotations

import base64
import threading
from http.server import ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from generative_agents.config import GAConfig, apply_overrides, load_config
from generative_agents.providers.openai_compatible import OpenAICompatibleProvider
from generative_agents.simulation.runtime import build_llm_provider
from generative_agents.webauth import ENV_VAR, SPECTATORS_VAR, password_from_env, require_password, spectators_from_env
from test_local_providers import _OpenAIish, gateway, variables


@pytest.fixture
def openai_like():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIish)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _OpenAIish.seen.clear()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    finally:
        srv.shutdown()
        srv.server_close()
        _OpenAIish.seen.clear()  # the list is shared with test_local_providers


def test_response_format_follows_the_provider_setting(openai_like):
    for mode, expected in (("json_object", {"type": "json_object"}), ("none", None), ("json_schema", "schema")):
        _OpenAIish.seen.clear()
        gw = gateway(OpenAICompatibleProvider("llama-3.3-70b", base_url=openai_like, seed=3, response_format=mode))
        assert gw.run("importance", variables("importance"), agent_id="a").output.rating == 3
        body = _OpenAIish.seen[0][1]
        if expected is None:
            assert "response_format" not in body
        elif expected == "schema":
            assert body["response_format"]["type"] == "json_schema"
        else:
            assert body["response_format"] == expected
        assert gw.provider.describe()["response_format"] == mode
    with pytest.raises(ValueError):
        OpenAICompatibleProvider("m", base_url=openai_like, response_format="yaml")


def test_config_passes_response_format_and_hosted_apis_are_not_local():
    cfg = GAConfig.model_validate(
        apply_overrides(
            {},
            [
                "providers.llm.kind=openai_compatible",
                "providers.llm.base_url=https://api.example.com/v1",
                "providers.llm.model=llama",
                "providers.llm.response_format=json_object",
                "providers.llm.api_key_env=LLAMA_API_KEY",
            ],
        )
    )
    prov = build_llm_provider(cfg)
    assert prov.response_format == "json_object" and not cfg.providers.llm.is_local() and cfg.run_mode == "live"


def test_server_configs_route_mechanical_tasks_to_the_small_model():
    cfg = load_config("configs/town_n25_server.yaml")
    assert cfg.game.enabled and cfg.providers.llm.kind == "ollama" and cfg.scenario.population is None
    small = {t: o["model"] for t, o in cfg.providers.llm.task_overrides.items()}
    assert {"choose_location", "importance", "importance_batch", "action_grounding"} <= set(small)
    assert all(m != cfg.providers.llm.model for m in small.values())
    api = load_config("configs/town_llama_api.yaml")
    assert api.providers.llm.kind == "openai_compatible" and api.providers.llm.response_format == "json_object" and not api.providers.llm.is_local()


def test_password_gate_requires_http_basic_credentials(monkeypatch):
    app = FastAPI()

    @app.get("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/x")
    def post_x() -> dict[str, bool]:
        return {"ok": True}

    require_password(app, "s3cret")
    c = TestClient(app)
    assert c.get("/x").status_code == 401 and c.get("/x").headers["www-authenticate"].startswith("Basic")
    wrong = base64.b64encode(b"anyone:nope").decode()
    assert c.get("/x", headers={"Authorization": f"Basic {wrong}"}).status_code == 401
    right = base64.b64encode(b"anyone:s3cret").decode()
    assert c.get("/x", headers={"Authorization": f"Basic {right}"}).json() == {"ok": True}
    assert c.get("/x", auth=("researcher", "s3cret")).status_code == 200
    # spectators: reads are open, writes still need the password
    public = FastAPI()

    @public.get("/y")
    def y() -> dict[str, bool]:
        return {"ok": True}

    @public.post("/y")
    def post_y() -> dict[str, bool]:
        return {"ok": True}

    require_password(public, "s3cret", spectators=True)
    s = TestClient(public)
    assert s.get("/y").status_code == 200 and s.post("/y").status_code == 401 and s.post("/y", auth=("a", "s3cret")).status_code == 200
    monkeypatch.setenv(ENV_VAR, "  ")
    assert password_from_env() is None
    monkeypatch.setenv(ENV_VAR, "pw")
    monkeypatch.setenv(SPECTATORS_VAR, "1")
    assert password_from_env() == "pw" and spectators_from_env()
