"""Round-two research upgrades: paired statistics, parallel runs, per-seed fork sources,
probe variants and query styles, threshold-free network measures."""

from __future__ import annotations

import re

import yaml

from generative_agents.evaluation import memory_probe as mp
from generative_agents.evaluation.experiment import Protocol, _holm, _paired_test, _permutation_test, execute, render, summarize
from generative_agents.providers.embeddings import _STOP, _WORD, MockHashEmbedding
from generative_agents.providers.mock import MockLLM
from generative_agents.simulation.engine import Simulation, save_config
from generative_agents.social import network
from helpers import sim_config

PAIR = ["isabella_rodriguez", "klaus_mueller"]


# ---------------------------------------------------------------------------- statistics
def test_paired_test_uses_the_within_seed_differences():
    a = {1: 0.9, 2: 0.7, 3: 0.8, 4: 0.6, 5: 0.75}
    b = {1: 0.8, 2: 0.6, 3: 0.7, 4: 0.5, 5: 0.65, 6: 0.1}  # seed 6 has no partner and is ignored
    t = _paired_test(a, b)
    assert t["n_pairs"] == 5 and abs(t["mean_difference"] - 0.1) < 1e-9 and t["same_sign"] == 5
    # every seed moved the same way: the exact sign-flip test gives its floor, 2 / 2**5
    assert t["p"] == t["min_p"] == 0.0625 and t["method"] == "exact sign-flip"
    assert t["effect_size_dz"] is None or t["effect_size_dz"] > 5  # identical differences have no spread
    mixed = _paired_test({1: 1.0, 2: 0.0, 3: 1.0, 4: 0.0}, {1: 0.0, 2: 1.0, 3: 0.0, 4: 1.0})
    assert mixed["p"] == 1.0 and mixed["mean_difference"] == 0.0
    same = _paired_test({1: 0.5, 2: 0.5}, {1: 0.5, 2: 0.5})
    assert same["p"] == 1.0 and same["method"] == "all differences are zero"
    assert _paired_test({1: 0.5}, {1: 0.4}) is None


def test_permutation_test_reports_the_floor_of_its_design_and_scales_past_exact_enumeration():
    small = _permutation_test([1.0, 1.0, 1.0], [0.0, 0.0, 0.0])
    assert small == {"p": 0.1, "method": "exact", "min_p": 0.1}  # 2 of C(6, 3) = 20 relabelings
    big = _permutation_test([1.0] * 12, [0.0] * 12)
    assert big["method"].startswith("monte-carlo") and big["p"] < 0.001
    null = _permutation_test([0.1, 0.9, 0.5, 0.4] * 3, [0.5, 0.4, 0.1, 0.9] * 3)
    assert null["p"] == 1.0  # identical multisets: every relabeling is at least as extreme as zero
    assert _permutation_test([], [1.0]) is None


def test_holm_adjustment_is_monotone_and_bounded():
    adj = _holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert adj["a"] == 0.04 and adj["c"] == 0.09 and adj["b"] == 0.09 and adj["d"] == 0.5
    assert _holm({}) == {}


def test_summary_pairs_by_seed_and_flags_seeds_that_are_copies():
    proto = Protocol(name="p", base_config="x", conditions={"a": [], "b": []}, seeds=[1, 2, 3], primary_outcomes=["y", "z"])
    rows = [{"run_id": f"{c}-{s}", "run_dir": "/nonexistent", "condition": c, "seed": s, "status": "completed"} for c in "ab" for s in (1, 2, 3)]
    for r in rows:
        r["y"] = (0.5 if r["condition"] == "a" else 0.2) + 0.01 * r["seed"]  # a - b = 0.3 on every seed
        r["z"] = 1.0 if r["condition"] == "a" else 0.0  # no between-seed spread at all
    s = summarize(rows, proto)
    y, z = s["comparisons"]["y"], s["comparisons"]["z"]
    assert y["paired"]["n_pairs"] == 3 and abs(y["paired"]["mean_difference"] - 0.3) < 1e-9 and y["paired"]["p"] == 0.25
    assert y["permutation_p"] == 0.1 and y["permutation_min_p"] == 0.1 and not y["no_between_seed_variation"]
    assert z["no_between_seed_variation"] is True
    assert y["paired"]["p_holm"] == 0.5 and s["comparison_family"]["size"] == 2
    assert s["conditions"]["a"]["outcomes"]["y"]["ci95"] is not None
    text = render(proto, rows, s)
    assert "paired by seed" in text and "smallest possible 0.25" in text and "the seeds are copies here" in text


