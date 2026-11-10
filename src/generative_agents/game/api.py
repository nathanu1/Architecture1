"""HTTP interface of a live (or replayed) game session: ``ga play``.

The town page polls ``/api/game/poll`` a few times a second and sends player actions to
``/api/game/action``. Build checks run against the session's last published snapshot. The
research inspector reads the same run through the read-only viewer API mounted at
``/research/api``; nothing it shows is ever sent to residents.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..db import Database
from ..viewer.app import create_app as create_viewer_app
from .payloads import object_info, resident_detail, town_info, town_map
from .session import GameSession

WEB = Path(__file__).parent / "web"


class ActionIn(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BuildIn(BaseModel):
    ops: list[dict[str, Any]]


class ControlIn(BaseModel):
    action: str
    speed: str | None = None


def create_game_app(session: GameSession, *, web_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Hearthside town", docs_url=None, redoc_url=None)
    sim = session.sim
    world = sim.world
    reader = Database(sim.run_dir / "state.sqlite", read_only=True)
    reader_lock = threading.Lock()

    def rows(sql: str, params: tuple = ()) -> list[Any]:
        with reader_lock:
            return reader.query(sql, params)

    info_payload = town_info(session)
    map_payload = town_map(session, placed={json.loads(r["json"]).get("address") for r in rows("SELECT json FROM game_items ORDER BY seq")})

    # ------------------------------------------------------------------ game endpoints
    @app.get("/api/game/info")
    def info() -> dict[str, Any]:
        return info_payload

    @app.get("/api/game/map")
    def map_() -> JSONResponse:
        return JSONResponse(map_payload, headers={"Cache-Control": "max-age=600"})

    @app.get("/api/game/poll")
    def poll(since_step: int = Query(-2), since_feed: int = Query(0)) -> dict[str, Any]:
        return session.poll(since_step, since_feed)

    @app.post("/api/game/action")
    def action(body: ActionIn) -> dict[str, Any]:
        try:
            return session.submit(body.kind, body.payload)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/game/validate-build")
    def validate_build(body: BuildIn) -> dict[str, Any]:
        try:
            return session.validate_build(body.ops)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, f"bad build request: {exc}") from exc

    @app.post("/api/game/control")
    def control(body: ControlIn) -> dict[str, Any]:
        try:
            return session.control(body.action, body.speed)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/game/resident/{aid}")
    def resident(aid: str) -> dict[str, Any]:
        try:
            return resident_detail(session, aid, rows)
        except KeyError as exc:
            raise HTTPException(404, f"no resident {aid}") from exc

    @app.get("/api/game/object")
    def object_route(address: str) -> dict[str, Any]:
        if not world.exists(address):
            raise HTTPException(404, "unknown object")
        return object_info(session, address)

    # ------------------------------------------------------------------ research inspector data (read-only)
    app.mount("/research", create_viewer_app(sim.run_dir))

    # ------------------------------------------------------------------ the built interface
    web = web_dir or WEB
    if (web / "index.html").exists():
        if (web / "assets").exists():
            app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            target = (web / path).resolve()
            if path and target.is_file() and web.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(web / "index.html")
    else:

        @app.get("/")
        def missing() -> JSONResponse:
            return JSONResponse(
                {"error": "the town interface is not built; run `npm install && npm run build` in frontend/"},
                status_code=503,
            )

    return app
