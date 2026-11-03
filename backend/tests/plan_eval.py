"""The plan detection accuracy check (#14): hand-written Chat cases and how a Plan Model's
decision on each is scored.

Each case is one JSON file in `tests/fixtures/plan_eval/` (schema: `PlanEvalCase`). The live
check (`test_plan_eval_live.py`, `make eval-plans`) asks the real Gemini Plan Model about every
case; `test_plan_eval_scoring.py` checks the fixtures and the scoring without a key.

Scoring mirrors what the app would do with the decision: a plan less confident than
`PLAN_CONFIDENCE_THRESHOLD` creates or changes nothing, so it counts as "nothing", and times
are resolved like plan detection resolves them (naive = wall time in the case's time zone).
A case passes only if every check passes; the overall score is the share of cases that pass.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.adapters.protocols import (
    NewPlan,
    NoPlan,
    PendingPlan,
    PlanDecision,
    PlanDetails,
    PlanRequest,
    PlanWindowMessage,
    UpdatePlan,
)
from app.plan_detection import resolve_times

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "plan_eval"

Kind = Literal["nothing", "new", "update"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseMessage(_Strict):
    sender_name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sent_at: AwareDatetime
    outbound: bool


class CasePendingPlan(_Strict):
    id: int
    title: str = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime | None = None
    all_day: bool = False
    location: str | None = None


class Expected(_Strict):
    """The right decision. Dates and times are local to the case's time zone."""

    kind: Kind
    event_id: int | None = None  # update only: the pending plan it changes
    start_date: date | None = None  # new/update
    start_time: time | None = None  # new/update, timed plans only ("19:30")
    all_day: bool | None = None  # new/update
    end_date: date | None = None  # optional: the last day of a multi-day plan
    location_contains: str | None = None  # optional, case-insensitive
    start_tolerance_minutes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        plan_fields = (self.start_date, self.start_time, self.all_day, self.end_date)
        if self.kind == "nothing":
            if self.event_id is not None or any(v is not None for v in plan_fields):
                raise ValueError("a 'nothing' expectation has no event_id or plan fields")
            if self.location_contains is not None:
                raise ValueError("a 'nothing' expectation has no location")
            return self
        if (self.kind == "update") != (self.event_id is not None):
            raise ValueError("event_id is required for 'update' and only for 'update'")
        if self.start_date is None or self.all_day is None:
            raise ValueError(f"a {self.kind!r} expectation needs start_date and all_day")
        if self.all_day and self.start_time is not None:
            raise ValueError("an all-day plan has no start_time")
        if not self.all_day and self.start_time is None:
            raise ValueError("a timed plan needs start_time")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class PlanEvalCase(_Strict):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str = Field(min_length=1)
    timezone: str
    now: AwareDatetime
    messages: list[CaseMessage] = Field(min_length=1)
    pending: list[CasePendingPlan] = []
    expected: Expected

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        sent = [message.sent_at for message in self.messages]
        if sent != sorted(sent):
            raise ValueError("messages must be oldest first")
        if self.now < sent[-1]:
            raise ValueError("now is before the latest message")
        ids = [plan.id for plan in self.pending]
        if len(ids) != len(set(ids)):
            raise ValueError("pending plan ids must be unique")
        if self.expected.kind == "update" and self.expected.event_id not in ids:
            raise ValueError(f"expected event_id {self.expected.event_id} isn't a pending plan")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def request(self) -> PlanRequest:
        """The Plan Model request the app would make for this Chat."""
        return PlanRequest(
            messages=[
                PlanWindowMessage(m.sender_name, m.text, m.sent_at, m.outbound)
                for m in self.messages
            ],
            pending=[
                PendingPlan(
                    id=p.id,
                    title=p.title,
                    start=p.start.astimezone(UTC),
                    end=p.end.astimezone(UTC) if p.end else None,
                    all_day=p.all_day,
                    location=p.location,
                )
                for p in self.pending
            ],
            timezone=self.timezone,
            now=self.now,
        )