# ---------------------------------------------------------------------------- runner
def _base(tmp_path, **scenario):
    b = tmp_path / "base.yaml"
    b.write_text(
        yaml.safe_dump(
            {
                "scenario": {
                    "path": "scenarios/pilot5/scenario.yaml",
                    "population": PAIR,
                    "start": "2023-02-13T09:00:00",
                    "end": "2023-02-13T09:20:00",
                    **scenario,
                },
                "output": {"checkpoint_every_steps": 30},
                "providers": {"embeddings": {"kind": "mock-hash", "dims": 128}},
            }
        )
    )
    return b


def test_parallel_jobs_give_the_same_rows_in_protocol_order(tmp_path):
    def proto(name):
        return Protocol(
            name=name,
            base_config=str(_base(tmp_path)),
            conditions={"full": [], "hourly": ["planning.decompose=false"]},
            seeds=[3, 4],
            metrics=["behavior", "network", "usage"],
            primary_outcomes=["scheduled_share"],
            output_dir=str(tmp_path / "experiments"),
        )

    serial = execute(proto("serial"))
    seen = []
    parallel = execute(proto("parallel"), jobs=2, progress=seen.append)
    assert [r["run_id"] for r in parallel["rows"]] == [r["run_id"] for r in serial["rows"]] == ["full-s3", "hourly-s3", "full-s4", "hourly-s4"]
    assert len(seen) == 4 and all(r["status"] == "completed" for r in parallel["rows"])
    for a, b in zip(serial["rows"], parallel["rows"], strict=True):
        for key in ("scheduled_share", "plan_adherence", "calls", "network_weighted_density"):
            assert a[key] == b[key], key


def test_per_seed_fork_sources_are_created_and_each_seed_forks_its_own_past(tmp_path):
    proto = Protocol(
        name="perseed",
        base_config=str(_base(tmp_path)),
        conditions={"control": [], "fire": []},
        seeds=[5, 6],
        metrics=["adaptation", "usage"],
        metric_params={"adaptation": {"at": "2023-02-13T09:11:00", "keywords": ["fire", "burning"], "window_minutes": 9}},
        primary_outcomes=["adaptation_perceivers"],
        fork_from={
            "run_dir": str(tmp_path / "sources" / "s{seed}"),
            "snapshot": "2023-02-13T09-10-00",
            "create": {
                "config": str(_base(tmp_path)),
                "overrides": ["output.snapshots=[initial, '2023-02-13T09:10:00', final]", "scenario.end=2023-02-13T09:10:10"],
            },
        },
        interventions={
            "fire": [
                {
                    "kind": "ambient",
                    "at": "2023-02-13T09:11:00",
                    "id": "f",
                    "tile": [78, 19],
                    "subject": "fire",
                    "object": "burning",
                    "description": "a fire is burning",
                }
            ]
        },
        output_dir=str(tmp_path / "experiments"),
    )
    assert proto.per_seed_sources() and [s["seed"] for s in proto.source_runs()] == [5, 6]
    assert proto.config_for(proto.runs()[0]).run.seed == 5  # planning works before any source exists
    res = execute(proto, jobs=2)
    assert [s["status"] for s in res["summary"]["fork_sources"]] == ["completed", "completed"]
    by = {r["run_id"]: r for r in res["rows"]}
    assert all(r["status"] == "completed" for r in by.values()), res["rows"]
    assert by["control-s5"]["forked_from"] == "s5@2023-02-13T09-10-00" and by["fire-s6"]["forked_from"] == "s6@2023-02-13T09-10-00"
    assert "each seed has its own recorded past" in (tmp_path / "experiments" / "perseed" / "report.md").read_text()
    again = execute(proto)  # sources and runs exist: nothing is recomputed
    assert [s["status"] for s in again["summary"]["fork_sources"]] == ["exists", "exists"]


