"""Counterfactual forks: a new run that starts from a snapshot of another run (research extension).

A fork copies a committed snapshot (``snapshots/<name>.sqlite``) into a new run directory
and lets the simulation continue from that exact state under a different configuration
and/or with interventions scheduled after the fork point. Two forks of the same snapshot
share every memory, plan, relationship and position up to that moment, so differences in
what follows can only come from what was changed, from the model's sampling, or from the
run seed. The manifest of a fork records its origin (``forked_from``).

The fork gets a fresh provider ledger under its own run id: nothing after the fork point is
served from the source's recorded responses. With the offline mock, a fork that changes
nothing reproduces the source run's own continuation exactly (tested), which is the baseline
every counterfactual is compared against.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import GAConfig, apply_overrides
from ..db import Database


def fork_run(
    source_dir: str | Path,
    snapshot: str,
    out_dir: str | Path,
    *,
    overrides: list[str] | None = None,
    interventions: list[dict[str, Any]] | str | Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Create the fork's directory, state database, config and interventions. Does not run it."""

    source_dir = Path(source_dir)
    out_dir = Path(out_dir)
    snap_path = Path(snapshot) if str(snapshot).endswith(".sqlite") else source_dir / "snapshots" / f"{snapshot}.sqlite"
    if not snap_path.exists():
        raise FileNotFoundError(f"snapshot not found: {snap_path}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"fork directory {out_dir} already exists")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (source_dir / "config.yaml").exists():
        raise FileNotFoundError(f"{source_dir} has no config.yaml; forks need the source run's configuration")
    raw = yaml.safe_load((source_dir / "config.yaml").read_text())
    cfg = GAConfig.model_validate(apply_overrides(raw, overrides))
    if label:
        cfg.run.label = label
    source_manifest = json.loads((source_dir / "manifest.json").read_text()) if (source_dir / "manifest.json").exists() else {}
    shutil.copy(snap_path, out_dir / "state.sqlite")
    db = Database(out_dir / "state.sqlite")
    try:
        info = db.get_meta("snapshot") or {}
        origin = {
            "run_id": info.get("run_id") or source_manifest.get("run_id") or source_dir.name,
            "source_dir": str(source_dir),
            "snapshot": info.get("name") or snap_path.stem,
            "step": info.get("step", db.get_meta("next_step")),
            "sim_time": info.get("sim_time") or db.get_meta("sim_time"),
            "overrides": list(overrides or []),
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        db.set_meta("run_id", out_dir.name)
        db.set_meta("status", "created")
        db.set_meta("stop_detail", None)
        db.set_meta("snapshots", {})
        db.set_meta("snapshot", None)
        db.set_meta("interventions_applied", [])
        db.set_meta("budget", None)
        db.set_meta("forked_from", origin)
        db.set_meta("mode", cfg.run_mode)
        db.commit()
    finally:
        db.close()
    (out_dir / "config.yaml").write_text(yaml.safe_dump(json.loads(cfg.model_dump_json()), sort_keys=False, allow_unicode=True))
    if interventions is not None:
        items = interventions if isinstance(interventions, list) else (yaml.safe_load(Path(interventions).read_text()) or {})
        if isinstance(items, dict):
            items = items.get("interventions", [])
        (out_dir / "interventions.yaml").write_text(yaml.safe_dump({"interventions": items}, sort_keys=False, allow_unicode=True))
    return origin
