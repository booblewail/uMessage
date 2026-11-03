"""The plan detection accuracy check without Gemini: every fixture case is valid, and a Plan
Model's decision is scored as the live check (`make eval-plans`) scores it."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.adapters.protocols import NewPlan, NoPlan, PlanDecision, PlanDetails, UpdatePlan
from tests.plan_eval import (
    FIXTURES_DIR,
    PlanEvalCase,
    load_case,
    load_cases,
    overall,
    report,
    score,
    table,
)

SYDNEY = timezone(timedelta(hours=11))  # AEDT, in November
THRESHOLD = 0.5


def case_json(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "dinner",
        "description": "Dinner on Friday at 7:30pm.",
        "timezone": "Australia/Sydney",
        "now": "2026-11-03T14:05:00+11:00",
        "messages": [
            {
                "sender_name": "Ana",
                "text": "Dinner Friday 7:30pm at Chaco Bar?",
                "sent_at": "2026-11-03T13:50:00+11:00",
                "outbound": False,
            },
            {
                "sender_name": "You",
                "text": "Keen",
                "sent_at": "2026-11-03T13:52:00+11:00",
                "outbound": True,
            },
        ],
        "pending": [
            {
                "id": 7,
                "title": "Climbing",
                "start": "2026-11-05T19:00:00+11:00",
                "end": None,
                "all_day": False,
                "location": None,
            }
        ],
        "expected": {
            "kind": "new",
            "start_date": "2026-11-06",
            "start_time": "19:30",
            "all_day": False,
            "location_contains": "chaco",
        },
    }
    return {**base, **overrides}


def make_case(**overrides: Any) -> PlanEvalCase:
    return PlanEvalCase.model_validate(case_json(**overrides))


def plan(start: datetime, *, end: datetime | None = None, **fields: Any) -> PlanDetails:
    values: dict[str, Any] = {
        "title": "Dinner at Chaco Bar",
        "start": start,
        "end": end,
        "all_day": False,
        "location": "Chaco Bar",
        "confidence": 0.9,
    }
    values.update(fields)
    return PlanDetails(**values)


def failed_checks(case: PlanEvalCase, decision: PlanDecision | BaseException) -> list[str]:
    return [check.name for check in score(case, decision, confidence_threshold=THRESHOLD).failures]


# --- The fixtures -------------------------------------------------------------------------


def test_every_fixture_is_a_valid_case() -> None:
    paths = sorted(FIXTURES_DIR.glob("*.json"))
    assert len(paths) >= 14
    for path in paths:
        load_case(path)  # raises with the file's problem


def test_the_fixtures_cover_every_kind_of_decision() -> None:
    cases = load_cases()

    assert len({case.name for case in cases}) == len(cases)
    kinds = {case.expected.kind for case in cases}
    assert kinds == {"nothing", "new", "update"}
    assert any(case.expected.all_day for case in cases)
    assert any(case.expected.end_date for case in cases)
    assert any(case.messages[0].outbound for case in cases)


def test_a_case_builds_the_request_the_app_would_make() -> None:
    request = make_case().request()

    assert request.timezone == "Australia/Sydney"
    assert request.now == datetime(2026, 11, 3, 3, 5, tzinfo=UTC)
    assert [m.text for m in request.messages] == ["Dinner Friday 7:30pm at Chaco Bar?", "Keen"]
    assert request.messages[1].outbound
    [pending] = request.pending
    assert (pending.id, pending.start) == (7, datetime(2026, 11, 5, 8, 0, tzinfo=UTC))


def test_a_fixture_must_be_named_after_its_file(tmp_path: Path) -> None:
    path = tmp_path / "other_name.json"
    path.write_text(json.dumps(case_json()))

    with pytest.raises(ValueError, match="doesn't match the file name"):
        load_case(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"timezone": "Mars/Olympus_Mons"},
        {"now": "2026-11-03T13:00:00+11:00"},  # before the latest Message
        {"messages": []},
        {"messages": [{"sender_name": "Ana", "text": "hi", "sent_at": "2026-11-03T13:50:00",
                       "outbound": False}]},
        {"expected": {"kind": "update", "event_id": 99, "start_date": "2026-11-06",
                      "start_time": "20:00", "all_day": False}},
        {"expected": {"kind": "update", "start_date": "2026-11-06", "start_time": "20:00",
                      "all_day": False}},
        {"expected": {"kind": "new", "start_date": "2026-11-06", "all_day": False}},
        {"expected": {"kind": "new", "start_date": "2026-11-07", "start_time": "10:00",
                      "all_day": True}},
        {"expected": {"kind": "nothing", "start_date": "2026-11-06"}},
        {"expected": {"kind": "maybe"}},
        {"surprise": True},
    ],
    ids=[
        "unknown-time-zone",
        "now-before-messages",
        "no-messages",
        "naive-sent-at",
        "update-of-unknown-plan",
        "update-without-id",
        "timed-without-time",
        "all-day-with-time",
        "nothing-with-a-date",
        "unknown-kind",
        "unknown-field",
    ],
)  # fmt: skip
def test_a_broken_case_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_case(**overrides)


# --- Scoring ------------------------------------------------------------------------------


def test_the_right_plan_passes_whether_it_has_an_offset_or_not() -> None:
    case = make_case()

    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 19, 30, tzinfo=SYDNEY)))) == []
    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 19, 30)))) == []  # naive: local
    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 8, 30, tzinfo=UTC)))) == []


def test_a_wrong_time_day_or_place_fails_that_check() -> None:
    case = make_case()

    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 7, 30)))) == ["start"]
    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 13, 19, 30)))) == ["start"]
    wrong_offset = datetime(2026, 11, 6, 19, 30, tzinfo=timezone(timedelta(hours=10)))
    assert failed_checks(case, NewPlan(plan(wrong_offset))) == ["start"]
    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 19, 30), location=None))) == [
        "location"
    ]


def test_the_start_may_be_off_by_the_cases_tolerance() -> None:
    expected = {**case_json()["expected"], "start_tolerance_minutes": 30}
    case = make_case(expected=expected)

    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 20, 0)))) == []
    assert failed_checks(case, NewPlan(plan(datetime(2026, 11, 6, 20, 1)))) == ["start"]


def test_the_wrong_kind_of_decision_fails_without_further_checks() -> None:
    case = make_case()

    assert failed_checks(case, NoPlan()) == ["kind"]
    assert failed_checks(case, UpdatePlan(7, plan(datetime(2026, 11, 6, 19, 30)))) == ["kind"]
    nothing = make_case(expected={"kind": "nothing"})
    assert failed_checks(nothing, NoPlan()) == []
    assert failed_checks(nothing, NewPlan(plan(datetime(2026, 11, 6, 19, 30)))) == ["kind"]


def test_an_update_must_name_the_right_pending_plan() -> None:
    case = make_case(
        expected={"kind": "update", "event_id": 7, "start_date": "2026-11-05",
                  "start_time": "20:00", "all_day": False}
    )  # fmt: skip

    assert failed_checks(case, UpdatePlan(7, plan(datetime(2026, 11, 5, 20, 0)))) == []
    assert failed_checks(case, UpdatePlan(8, plan(datetime(2026, 11, 5, 20, 0)))) == ["event_id"]


def test_a_plan_below_the_confidence_threshold_counts_as_nothing() -> None:
    unsure = NewPlan(plan(datetime(2026, 11, 6, 19, 30), confidence=THRESHOLD - 0.01))

    result = score(make_case(), unsure, confidence_threshold=THRESHOLD)
    assert [c.name for c in result.failures] == ["kind"]
    assert "below confidence threshold" in result.got
    assert score(make_case(expected={"kind": "nothing"}), unsure, confidence_threshold=0.5).passed


def test_an_all_day_plan_is_scored_on_its_dates() -> None:
    case = make_case(
        expected={"kind": "new", "start_date": "2026-11-20", "end_date": "2026-11-22",
                  "all_day": True}
    )  # fmt: skip
    trip = plan(datetime(2026, 11, 20), end=datetime(2026, 11, 22), all_day=True)

    assert failed_checks(case, NewPlan(trip)) == []
    one_day = plan(datetime(2026, 11, 20), all_day=True)
    assert failed_checks(case, NewPlan(one_day)) == ["end"]
    timed = plan(datetime(2026, 11, 20, 9, 0), end=datetime(2026, 11, 22, 17, 0))
    assert failed_checks(case, NewPlan(timed)) == ["all_day"]


def test_an_error_from_the_plan_model_fails_the_case() -> None:
    result = score(make_case(), ValueError("bad JSON"), confidence_threshold=THRESHOLD)

    assert not result.passed
    assert "ValueError: bad JSON" in result.got


def test_the_overall_score_is_the_share_of_cases_that_pass() -> None:
    case = make_case()
    right = score(case, NewPlan(plan(datetime(2026, 11, 6, 19, 30))), confidence_threshold=0.5)
    wrong = score(case, NoPlan(), confidence_threshold=0.5)

    assert overall([right, right, right, wrong]) == 0.75
    assert overall([]) == 0.0
    text = table([right, wrong])
    assert "PASS  dinner" in text and "FAIL  dinner" in text and "1/2 cases = 50%" in text


def test_the_report_lists_every_case_with_its_chat() -> None:
    case = make_case()
    right = score(case, NewPlan(plan(datetime(2026, 11, 6, 19, 30))), confidence_threshold=0.5)
    wrong = score(case, NoPlan(), confidence_threshold=0.5)

    text = report(
        [right, wrong],
        model="gemini-test",
        confidence_threshold=0.5,
        min_score=0.8,
        reasons={"dinner": "They agreed on dinner."},
    )

    assert "`gemini-test`" in text
    assert "1/2 cases = 50%" in text and "BELOW the minimum of 80%" in text
    assert "kind: expected new, got nothing" in text
    assert "**Ana**: Dinner Friday 7:30pm at Chaco Bar?" in text
    assert "**You (user)**: Keen" in text
    assert "Model's reason: They agreed on dinner." in text


def answer_expected(case: PlanEvalCase) -> PlanDecision:
    """The decision a perfect Plan Model would make for the case (naive local times)."""
    expected = case.expected
    if expected.kind == "nothing":
        return NoPlan()
    assert expected.start_date is not None
    start = datetime.combine(expected.start_date, expected.start_time or datetime.min.time())
    end = datetime.combine(expected.end_date, start.time()) if expected.end_date else None
    perfect = plan(
        start, end=end, all_day=bool(expected.all_day), location=expected.location_contains
    )
    if expected.kind == "update":
        assert expected.event_id is not None
        return UpdatePlan(expected.event_id, perfect)
    return NewPlan(perfect)


def test_a_perfect_plan_model_passes_every_fixture_case() -> None:
    scores = [
        score(case, answer_expected(case), confidence_threshold=THRESHOLD) for case in load_cases()
    ]

    assert [s.case.name for s in scores if not s.passed] == []
    assert overall(scores) == 1.0
