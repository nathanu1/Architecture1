"""Hierarchical planning: validation, JIT decomposition, replanning, midnight (spec G-1 … G-8)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from generative_agents.cognition.planning import Planner, PlanStore, fit_durations, is_sleep
from generative_agents.cognition.summary import SummaryService
from generative_agents.providers.mock import MockLLM, ScriptedLLM
from generative_agents.schemas import MemoryKind, PlanLevel, PlanStatus
from helpers import ISABELLA, KLAUS, make_stack

D0 = datetime(2023, 2, 13, 0, 0)


def planner_for(provider=None, overrides=None):
    cfg, db, rt, svc = make_stack(provider or MockLLM(seed=11), overrides)
    plans = PlanStore(db)
    return Planner(svc, SummaryService(svc), plans), plans, rt, svc


def test_day_plan_and_hour_blocks_cover_the_day_contiguously():
    planner, plans, rt, svc = planner_for()
    assert planner.ensure_day(ISABELLA, D0)
    blocks = plans.items(ISABELLA.id, day="2023-02-13", level=PlanLevel.HOUR)
    assert blocks[0].start == D0
    for a, b in zip(blocks, blocks[1:], strict=False):
        assert a.end == b.start and a.description != b.description  # contiguous, merged
    assert blocks[-1].end == D0 + timedelta(days=1)
    day = plans.items(ISABELLA.id, day="2023-02-13", level=PlanLevel.DAY)
    assert len(day) == 1 and day[0].memory_id
    mems = svc.store.for_agent(ISABELLA.id, kinds=[MemoryKind.PLAN])
    assert any(m.description.startswith("This is Isabella Rodriguez's plan for Monday February 13") for m in mems)
    assert not svc.store.for_agent(KLAUS.id)  # plans live only in the planner's own stream
    assert planner.ensure_day(ISABELLA, D0 + timedelta(hours=3))  # idempotent
    assert len(rt.ledger.rows(task="day_plan")) == 1


def test_invalid_day_plan_is_repaired_once():
    bad = {"wake_up_time": "6am", "items": [{"time": "07:00", "activity": "wake up"}]}
    planner, plans, rt, _ = planner_for(ScriptedLLM({"day_plan": [bad]}, fallback=MockLLM(seed=11)))
    assert planner.ensure_day(ISABELLA, D0)
    calls = rt.ledger.rows(task="day_plan")
    assert len(calls) == 2 and calls[0]["status"] == "invalid" and calls[1]["status"] == "ok"


def test_failed_day_plan_leaves_no_plan_and_retries_later():
    bad = {"wake_up_time": "x", "items": []}
    planner, plans, rt, svc = planner_for(ScriptedLLM({"day_plan": [bad, bad]}, fallback=MockLLM(seed=11)))
    assert not planner.ensure_day(ISABELLA, D0)
    assert plans.items(ISABELLA.id) == []  # nothing invented
    assert planner.current_task(ISABELLA, D0 + timedelta(hours=9)) is None
    assert [e["level"] for e in svc.events.query("plan_failure")] == ["day"]
    assert not planner.ensure_day(ISABELLA, D0 + timedelta(minutes=10))  # cooldown: no new call
    assert len(rt.ledger.rows(task="day_plan")) == 2
    assert planner.ensure_day(ISABELLA, D0 + timedelta(minutes=31))  # script exhausted -> mock answers


def test_an_hourly_schedule_ending_at_00_00_with_empty_blocks_is_read_not_rejected():
    # small models write midnight as 00:00 and sometimes put an empty block before each real one
    blocks = [
        {"start": "00:00", "end": "00:00", "activity": "sleeping"},
        {"start": "00:00", "end": "07:00", "activity": "sleeping"},
        {"start": "07:00", "end": "07:00", "activity": "morning routine"},
        {"start": "07:00", "end": "23:00", "activity": "working at the cafe"},
        {"start": "23:00", "end": "00:00", "activity": "sleeping"},
    ]
    gap = {"blocks": [{"start": "00:00", "end": "07:00", "activity": "sleeping"}, {"start": "08:00", "end": "00:00", "activity": "working"}]}
    planner, plans, rt, svc = planner_for(ScriptedLLM({"hourly_schedule": [{"blocks": blocks}]}, fallback=MockLLM(seed=11)))
    assert planner.ensure_day(ISABELLA, D0)
    assert [c["status"] for c in rt.ledger.rows(task="hourly_schedule")] == ["ok"]
    hours = plans.items(ISABELLA.id, level=PlanLevel.HOUR)
    assert [(h.start.hour, h.duration_min) for h in hours] == [(0, 420), (7, 960), (23, 60)]
    readings = svc.events.query("plan_reading")[0]["readings"]
    assert "block 5: read the end 00:00 as 24:00" in readings and sum("left out" in r for r in readings) == 2
    # a real gap is still an error, repaired or failed, never filled in
    planner2, _, rt2, _ = planner_for(ScriptedLLM({"hourly_schedule": [gap, gap]}, fallback=MockLLM(seed=11)))
    assert not planner2.ensure_day(KLAUS, D0)
    assert [c["status"] for c in rt2.ledger.rows(task="hourly_schedule")] == ["invalid", "invalid"]


def test_tasks_are_decomposed_just_in_time_for_the_current_window():
    planner, plans, rt, _ = planner_for()
    planner.ensure_day(KLAUS, D0)
    t = D0 + timedelta(hours=9, minutes=20)
    task = planner.current_task(KLAUS, t)
    assert task is not None and task.start <= t < task.end
    tasks = plans.items(KLAUS.id, level=PlanLevel.TASK)
    block = plans.get(task.parent_id)
    ws = block.start + timedelta(hours=int((t - block.start).total_seconds() // 3600))
    window = [x for x in tasks if x.parent_id == block.id]
    assert window[0].start == ws and sum(x.duration_min for x in window) == min(60, int((block.end - ws).total_seconds() // 60))
    assert all(5 <= x.duration_min <= 15 for x in window)
    for a, b in zip(window, window[1:], strict=False):
        assert a.end == b.start
    n = len(rt.ledger.rows(task="decompose"))
    assert planner.current_task(KLAUS, t + timedelta(minutes=1)).id in {x.id for x in window}
    assert len(rt.ledger.rows(task="decompose")) == n  # no repeated decomposition inside the window
    assert all(x.end <= ws + timedelta(hours=1) for x in tasks)  # later windows not decomposed yet


@pytest.mark.parametrize(
    "given,total,expected",
    [
        ([5, 10, 8, 12, 5, 10, 15], 60, [5, 10, 8, 12, 5, 10, 10]),  # five minutes over: the last task gives them up
        ([5, 10, 8, 12, 5, 10], 60, [5, 10, 8, 12, 10, 15]),  # ten minutes short: added from the end, within the range
        ([5, 2, 3, 8, 5, 10, 6, 4], 44, [5, 5, 5, 8, 5, 6, 5, 5]),  # out-of-range durations are clamped first
        ([60, 1, 10, 8], 44, [15, 5, 10, 14]),
        ([10, 10, 10, 10, 10, 10, 10, 10], 18, [8, 5, 5]),  # trailing tasks are dropped when even their minimum does not fit
        ([15, 15, 15, 15], 60, [15, 15, 15, 15]),  # a valid answer is returned unchanged
        ([10, 10], 60, None),  # too few tasks to fill the window: left to the repair attempt
        ([], 60, None),
        ([10], 3, None),
    ],
)
def test_fit_durations(given, total, expected):
    fitted = fit_durations(given, total, 5, 15)
    assert fitted == expected
    if fitted is not None:
        assert sum(fitted) == total and all(5 <= d <= 15 for d in fitted) and len(fitted) <= len(given)


def _bad_sum(n_tasks: int, minutes: int) -> dict:
    return {"tasks": [{"activity": f"step {k}", "duration_minutes": minutes, "minutes_left": 0} for k in range(1, n_tasks + 1)]}


def test_a_decomposition_with_wrong_arithmetic_is_rejected_by_default_and_fitted_on_request():
    bad = _bad_sum(7, 10)  # 70 minutes for a 60-minute window
    t = D0 + timedelta(hours=9, minutes=20)

    planner, plans, rt, svc = planner_for(ScriptedLLM({"decompose": [bad, bad]}, fallback=MockLLM(seed=11)))
    planner.ensure_day(KLAUS, D0)
    task = planner.current_task(KLAUS, t)
    assert task.metadata.get("decomposition_failed") and [c["status"] for c in rt.ledger.rows(task="decompose")] == ["invalid", "invalid"]
    assert not svc.events.query("plan_fitted")

    planner, plans, rt, svc = planner_for(ScriptedLLM({"decompose": [bad]}, fallback=MockLLM(seed=11)), ["planning.fit_durations=true"])
    planner.ensure_day(KLAUS, D0)
    task = planner.current_task(KLAUS, t)
    window = [x for x in plans.items(KLAUS.id, level=PlanLevel.TASK) if x.parent_id == task.parent_id]
    total = sum(x.duration_min for x in window)
    assert [c["status"] for c in rt.ledger.rows(task="decompose")] == ["ok"]  # accepted on the first attempt
    assert [x.description for x in window] == [f"step {k}" for k in range(1, len(window) + 1)]  # the model's activities, in order
    assert all(5 <= x.duration_min <= 15 for x in window) and total in (60, int((plans.get(task.parent_id).end - window[0].start).total_seconds() // 60))
    fitted = svc.events.query("plan_fitted")
    assert len(fitted) == 1 and fitted[0]["given"] == [10] * 7 and sum(fitted[0]["fitted"]) == total
    assert '"duration_minutes": 10' in rt.ledger.rows(task="decompose")[0]["raw_output"].replace('":10', '": 10')  # the raw answer is kept


def test_fitting_leaves_valid_answers_and_other_runs_untouched():
    a = planner_for()
    b = planner_for(overrides=["planning.fit_durations=true"])
    t = D0 + timedelta(hours=9, minutes=20)
    out = []
    for planner, plans, _rt, svc in (a, b):
        planner.ensure_day(KLAUS, D0)
        planner.current_task(KLAUS, t)
        out.append([(x.start, x.duration_min, x.description) for x in plans.items(KLAUS.id, level=PlanLevel.TASK)])
        assert not svc.events.query("plan_fitted")
    assert out[0] == out[1]


def test_sleep_is_not_decomposed():
    planner, plans, rt, _ = planner_for()
    planner.ensure_day(ISABELLA, D0)
    task = planner.current_task(ISABELLA, D0 + timedelta(hours=2))
    assert task is not None and is_sleep(task.description) and task.source == "block"
    assert rt.ledger.rows(task="decompose") == []


def test_insert_supersedes_overlaps_and_replans_rest_of_window():
    planner, plans, rt, svc = planner_for()
    planner.ensure_day(KLAUS, D0)
    t = D0 + timedelta(hours=9, minutes=7, seconds=40)
    first = planner.current_task(KLAUS, t)
    inserted = planner.insert(KLAUS, t, "talk to Isabella about her party", 12, source="conversation")
    assert inserted.start == t.replace(second=0) and inserted.duration_min == 12
    assert planner.current_task(KLAUS, t).id == inserted.id
    old = plans.get(first.id)
    assert old.status in (PlanStatus.DONE, PlanStatus.SUPERSEDED)
    block = plans.get(inserted.parent_id)
    ws, we = planner.window_of(block, t)
    active = [x for x in plans.items(KLAUS.id, level=PlanLevel.TASK) if x.status != PlanStatus.SUPERSEDED and x.end > t]
    covered = sorted(active, key=lambda x: x.start)
    assert covered[0].id == inserted.id
    assert covered[-1].end == we  # the regenerated rest ends exactly at the window end
    for a, b in zip(covered, covered[1:], strict=False):
        assert a.end == b.start
    assert len(rt.ledger.rows(task="replan")) == 1
    assert svc.events.query("replan")[0]["displaced"]


def test_wait_pauses_the_plan_without_replacing_it():
    planner, plans, rt, _ = planner_for()
    planner.ensure_day(KLAUS, D0)
    t = D0 + timedelta(hours=9, minutes=3)
    task = planner.current_task(KLAUS, t)
    wait = planner.insert(KLAUS, t, "waiting for the bathroom", 5, source="wait", displace=False)
    assert planner.current_task(KLAUS, t).id == wait.id
    planner.mark_done(wait.id, t + timedelta(minutes=5))
    later = planner.current_task(KLAUS, t + timedelta(minutes=5))
    if task.end > t + timedelta(minutes=5):
        assert later.id == task.id  # resumes the paused task
    assert plans.get(task.id).status != PlanStatus.SUPERSEDED


def test_midnight_boundary_spillover_and_next_day_plan():
    planner, plans, rt, _ = planner_for()
    planner.ensure_day(ISABELLA, D0)
    late = D0 + timedelta(hours=23, minutes=58)
    chat = planner.insert(ISABELLA, late, "chatting with Klaus Mueller", 10, source="conversation")
    nxt = D0 + timedelta(days=1)
    assert planner.ensure_day(ISABELLA, nxt)
    assert planner.current_task(ISABELLA, nxt + timedelta(minutes=5)).id == chat.id
    after = planner.current_task(ISABELLA, nxt + timedelta(minutes=8))
    assert after.id != chat.id and after.start == chat.end and after.day == "2023-02-14"
    assert len(rt.ledger.rows(task="day_plan")) == 2


def test_idempotent_completion():
    planner, plans, _, _ = planner_for()
    planner.ensure_day(KLAUS, D0)
    t = D0 + timedelta(hours=9, minutes=1)
    task = planner.current_task(KLAUS, t)
    planner.mark_done(task.id, t)  # not finished yet: no change
    assert plans.get(task.id).status == PlanStatus.PLANNED
    planner.mark_done(task.id, task.end)
    planner.mark_done(task.id, task.end + timedelta(minutes=1))
    assert plans.get(task.id).status == PlanStatus.DONE
    assert planner.current_task(KLAUS, task.end).id != task.id


@pytest.mark.parametrize("text,expected", [("sleeping", True), ("go to bed", True), ("take a nap", True), ("make the bed", False), ("have breakfast", False)])
def test_sleep_detection(text, expected):
    assert is_sleep(text) is expected
