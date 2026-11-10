"""The research viewer's read-only API as one function: a path and its query in, plain data out.

``viewer/app.py`` serves the same data over HTTP. A town that runs inside a browser tab has no
HTTP server, so its inspector asks through ``dispatch`` instead (``game/tab.py``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote

from .data import RunData


class NotFound(KeyError):
    """No such path, or the data layer does not have what was asked for."""


def _int(q: dict[str, str], key: str, default: int | None) -> int | None:
    return int(q[key]) if q.get(key) not in (None, "") else default


def dispatch(data: RunData, path: str) -> Any:
    """Answer ``path`` (for example ``agent/klaus_mueller/memories?kind=reflection``)."""

    route, _, query = path.partition("?")
    q = {k: v[-1] for k, v in parse_qs(query).items()}
    parts = [unquote(p) for p in route.strip("/").split("/") if p]
    try:
        match parts:
            case ["run"]:
                info = data.run_info()
                info["has_evaluation"] = (data.run_dir / "exports" / "evaluation" / "summary.json").exists()
                info["has_experiment"] = False
                return info
            case ["map"]:
                return data.map_payload()
            case ["frames"]:
                return data.frames(_int(q, "start", -1), int(q["end"]))
            case ["timeline"]:
                return data.timeline(q.get("day"))
            case ["agent", aid]:
                return data.agent(aid, _int(q, "step", None))
            case ["agent", aid, "memories"]:
                return data.memories(aid, kind=q.get("kind"), text=q.get("q"), limit=min(_int(q, "limit", 60), 500), before=q.get("before"))
            case ["agent", aid, "traces"]:
                return data.traces(aid, min(_int(q, "limit", 40), 200), q.get("before"))
            case ["agent", aid, "reflections"]:
                return data.reflections(aid)
            case ["agent", aid, "decisions"]:
                return data.decisions(aid, day=q.get("day"), limit=min(_int(q, "limit", 200), 1000), before=q.get("before"))
            case ["trace", tid]:
                return data.trace(tid)
            case ["evidence", mid]:
                return data.evidence(mid)
            case ["conversations"]:
                return data.conversations(q.get("agent"))
            case ["conversation", cid]:
                return data.conversation(cid)
            case ["events"]:
                return data.events(q.get("type"), q.get("agent"), min(_int(q, "limit", 200), 2000), _int(q, "after", 0))
            case ["manifest"]:
                return data.manifest()
            case ["calls"]:
                return data.calls(task=q.get("task"), agent=q.get("agent"), limit=min(_int(q, "limit", 100), 500), before=_int(q, "before", None))
            case ["call", call_id]:
                return data.call(int(call_id))
            case ["diffusion"]:
                return data.diffusion()
            case ["evaluation"]:
                return data.evaluation() or {}
            case ["interviews"]:
                return data.interviews()
            case ["relationships"]:
                return data.relationships(q.get("agent"))
            case ["network"]:
                return data.network(q.get("at"), points=min(_int(q, "points", 24), 96))
            case ["behavior"]:
                return data.behavior()
            case ["beliefs"]:
                return data.beliefs()
            case ["metrics"]:
                return data.metrics()
            case ["experiment"]:
                return {}
    except KeyError as exc:
        raise NotFound(str(exc)) from exc
    raise NotFound(path)
