"""Convert pydantic output models into strict JSON schemas accepted by structured-output APIs.

Structured outputs require ``additionalProperties: false`` on every object and do not support
numeric or string-length constraints; those are validated client-side by the pydantic model.

Local servers (Ollama, llama.cpp's server, LM Studio) enforce the schema differently: they turn
it into a grammar and decode within it, and that grammar can also carry an enum of offered
choices, an item count or a numeric range. ``decoding_schema`` builds such a tighter copy for
one call (see ``LLMGateway.run(constraints=...)``). It only ever repeats rules the call's own
validator already enforces, so it removes answers that would be rejected anyway and never one
that would be accepted.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "default",
    "title",
}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = copy.deepcopy(model.model_json_schema())
    return _strictify(schema)


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _strictify(v) for k, v in node.items() if k not in _UNSUPPORTED}
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties", {})
            out["type"] = "object"
            out["additionalProperties"] = False
            out["required"] = list(props.keys())
        return out
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with local ``$ref``s to ``$defs`` expanded in place.

    Grammar-constrained decoders in local servers handle plain nested objects more reliably
    than references, and the expanded schema is equivalent.
    """

    defs = schema.get("$defs", {})

    def expand(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise ValueError("schema nesting too deep to inline")
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = defs[ref.split("/")[-1]]
                merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
                return expand(merged, depth + 1)
            return {k: expand(v, depth + 1) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [expand(v, depth + 1) for v in node]
        return node

    return expand(schema)


def decoding_schema(schema: dict[str, Any], constraints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A copy of ``schema`` (references inlined) with ``constraints`` merged into its fields.

    Keys are field paths: ``"rating"`` is a top-level property and ``"ratings.*.id"`` the
    ``id`` of every item of the ``ratings`` array (``*`` steps into array items). Values are
    JSON-schema keywords such as ``enum``, ``minimum``/``maximum``, ``minItems``/``maxItems``,
    ``minLength`` or ``pattern``. For an optional field (``anyOf`` with ``null``) they apply to
    the non-null branch. A path that matches nothing raises ``KeyError``: a misspelt path would
    otherwise silently constrain nothing.
    """

    out = inline_refs(schema)
    for path, keywords in constraints.items():
        nodes = [out]
        for part in path.split("."):
            nodes = [child for node in nodes for branch in _branches(node) for child in _children(branch, part)]
        if not nodes:
            raise KeyError(f"constraint path {path!r} matches no field of the schema")
        for node in nodes:
            for branch in _branches(node):
                branch.update(copy.deepcopy(keywords))
    return out


def _branches(node: dict[str, Any]) -> list[dict[str, Any]]:
    if "anyOf" in node:
        return [b for b in node["anyOf"] if isinstance(b, dict) and b.get("type") != "null"]
    return [node]


def _children(node: dict[str, Any], part: str) -> list[dict[str, Any]]:
    if part == "*":
        items = node.get("items")
        return [items] if isinstance(items, dict) else []
    child = node.get("properties", {}).get(part)
    return [child] if isinstance(child, dict) else []