def load_case(path: Path) -> PlanEvalCase:
    case = PlanEvalCase.model_validate_json(path.read_text(encoding="utf-8"))
    if case.name != path.stem:
        raise ValueError(f"{path.name}: name {case.name!r} doesn't match the file name")
    return case


def load_cases(directory: Path = FIXTURES_DIR) -> list[PlanEvalCase]:
    return [load_case(path) for path in sorted(directory.glob("*.json"))]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CaseScore:
    case: PlanEvalCase
    got: str  # the decision, as one readable line
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]


def score(
    case: PlanEvalCase, decision: PlanDecision | BaseException, *, confidence_threshold: float
) -> CaseScore:
    """Score one decision (or the error the Plan Model raised) against the case."""
    expected = case.expected
    if isinstance(decision, BaseException):
        detail = f"{type(decision).__name__}: {decision}"
        return CaseScore(case, f"error ({detail})", [Check("kind", False, detail)])

    plan = None if isinstance(decision, NoPlan) else decision.plan
    kind: Kind = "nothing" if plan is None else "new" if isinstance(decision, NewPlan) else "update"
    got = describe(decision, case.tz)
    if plan is not None and plan.confidence < confidence_threshold:
        kind = "nothing"  # the app drops it
        got += f" -> below confidence threshold {confidence_threshold:g}: nothing"

    checks = [Check("kind", kind == expected.kind, f"expected {expected.kind}, got {kind}")]
    if kind != expected.kind or kind == "nothing" or plan is None:
        return CaseScore(case, got, checks)

    if isinstance(decision, UpdatePlan):
        checks.append(
            Check(
                "event_id",
                decision.event_id == expected.event_id,
                f"expected {expected.event_id}, got {decision.event_id}",
            )
        )
    checks.extend(_plan_checks(case, plan))
    return CaseScore(case, got, checks)


def _plan_checks(case: PlanEvalCase, plan: PlanDetails) -> list[Check]:
    expected = case.expected
    assert expected.start_date is not None and expected.all_day is not None
    tz = case.tz
    times = resolve_times(plan, tz)
    start = times.start.astimezone(tz)
    checks = [
        Check(
            "all_day",
            plan.all_day == expected.all_day,
            f"expected {expected.all_day}, got {plan.all_day}",
        )
    ]
    if expected.start_time is None:  # all-day: only the date counts
        checks.append(
            Check(
                "start",
                start.date() == expected.start_date,
                f"expected {expected.start_date}, got {start.date()}",
            )
        )
    else:
        want = datetime.combine(expected.start_date, expected.start_time, tzinfo=tz)
        off = abs(start - want)
        checks.append(
            Check(
                "start",
                off <= timedelta(minutes=expected.start_tolerance_minutes),
                f"expected {want:%Y-%m-%d %H:%M}, got {start:%Y-%m-%d %H:%M}",
            )
        )
    if expected.end_date is not None:
        last = (times.end or times.start).astimezone(tz).date()
        checks.append(
            Check("end", last == expected.end_date, f"expected {expected.end_date}, got {last}")
        )
    if expected.location_contains is not None:
        location = plan.location or ""
        checks.append(
            Check(
                "location",
                expected.location_contains.casefold() in location.casefold(),
                f"expected ~{expected.location_contains!r}, got {plan.location!r}",
            )
        )
    return checks


def describe(decision: PlanDecision, tz: ZoneInfo) -> str:
    if isinstance(decision, NoPlan):
        return "nothing"
    plan = decision.plan
    times = resolve_times(plan, tz)
    fmt = "%Y-%m-%d" if times.all_day else "%Y-%m-%d %H:%M"
    when = times.start.astimezone(tz).strftime(f"%a {fmt}")
    if times.end is not None:
        when += " to " + times.end.astimezone(tz).strftime(f"%a {fmt}")
    head = "new" if isinstance(decision, NewPlan) else f"update #{decision.event_id}"
    parts = [f"{head} {plan.title!r}", when + (" (all day)" if times.all_day else "")]
    if plan.location:
        parts.append(f"at {plan.location!r}")
    parts.append(f"confidence {plan.confidence:.2f}")
    return ", ".join(parts)


