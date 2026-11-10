"""The living town on a local model, as one command (``ga town``) and one measurement (``ga bench``).

Three places run the same thing:

* **an app on your own computer**: ``ga town`` checks the model server, downloads missing models,
  continues the town where it stopped and opens it in a window;
* **a server** (a workstation, a lab machine, a mainframe partition): ``ga town --host 0.0.0.0``
  under systemd or Docker, with the model server on the same machine or another one
  (``HEARTHSIDE_LLM_URL``);
* **a site**: the same server behind HTTPS, with spectators on (docs/deploy.md).

The town process itself is plain Python and SQLite and has no hardware requirements. Everything
that needs a GPU or many cores is behind one HTTP address: the model server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import GAConfig, load_config

ENV_URL = "HEARTHSIDE_LLM_URL"
TOWN_CONFIGS = {10: "configs/town_live.yaml", 25: "configs/town_live_25.yaml"}
SERVER_KINDS = ("ollama", "openai_compatible")

# Model tasks per resident per game day with the live town's switches on (habits, memoized
# repeats, salience gate), from a recorded ten-resident day on the offline MOCK model
# (docs/deploy.md, "What a day costs"). A real model talks and reflects a different amount, so
# this is the shape of the load, not a promise; `ga bench` combines it with latencies measured
# on your own model server.
CALLS_PER_RESIDENT_DAY = {
    "choose_location": 70,
    "importance": 56,
    "action_grounding": 25,
    "interaction_context": 19,
    "summary_aspect": 18,
    "decompose": 15,
    "dialogue_turn": 15,
    "importance_batch": 8,
    "talk_decision": 7,
    "reflection_insights": 7,
    "replan": 7,
    "reaction": 7,
    "conversation_summary": 3,
    "reflection_questions": 2,
    "day_plan": 1,
    "hourly_schedule": 1,
}
# How many model calls a sequential engine waits for per wait of the round scheduler, over a
# whole recorded day (manifest "parallel": model_calls / model_waits, plus the conversation
# calls, which are a turn-by-turn chain and stay sequential). Within residents' turns alone the
# ratio is 2.4 (10 residents) and 2.7 (25 residents).
SCHEDULE_GAIN = {10: 2.0, 25: 2.1}


# ----------------------------------------------------------------------------- configuration
def server_overrides(cfg: GAConfig, url: str | None) -> list[str]:
    """``--set`` overrides that point every local model endpoint of ``cfg`` at ``url``."""

    if not url:
        return []
    url = url.rstrip("/")
    out = []
    if cfg.providers.llm.kind in SERVER_KINDS:
        out.append(f"providers.llm.base_url={url}")
    if cfg.providers.embeddings.kind in SERVER_KINDS:
        out.append(f"providers.embeddings.base_url={url}")
    return out


def needed_models(cfg: GAConfig) -> dict[str, list[str]]:
    """Ollama models the config uses, grouped by the server (base_url) they must be on."""

    from .providers.ollama_provider import DEFAULT_URL

    llm, emb = cfg.providers.llm, cfg.providers.embeddings
    by_server: dict[str, list[str]] = {}

    def add(url: str | None, model: str) -> None:
        models = by_server.setdefault((url or DEFAULT_URL).rstrip("/"), [])
        if model not in models:
            models.append(model)

    if llm.kind == "ollama":
        add(llm.base_url, llm.model)
        for override in llm.task_overrides.values():
            if override.get("model") and not override.get("provider"):
                add(llm.base_url, override["model"])
    for pool in llm.pools.values():
        if pool.kind == "ollama":
            add(pool.base_url, pool.model)
    if emb.kind == "ollama":
        add(emb.base_url, emb.model)
    return by_server


def prepare_models(cfg: GAConfig, *, pull: bool = True, say: Callable[[str], None] = print) -> bool:
    """Check that every model server answers and has its models; download what is missing.

    Returns False (after saying exactly what to do) when the town cannot start.
    """

    from .providers.base import ProviderError
    from .providers.local_http import JSONClient, is_local_url
    from .providers.ollama_provider import ollama_pull, ollama_status

    ok = True
    for url, models in needed_models(cfg).items():
        st = ollama_status(url, models)
        if not st["reachable"]:
            say(f"no model server at {url}.")
            if is_local_url(url):
                say("  Install Ollama from https://ollama.com/download and start it (open the app, or run `ollama serve`), then run this again.")
            else:
                say(f"  Start Ollama on that machine with OLLAMA_HOST=0.0.0.0, or set {ENV_URL} to the right address.")
            ok = False
            continue
        say(f"model server: Ollama {st['version']} at {url}")
        for model, info in st["present"].items():
            if info:
                say(f"  {model}: ready")
                continue
            if not pull:
                say(f"  {model}: missing (run `ollama pull {model}`, or drop --no-pull)")
                ok = False
                continue
            say(f"  {model}: downloading (once; several GB)")
            shown = {"pct": -10}

            def progress(status: str, done: int, total: int, model: str = model, shown: dict[str, int] = shown) -> None:
                pct = int(100 * done / total) if total else 0
                if total and pct >= shown["pct"] + 10:
                    shown["pct"] = pct
                    say(f"    {model}: {pct}% of {total / 1e9:.1f} GB")

            try:
                ollama_pull(url, model, on_progress=progress)
                say(f"  {model}: ready")
            except ProviderError as exc:
                say(f"  {model}: {exc}")
                ok = False
    llm = cfg.providers.llm
    if llm.kind == "openai_compatible":
        base = (llm.base_url or "http://localhost:1234/v1").rstrip("/")
        try:
            served = [m.get("id") for m in JSONClient(base, timeout_s=5, use_env_proxy=not is_local_url(base)).request("GET", "/models").get("data") or []]
            say(f"model server: OpenAI-compatible API at {base}" + (f" serving {', '.join(str(m) for m in served[:4])}" if served else ""))
            if served and llm.model not in served:
                say(f"  note: the config asks for {llm.model}, which the server does not list")
        except ProviderError as exc:
            say(f"no model server at {base} ({exc}). Start llama-server, vLLM or LM Studio there, or set {ENV_URL}.")
            ok = False
    return ok


def town_dir(cfg: GAConfig, run_dir: str | None) -> Path:
    """The folder a town lives in between sessions: one per town name, so it always continues."""

    from .config import repo_path

    return Path(run_dir) if run_dir else repo_path(cfg.run.output_dir) / cfg.run.name


# ------------------------------------------------------------------------------------ tuning
# Below this much memory the 8B model does not fit next to the 3B and the embedding model
# (about 8.5 GB loaded together), so one small model does everything. A rule of thumb for
# machines whose model server shares the system's memory (laptops, Apple Silicon); a machine
# with a large GPU can say otherwise with --models.
SMALL_MACHINE_GB = 12.0
MECHANICAL = ("choose_location", "importance", "importance_batch", "action_grounding")


def machine_memory_gb() -> float | None:
    """Physical memory of this machine in GB, or None where it cannot be read."""

    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("total", "avail", "a", "b", "c", "d", "e")
                ]

            status = _Status()
            status.length = ctypes.sizeof(_Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return status.total / 1e9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return None


def plan_models(cfg: GAConfig, *, memory_gb: float | None, explicit: str | None = None) -> tuple[list[str], str | None]:
    """Which models the town should use on this machine, as config overrides plus the reason.

    ``explicit`` is the user's ``--models BIG[,SMALL]`` and always wins. Otherwise, when the
    model server is this machine and the machine is small, the config's small model does every
    task; in every other case the config stands.
    """

    from .providers.local_http import is_local_url
    from .providers.ollama_provider import DEFAULT_URL

    llm = cfg.providers.llm
    routed = [t for t, o in llm.task_overrides.items() if o.get("model") and not o.get("provider")]
    small = next((llm.task_overrides[t]["model"] for t in routed), None)
    if explicit:
        parts = [m.strip() for m in explicit.split(",") if m.strip()]
        big, little = parts[0], (parts[1] if len(parts) > 1 else parts[0])
        return [
            f"providers.llm.model={big}",
            *(f"providers.llm.task_overrides.{t}.model={little}" for t in routed),
        ], f"models set by you: {big} for judgment, {little} for mechanical tasks"
    if llm.kind != "ollama" or small is None or small == llm.model or memory_gb is None or not is_local_url(llm.base_url or DEFAULT_URL):
        return [], None
    if memory_gb < SMALL_MACHINE_GB:
        return [f"providers.llm.model={small}"], (
            f"this machine has {memory_gb:.0f} GB of memory, too little to keep {llm.model} loaded next to {small}: {small} does every task (override with --models)"
        )
    return [], f"this machine has {memory_gb:.0f} GB of memory: {llm.model} for judgment, {small} for mechanical tasks"


def probe_parallel(cfg: GAConfig, *, at_once: int = 4, say: Callable[[str], None] = print) -> dict[str, Any] | None:
    """Ask the model server one question alone and ``at_once`` together; how much does it gain?

    Returns the timings, the gain and the ``engine.parallel_calls`` that fits it (1, 2 or 4), or
    None when the server cannot be asked. The first, untimed call loads the model.
    """

    from .prompting import PromptRegistry
    from .providers.base import LLMRequest, ProviderError
    from .providers.schema import strict_json_schema
    from .simulation.runtime import build_llm_provider

    llm = cfg.providers.llm
    model = next((o["model"] for t, o in llm.task_overrides.items() if t in MECHANICAL and o.get("model") and not o.get("provider")), llm.model)
    tpl = PromptRegistry().get("importance")
    provider = build_llm_provider(cfg)
    passage = (
        "Maria Lopez is sitting at a table in Hobbs Cafe with her physics notes, a cup of tea going cold beside her, while the morning regulars come and go. "
        * 6
    )

    def one(i: int) -> float:
        req = LLMRequest(
            task="importance",
            template_id=tpl.template_id,
            template_hash=tpl.sha256,
            system="You rate how poignant a memory is for a person, from 1 (mundane) to 10 (life-changing). Answer with JSON only.",
            prompt=f'{passage}\n\nMemory {i}: Maria Lopez is drinking tea.\nReturn {{"rating": <1-10>}}.',
            output_schema=strict_json_schema(tpl.output_model),
            model=model,
            max_output_tokens=32,
            temperature=llm.temperature,
        )
        t = time.monotonic()
        provider.complete(req)
        return time.monotonic() - t

    try:
        one(0)  # loads the model; not timed
        alone = (one(1) + one(2)) / 2
        t = time.monotonic()
        with ThreadPoolExecutor(max_workers=at_once) as pool:
            list(pool.map(one, range(10, 10 + at_once)))
        together = time.monotonic() - t
    except ProviderError as exc:
        say(f"could not measure the model server ({exc}); keeping engine.parallel_calls={cfg.engine.parallel_calls}")
        return None
    gain = at_once * alone / together if together > 0 else 1.0
    parallel = 4 if gain >= 3 else 2 if gain >= 1.6 else 1
    return {
        "model": model,
        "alone_s": round(alone, 3),
        "together_s": round(together, 3),
        "at_once": at_once,
        "gain": round(gain, 2),
        "parallel_calls": parallel,
    }


# ----------------------------------------------------------------------------------- founding
@dataclass
class Founding:
    """Everything `ga town` decided before the town starts."""

    config: str
    sets: list[str]
    run_dir: Path
    resuming: bool
    cfg: GAConfig
    notes: list[str] = field(default_factory=list)
    tuning: dict[str, Any] = field(default_factory=dict)


def plan_town(
    *,
    config: str | None = None,
    name: str | None = None,
    residents: int | None = None,
    cast: str | None = None,
    newcomers: str | None = None,
    run_dir: str | None = None,
    sets: list[str] | None = None,
    url: str | None = None,
    models: str | None = None,
    memory_gb: float | None = None,
) -> Founding:
    """Decide which town this is (a new one to found, or one to continue) and with what settings.

    A new town takes its cast, its name, your own residents and a model plan that fits the
    machine. An existing town keeps all of that: only the model-server address, explicit
    ``--models`` and ``--set`` values apply, and the founding options are reported as ignored.
    """

    from . import founding
    from .config import repo_path
    from .simulation.engine import load_run_config

    sets = list(sets or [])
    path = config or (TOWN_CONFIGS[25] if residents == 25 and not (name or cast or newcomers) else TOWN_CONFIGS[10])
    first = load_config(path, overrides=sets)
    custom = bool(cast or newcomers or residents not in (None, 10, 25))
    run_name = founding.folder_name(name) if name else first.run.name + (f"-{residents}" if custom and residents is not None and not config else "")
    folder = Path(run_dir) if run_dir else repo_path(first.run.output_dir) / run_name
    notes: list[str] = []
    town_scenario = founding.scenario_path(folder)

    if (folder / "state.sqlite").exists() and (folder / "config.yaml").exists():
        saved = load_run_config(folder)
        extra = [*sets, *server_overrides(saved, url)]
        if town_scenario.exists():
            extra.append(f"scenario.path={json.dumps(str(town_scenario))}")  # the folder may have moved
        extra += plan_models(saved, memory_gb=memory_gb, explicit=models)[0] if models else []
        if cast or newcomers or residents not in (None, len(saved.scenario.population or []) or 25):
            notes.append(
                "continuing the town that is already here: --residents, --cast and --newcomers only apply when a town is founded (use --name for another town)"
            )
        return Founding(path, extra, folder, True, load_run_config(folder, extra), notes)

    founded: list[str] = []
    if name:
        founded += [f"run.name={run_name}", f"run.label={json.dumps(name)}", f"game.town_name={json.dumps(name)}"]
    elif run_name != first.run.name:
        founded.append(f"run.name={run_name}")
    people: list[str] | None = None
    if custom or (config and residents is not None):
        people = founding.choose_cast(10 if residents is None else residents, cast, seed=first.run.seed)
    if newcomers:
        cards = founding.load_cards(newcomers)
        report = founding.build_scenario(cards, folder / "scenario", name or run_name)
        people = (people if people is not None else founding.choose_cast(10, cast, seed=first.run.seed)) + report["newcomers"]
        founded.append(f"scenario.path={json.dumps(str(town_scenario))}")
        notes.append(f"moved in: {', '.join(report['newcomer_names'])} ({', '.join(report['houses'])})")
    elif people is not None and not str(first.scenario.path).startswith(founding.BASE):
        founded.append(f"scenario.path={founding.BASE}/scenario.yaml")
    if people is not None:
        if not people:
            raise founding.FoundingError("a town needs at least one resident")
        founded.append(f"scenario.population=[{', '.join(people)}]")
    cfg = load_config(path, overrides=[*sets, *founded])
    extra = server_overrides(cfg, url)
    model_sets, reason = plan_models(load_config(path, overrides=[*sets, *founded, *extra]), memory_gb=memory_gb, explicit=models)
    if reason:
        notes.append(reason)
    all_sets = [*sets, *founded, *extra, *model_sets]
    tuning = {"memory_gb": round(memory_gb, 1) if memory_gb else None, "models": reason}
    return Founding(path, all_sets, folder, False, load_config(path, overrides=all_sets), notes, tuning)


# ------------------------------------------------------------------------------------ window
APP_BROWSERS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def find_app_browser(candidates: tuple[str, ...] = APP_BROWSERS) -> str | None:
    for name in candidates:
        found = shutil.which(name) or (name if os.path.isabs(name) and os.path.exists(name) else None)
        if found:
            return found
    return None


def open_window(url: str, *, app: bool = False, launch: Callable[..., Any] | None = None) -> str:
    """Open the town: its own window without browser chrome when ``app`` and a Chromium-family
    browser is installed, otherwise a tab in the default browser. Returns what was done."""

    if app:
        browser = find_app_browser()
        if browser:
            (launch or subprocess.Popen)([browser, f"--app={url}", "--window-size=1440,900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"opened as an app window ({Path(browser).name})"
    import webbrowser

    webbrowser.open(url)
    return "opened in your browser"


# ------------------------------------------------------------------------------------- bench
def bench(cfg: GAConfig, *, minutes: int = 20, residents: int = 3, parallel: int = 4, say: Callable[[str], None] = print) -> dict[str, Any]:
    """Measure this model server on the town's real workload and project the town's pace.

    1. Runs the first ``minutes`` of a small town (``residents`` residents, sequentially) and
       reads each task's latency from the call ledger.
    2. Sends ``parallel`` copies of one recorded prompt at once to see how much the server gains
       from concurrency.
    3. Combines both with the recorded task mix to estimate how long a game day takes for 10 and
       25 residents, one call at a time and with parallel deciding.
    """

    from datetime import timedelta

    from .config import repo_path
    from .providers.base import LLMRequest
    from .providers.schema import strict_json_schema
    from .scenario.loader import load_scenario
    from .simulation.engine import Simulation

    scenario = load_scenario(repo_path(cfg.scenario.path), population=cfg.scenario.population, candidacy_seed_policy=cfg.scenario.candidacy_seed_policy)
    people = list(scenario.agent_ids)[:residents]
    small = cfg.model_copy(deep=True)
    small.scenario.population = people
    small.scenario.end = small.scenario.start + timedelta(minutes=minutes)
    small.engine.parallel_calls = 1
    small.game.enabled = False
    small.output.snapshots = []
    small.run.name = "bench"
    tmp = Path(tempfile.mkdtemp(prefix="hearthside-bench-"))
    say(f"1/3 running {len(people)} residents for {minutes} game minutes, one call at a time ...")
    started = time.monotonic()
    sim = Simulation(small, tmp / "run")
    try:
        status = sim.run()
        wall = time.monotonic() - started
        rows = sim.rt.ledger.rows()
        by_task: dict[str, list[float]] = {}
        by_model: dict[str, list[float]] = {}
        for r in rows:
            if r["status"] not in ("ok", "invalid", "received") or r["latency_ms"] is None:
                continue
            by_task.setdefault(r["task"], []).append(r["latency_ms"] / 1000)
            by_model.setdefault(r["model"], []).append(r["latency_ms"] / 1000)
        if not rows:
            say(f"the slice made no model calls (status {status}); try more --minutes")
            return {"status": status, "calls": 0}
        mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
        overall = mean([x for xs in by_task.values() for x in xs])
        say(f"    {len(rows)} calls in {wall:.1f}s; mean {overall:.2f}s per call")
        for task, xs in sorted(by_task.items(), key=lambda kv: -len(kv[1])):
            say(f"    {task:<22} {len(xs):>4} calls  {mean(xs):6.2f}s each")

        # ---- server concurrency: the same prompt, `parallel` at once
        gain = 1.0
        if parallel > 1:
            probe = next((r for r in rows if r["task"] == "importance"), rows[0])
            tpl = sim.rt.registry.get(probe["task"])
            provider = sim.rt.gateway.provider

            def one(i: int) -> float:
                req = LLMRequest(
                    task=probe["task"],
                    template_id=tpl.template_id,
                    template_hash=tpl.sha256,
                    system=probe["system"] or "",
                    prompt=f"{probe['prompt']}\n\n(benchmark copy {i})",
                    output_schema=strict_json_schema(tpl.output_model),
                    model=probe["model"],
                    max_output_tokens=int(json.loads(probe["settings_json"] or "{}").get("max_output_tokens") or tpl.max_output_tokens),
                    temperature=cfg.providers.llm.temperature,
                    agent_id=probe["agent_id"],
                )
                t = time.monotonic()
                provider.complete(req)
                return time.monotonic() - t

            say(f"2/3 asking {parallel} at once ...")
            alone = mean([one(-1 - i) for i in range(2)])
            t = time.monotonic()
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                list(pool.map(one, range(parallel)))
            together = time.monotonic() - t
            gain = max(1.0, parallel * alone / together) if together > 0 else 1.0
            say(f"    one call {alone:.2f}s; {parallel} together {together:.2f}s: the server does {gain:.1f}x the work when asked {parallel} at once")
            if gain < 1.5:
                say("    (little gain: the server answers one request at a time. Ollama: set OLLAMA_NUM_PARALLEL; llama-server: --parallel; or use vLLM)")
    finally:
        sim.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- projection
    small_models = {o["model"] for o in cfg.providers.llm.task_overrides.values() if o.get("model")}
    small_latency = mean([x for m in small_models for x in by_model.get(m, [])]) if any(by_model.get(m) for m in small_models) else overall
    main_latency = mean(by_model[cfg.providers.llm.model]) if by_model.get(cfg.providers.llm.model) else overall

    def latency(task: str) -> float:
        if by_task.get(task):
            return mean(by_task[task])
        return small_latency if cfg.providers.llm.task_overrides.get(task, {}).get("model") in small_models else main_latency

    per_resident_day = sum(n * latency(task) for task, n in CALLS_PER_RESIDENT_DAY.items())
    say("3/3 what that means for a town (task mix from a recorded day; a game day is 24 game hours):")
    out: dict[str, Any] = {
        "status": status,
        "calls": len(rows),
        "mean_latency_s": overall,
        "server_gain": gain,
        "per_resident_day_s": per_resident_day,
        "towns": {},
    }
    for n in (10, 25):
        seq_h = n * per_resident_day / 3600
        used = min(gain, SCHEDULE_GAIN[n]) if parallel > 1 else 1.0
        par_h = seq_h / used
        out["towns"][n] = {"sequential_hours_per_game_day": seq_h, "parallel_hours_per_game_day": par_h, "gain_used": used}
        line = f"    {n} residents: a game day takes {_hours(seq_h)} one call at a time"
        if parallel > 1:
            line += f", {_hours(par_h)} with engine.parallel_calls={parallel}"
        say(line + f" ({_pace(par_h)})")
    say("    The town is live at any pace: residents keep thinking; only the clock moves as fast as the model allows.")
    return out


def _hours(h: float) -> str:
    return f"{h * 60:.0f} min" if h < 1.5 else f"{h:.1f} h"


def _pace(hours_per_game_day: float) -> str:
    x = 24 / hours_per_game_day if hours_per_game_day > 0 else float("inf")
    return f"{x:.1f}x real time" if x >= 1 else f"{1 / x:.1f}x slower than real time"


# ------------------------------------------------------------------------------------ helpers
def load_town_config(config: str | None, residents: int, sets: list[str] | None, url: str | None) -> tuple[GAConfig, list[str]]:
    """The town's config with the model-server address applied; returns it with the overrides used."""

    path = config or TOWN_CONFIGS[residents]
    sets = list(sets or [])
    first = load_config(path, overrides=sets)
    extra = server_overrides(first, url)
    return (load_config(path, overrides=[*sets, *extra]) if extra else first), [*sets, *extra]


def is_headless() -> bool:
    if sys.platform in ("darwin", "win32"):
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


__all__ = [
    "ENV_URL",
    "TOWN_CONFIGS",
    "bench",
    "is_headless",
    "load_town_config",
    "needed_models",
    "open_window",
    "prepare_models",
    "server_overrides",
    "town_dir",
]