# ---------------------------------------------------------------------------- memory probe
def test_second_fact_set_is_a_full_grid_and_its_paraphrases_share_no_content_word():
    facts = mp.load_facts("configs/probes/memory_facts_v2.yaml")
    assert len(facts) == 18 and len({f["id"] for f in facts}) == 18
    grid = {(f["age_hours"], f["importance"]) for f in facts}
    assert grid == {(a, i) for a in (0.5, 3, 8, 20, 32, 44) for i in (2, 5, 8)}

    def words(text):
        return {w for w in _WORD.findall(text.lower()) if w not in _STOP}

    for f in facts:
        st = words(f["statement"].replace("{name}", ""))
        assert not st & words(f["queries"]["paraphrase"]), f["id"]
        assert len(st & words(f["queries"]["lexical"])) >= 3, f["id"]
    assert mp.fact_queries({"query": "q"}) == {"lexical": "q"}


def test_probe_reports_styles_curves_and_exact_scoring_variants(tmp_path):
    cfg = sim_config(PAIR, end="2023-02-13T09:30:00")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    save_config(cfg, run_dir)
    sim = Simulation(cfg, run_dir, provider=MockLLM(seed=5), embedding_provider=MockHashEmbedding(128))
    assert sim.run() == "completed"
    snap = sim.snapshot("probe") if "final" not in sim.snapshots() else run_dir / sim.snapshots()["final"]["path"]
    sim.close()
    facts = mp.load_facts("configs/probes/memory_facts_v2.yaml")
    variants = {"relevance_only": {"weights.recency": 0, "weights.importance": 0}, "recency_only": {"weights.importance": 0, "weights.relevance": 0}}
    res = mp.planted_facts(cfg, snap, PAIR, facts=facts, k=10, embedding_provider=MockHashEmbedding(128), variants=variants)
    s = res["summary"]
    assert s["n"] == 2 * 18 * 2 and set(s["by_style"]) == {"lexical", "paraphrase"}
    # the hash fixture matches words, so paraphrases cannot beat lexical queries
    assert s["by_style"]["lexical"]["recall_at_k"] > s["by_style"]["paraphrase"]["recall_at_k"]
    curve = [s["recall_curve"][str(c)] for c in mp.CURVE_KS]
    assert curve == sorted(curve) and s["recall_curve"]["10"] == s["recall_at_k"] and s["recall_curve"]["30"] == s["recall_at_30"]
    assert set(s["by_age_hours"]) == {"0.5", "3", "8", "20", "32", "44"} and 0 <= s["mean_rank_percentile"] <= 1.1
    # the normalized recency of a never-accessed fact falls with its age
    rec = [s["by_age_hours"][a]["mean_normalized_recency"] for a in ("0.5", "3", "8", "20", "32", "44")]
    assert rec == sorted(rec, reverse=True)
    rel = res["variants"]["relevance_only"]["summary"]
    assert rel["by_style"]["lexical"]["recall_at_k"] == 1.0  # with relevance alone a lexical query finds its fact whatever its age
    assert rel["by_style"]["lexical"]["recall_at_k"] >= s["by_style"]["lexical"]["recall_at_k"]
    assert res["variants"]["recency_only"]["summary"]["old"]["recall_at_30"] == 0.0
    assert res["stream_sizes"][PAIR[0]] > 0
    assert mp.variant_settings(cfg, {"forgetting.enabled": True, "forgetting.threshold": -0.5}).forgetting.threshold == -0.5
    try:
        mp.variant_settings(cfg, {"weights.nope": 1})
    except KeyError as exc:
        assert "weights.nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unknown retrieval setting must be refused")


