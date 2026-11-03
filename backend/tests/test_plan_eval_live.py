"""Live accuracy check of plan detection (#14): the real Gemini Plan Model on every
hand-written case in `tests/fixtures/plan_eval/`.

Calls the Gemini API, so it is deselected by default; run it with `make eval-plans` (needs
GEMINI_API_KEY in `.env`, on a paid tier; GEMINI_MODEL picks the model). It prints a per-case
table, writes `backend/data/plan-eval-report.md` and fails if fewer than PLAN_EVAL_MIN_SCORE
(default 0.8) of the cases pass. The cases are made up, so the report is safe to share.
"""

import logging
import os
import re

import pytest

from app.adapters.gemini import GeminiPlanModel
from app.adapters.protocols import PlanDecision
from app.config import BACKEND_DIR, PlanModelSettings
from tests.plan_eval import CaseScore, load_cases, overall, report, score, table

pytestmark = pytest.mark.live

REPORT_PATH = BACKEND_DIR / "data" / "plan-eval-report.md"
DEFAULT_MIN_SCORE = 0.8
GEMINI_LOGGER = "app.adapters.gemini"


async def test_plan_detection_accuracy(caplog: pytest.LogCaptureFixture) -> None:
    settings = PlanModelSettings()
    if settings.gemini_api_key is None:
        pytest.skip(
            "GEMINI_API_KEY is not set: put your paid-tier Gemini API key in .env to run the "
            "plan detection accuracy check (README: 'Checking plan detection accuracy')"
        )
    min_score = float(os.environ.get("PLAN_EVAL_MIN_SCORE", DEFAULT_MIN_SCORE))
    model = GeminiPlanModel(
        api_key=settings.gemini_api_key.get_secret_value(), model=settings.gemini_model
    )
    caplog.set_level(logging.DEBUG, logger=GEMINI_LOGGER)

    scores: list[CaseScore] = []
    reasons: dict[str, str] = {}
    # One case at a time, so the model's logged reason belongs to the case just asked.
    for case in load_cases():
        caplog.clear()
        decision: PlanDecision | BaseException
        try:
            decision = await model.decide(case.request())
        except Exception as exc:  # scored as a failed case; the run carries on
            decision = exc
        if reason := _logged_reason(caplog):
            reasons[case.name] = reason
        scores.append(
            score(case, decision, confidence_threshold=settings.plan_confidence_threshold)
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        report(
            scores,
            model=settings.gemini_model,
            confidence_threshold=settings.plan_confidence_threshold,
            min_score=min_score,
            reasons=reasons,
        ),
        encoding="utf-8",
    )
    print(f"\nPlan detection accuracy, model {settings.gemini_model}:\n")
    print(table(scores))
    print(f"Report: {REPORT_PATH}")

    assert overall(scores) >= min_score, (
        f"only {overall(scores):.0%} of plan detection cases passed (minimum {min_score:.0%}); "
        f"see {REPORT_PATH}"
    )


def _logged_reason(caplog: pytest.LogCaptureFixture) -> str | None:
    """The one-sentence reason GeminiPlanModel logs at DEBUG for its decision."""
    for record in caplog.records:
        if record.name == GEMINI_LOGGER and (
            match := re.match(r"Gemini decided \w+: (.*)", record.getMessage(), re.S)
        ):
            return match.group(1)
    return None