def describe_expected(expected: Expected) -> str:
    if expected.kind == "nothing":
        return "nothing"
    head = "new" if expected.kind == "new" else f"update #{expected.event_id}"
    when = str(expected.start_date)
    if expected.start_time is not None:
        when += f" {expected.start_time:%H:%M}"
        if expected.start_tolerance_minutes:
            when += f" (±{expected.start_tolerance_minutes} min)"
    if expected.end_date is not None:
        when += f" to {expected.end_date}"
    if expected.all_day:
        when += " (all day)"
    parts = [head, when]
    if expected.location_contains:
        parts.append(f"at ~{expected.location_contains!r}")
    return ", ".join(parts)


def overall(scores: Sequence[CaseScore]) -> float:
    return sum(s.passed for s in scores) / len(scores) if scores else 0.0


def table(scores: Sequence[CaseScore]) -> str:
    """A plain-text per-case table for the terminal."""
    width = max(len(s.case.name) for s in scores)
    lines = []
    for s in scores:
        mark = "PASS" if s.passed else "FAIL"
        lines.append(f"{mark}  {s.case.name:<{width}}  {s.got}")
        for check in s.failures:
            lines.append(f"      {'':<{width}}  {check.name}: {check.detail}")
    passed = sum(s.passed for s in scores)
    lines.append(f"\nOverall: {passed}/{len(scores)} cases = {overall(scores):.0%}")
    return "\n".join(lines)


def report(
    scores: Sequence[CaseScore],
    *,
    model: str,
    confidence_threshold: float,
    min_score: float,
    reasons: dict[str, str] | None = None,
    ran_at: datetime | None = None,
) -> str:
    """The Markdown report the live check writes, safe to share (the cases are made up)."""
    reasons = reasons or {}
    ran_at = ran_at or datetime.now(UTC)
    passed = sum(s.passed for s in scores)
    verdict = "meets" if overall(scores) >= min_score else "is BELOW"
    lines = [
        "# Plan detection accuracy report",
        "",
        f"- Model: `{model}`",
        f"- Run at: {ran_at:%Y-%m-%d %H:%M} UTC",
        f"- Confidence threshold: {confidence_threshold:g} (less confident plans count as "
        "nothing, as in the app)",
        f"- Overall: **{passed}/{len(scores)} cases = {overall(scores):.0%}**, which "
        f"{verdict} the minimum of {min_score:.0%}",
        "",
        "| | Case | Expected | Got | Failed checks |",
        "|---|---|---|---|---|",
    ]
    for s in scores:
        failed = "; ".join(f"{c.name}: {c.detail}" for c in s.failures) or "-"
        row = [
            "PASS" if s.passed else "FAIL",
            f"`{s.case.name}`",
            describe_expected(s.case.expected),
            s.got,
            failed,
        ]
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    lines += ["", "## Cases", ""]
    for s in scores:
        lines.append(f"### {'PASS' if s.passed else 'FAIL'}: `{s.case.name}`")
        lines.append("")
        lines.append(s.case.description)
        lines.append("")
        lines.append(f"Time zone {s.case.timezone}, now {_local(s.case.now, s.case)}.")
        for plan in s.case.pending:
            lines.append(
                f"Pending #{plan.id}: {plan.title!r} at {_local(plan.start, s.case)}"
                + (" (all day)" if plan.all_day else "")
            )
        lines.append("")
        for m in s.case.messages:
            who = f"{m.sender_name} (user)" if m.outbound else m.sender_name
            lines.append(f"> [{_local(m.sent_at, s.case)}] **{who}**: {m.text}  ")
        lines.append("")
        lines.append(f"- Expected: {describe_expected(s.case.expected)}")
        lines.append(f"- Got: {s.got}")
        if s.case.name in reasons:
            lines.append(f"- Model's reason: {reasons[s.case.name]}")
        lines.append("")
    return "\n".join(lines)


def _local(value: datetime, case: PlanEvalCase) -> str:
    return value.astimezone(case.tz).strftime("%a %Y-%m-%d %H:%M")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