# ---------------------------------------------------------------------------- network
def test_threshold_free_network_measures_and_the_sweep():
    nodes = ["a", "b", "c", "d"]

    def st(a, b, f, conv=1):
        return {"agent_id": a, "other_id": b, "familiarity": f, "valence": 0.0, "conversations": conv, "presence": 0, "appraisals": 0}

    states = [st("a", "b", 0.8), st("b", "a", 0.6), st("a", "c", 0.3, conv=0), st("c", "a", 0.3, conv=0), st("c", "d", 0.9)]
    # six pairs: a-b contributes min(0.8, 0.6), a-c 0.3, c-d has one direction only and contributes nothing
    assert network.weighted_density(nodes, states) == round((0.6 + 0.3) / 6, 4)
    assert network.conversation_density(nodes, states) == round(2 / 6, 4)  # a-b and c-d talked; a-c only met
    sweep = {row["threshold"]: row for row in network.threshold_sweep(nodes, states, [0.2, 0.5, 0.75])}
    assert [sweep[t]["edge_count"] for t in (0.2, 0.5, 0.75)] == [2, 1, 0]
    m = network.measures(nodes, states, 0.2)
    assert m["weighted_density"] == 0.15 and m["conversation_density"] == 0.3333 and m["degree_gini"] is not None
    assert network.gini([1, 1, 1, 1]) == 0.0 and network.gini([0, 0, 0, 4]) == 0.75 and network.gini([0, 0]) is None
    assert network.weighted_density(["a"], []) is None


def test_report_names_are_plain_text():
    assert not re.search(r"__\w", "memory_recall_at_k")  # variant outcomes use the double underscore, base outcomes never do


# ---------------------------------------------------------------------------- contrasts, detail, rebuild
def test_planned_contrasts_form_their_own_family_and_check_the_registered_direction():
    proto = Protocol(
        name="p",
        base_config="x",
        conditions={"a": [], "b": []},
        seeds=[1, 2, 3, 4],
        primary_outcomes=["y"],
        contrasts=[
            {"outcome": "y", "a": "a", "b": "b", "expect": ">", "label": "y: a above b"},
            {"outcome": "y", "a": "b", "b": "a", "expect": ">"},  # the wrong way round on purpose
            {"outcome": "y_variant", "outcome_b": "y", "a": "a", "b": "a", "expect": ">="},  # two outcomes of the same runs
            {"outcome": "y", "a": "a", "b": "b", "expect": "=", "tolerance": 0.05},
            {"outcome": "missing", "a": "a", "b": "b", "expect": "<"},
        ],
    )
    rows = []
    for c, base in (("a", 0.6), ("b", 0.3)):
        for s in (1, 2, 3, 4):
            rows.append(
                {
                    "run_id": f"{c}{s}",
                    "run_dir": "/nonexistent",
                    "condition": c,
                    "seed": s,
                    "status": "completed",
                    "y": base + 0.01 * s,
                    "y_variant": base + 0.01 * s,
                }
            )
    s = summarize(rows, proto)
    up, down, same, band, missing = s["contrasts"]
    assert up["supported"] is True and up["label"] == "y: a above b" and abs(up["mean_difference"] - 0.3) < 1e-9
    assert up["paired"]["p"] == 0.125 and up["paired"]["same_sign"] == 4  # 2 / 2**4: the floor for four seeds
    assert down["supported"] is False and down["label"] == "y: b > a"
    assert same["supported"] is True and same["mean_difference"] == 0 and same["label"] == "a: y_variant >= y"
    assert band["supported"] is False and missing["supported"] is None and missing["paired"] is None
    # Holm runs over the planned contrasts that could be tested, not over every pairwise comparison
    assert up["paired"]["p_holm"] == 0.5 and same["paired"]["p_holm"] == 1.0
    text = render(proto, rows, s)
    assert "## Planned contrasts (registered with the hypothesis)" in text and "| y: b > a |" in text and "**no**" in text


