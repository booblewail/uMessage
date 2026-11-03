"""The cheap pre-filter that decides whether a new Message might be about a plan (a pure
function, so it is tested directly); only Messages it lets through cost a Plan Model call."""

import pytest

from app.plan_prefilter import looks_like_plan


@pytest.mark.parametrize(
    "text",
    [
        # weekdays
        "Dinner Friday?",
        "free on tues?",
        "how about Sat",
        # times
        "7:30pm at Chaco Bar",
        "19:30 works",
        "see you at 7",
        "meet at 7.30",
        "8am?",
        "10 a.m. sharp",
        "noon ok?",
        # relative dates
        "tonight?",
        "Tomorrow works",
        "tmrw then",
        "next week maybe",
        "this weekend?",
        "later today?",
        # dates
        "how about 12/11",
        "the 3rd works",
        "Nov 12?",
        "on 14 November",
        # activity words
        "drinks after work",
        "coffee soon?",
        "let's catch up",
        "party at Sam's",
        "movie night",
        "game night!",
        "want to grab lunch",
        "brunch?",
        "let's meet up",
        "booked a table",
    ],
)
def test_messages_that_might_be_about_a_plan_get_through(text: str) -> None:
    assert looks_like_plan(text)


@pytest.mark.parametrize(
    "text",
    [
        "Keen",
        "lol",
        "ok thanks!",
        "Running late!",
        "Did you get home safe?",
        "Here's the link to the photos",
        "may I borrow your charger",
        "I have 2 cats",
        "haha 100%",
        "",
    ],
)
def test_ordinary_chatter_is_filtered_out(text: str) -> None:
    assert not looks_like_plan(text)