def test_report_detail_pools_metric_files_and_rebuild_reproduces_the_report(tmp_path):
    from generative_agents.evaluation.experiment import load_rows, rebuild

    base = _base(tmp_path, end="2023-02-13T09:30:00")
    proto = Protocol(
        name="detail",
        base_config=str(base),
        conditions={"full": [], "recency_only": ["retrieval.weights.importance=0", "retrieval.weights.relevance=0"]},
        seeds=[3, 4],
        metrics=["memory_probe", "network", "usage"],
        metric_params={
            "memory_probe": {
                "facts": "configs/probes/memory_facts_v2.yaml",
                "variants": {"no_recency": {"weights.recency": 0}, "forgetting": {"forgetting.enabled": True, "forgetting.threshold": -0.6}},
            },
            "network": {"thresholds": [0.2, 0.5]},
        },
        primary_outcomes=["memory_recall_at_30"],
        contrasts=[{"outcome": "memory_recall_old_at_30__no_recency", "outcome_b": "memory_recall_old_at_30", "a": "full", "b": "full", "expect": ">="}],
        output_dir=str(tmp_path / "experiments"),
    )
    res = execute(proto, jobs=2)
    root = tmp_path / "experiments" / "detail"
    row = res["rows"][0]
    for key in (
        "memory_recall_paraphrase_at_30",
        "memory_recall_old_important_at_30__forgetting",
        "memory_forgotten__forgetting",
        "network_density_t50",
        "network_weighted_density",
    ):
        assert key in row, key
    assert row["memory_forgotten__forgetting"] == 2 * 5 * 2  # two agents, five facts below the threshold, two queries each
    report = (root / "report.md").read_text()
    for needle in (
        "## Detail: planted-fact retrieval",
        "Scoring variants on the snapshots of `full`",
        "Facts made inaccessible under `forgetting`: bees, fountain, ladder, marathon, scarf",
        "## Detail: the network at every threshold",
        "≥ 0.5",
    ):
        assert needle in report, needle
    for name in ("detail_recall_by_age.svg", "detail_variants_by_age.svg", "detail_density_by_threshold.svg", "rows.json", "detail.json"):
        assert (root / name).exists(), name
    again = rebuild(proto)
    assert (root / "report.md").read_text() == report and again["summary"]["contrasts"] == res["summary"]["contrasts"]
    # an experiment executed before rows.json existed is re-analysed from its CSV
    (root / "rows.json").unlink()
    from_csv = load_rows(root)
    assert [r["run_id"] for r in from_csv] == [r["run_id"] for r in res["rows"]]
    assert from_csv[0]["memory_recall_at_30"] == row["memory_recall_at_30"] and from_csv[0]["seed"] == 3 and from_csv[0]["status"] == "completed"


def test_line_chart_draws_every_series_and_breaks_at_missing_values():
    from generative_agents.evaluation.plots import line_chart

    svg = line_chart("t", ["a", "b", "c"], {"one": [0.1, 0.2, 0.3], "two": [0.5, None, 0.4], **{f"s{i}": [0.0, 0.0, 0.0] for i in range(5)}}, x_title="x")
    assert svg.count("<polyline") == 6  # "two" has no two adjacent points left, so only its dots are drawn
    assert svg.count("<circle") == 3 + 2 + 15 and ">one<" in svg and ">x<" in svg
    styles = re.findall(r'<polyline[^>]*stroke="(#[0-9A-F]+)"[^>]*stroke-dasharray="([^"]*)"', svg)
    assert len(set(styles)) == len(styles)  # no two series share color and dash
