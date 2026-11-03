"""A cheap check of whether a new Message might be about a plan: a weekday, a time, a relative
or calendar date, or an activity word. Only Messages it lets through get their Chat checked
by the Plan Model (a cloud call, ADR-0005), so it errs on the side of letting things through;
the Plan Model weeds out the rest.
"""

import re

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

_PATTERNS = [
    # Weekdays: "Friday", "fri", "tues", "weds", "thurs".
    r"\b(?:mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)(?:day)?s?\b",
    r"\b(?:tuesday|wednesday|thursday|saturday)s?\b",
    # Times: "7pm", "10 a.m.", "19:30", "7:30", "7.30", "at 7", "noon", "8 o'clock".
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)(?!\w)",
    r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b",
    r"\b(?:at|around|from|by|until|til|till)\s+\d{1,2}\b",
    r"\b(?:noon|midday|midnight|o'?clock)\b",
    # Relative dates.
    r"\b(?:today|tonight|tonite|tomorrow|tmrw|tmr|tomoz|yesterday)\b",
    r"\b(?:this|next|last)\s+(?:morning|afternoon|evening|night|week|weekend|month|year)\b",
    r"\bweekend\b",
    r"\blater\s+(?:today|tonight|on)\b",
    r"\bin\s+(?:a|\d+)\s+(?:days?|weeks?)\b",
    # Dates: "12/11", "12/11/26", "the 3rd", "Nov 12", "14 November".
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    r"\b\d{1,2}(?:st|nd|rd|th)\b",
    rf"\b{_MONTH}\.?\s+\d{{1,2}}\b",
    rf"\b\d{{1,2}}\s+(?:of\s+)?{_MONTH}\b",
    # Activities.
    r"\b(?:dinner|lunch|brunch|breakfast|drinks?|coffee|beers?|pints?|tea)\b",
    r"\b(?:meet(?:ing|up)?|catch(?:ing)?[\s-]?up|hang(?:ing)?\s?out|get[\s-]together)\b",
    r"\b(?:party|parties|bbq|barbecue|picnic|birthday|wedding|celebration)\b",
    r"\b(?:movies?|film|cinema|concert|gig|show|theatre|theater|game|match|festival)\b",
    r"\b(?:gym|climb(?:ing)?|hike|run|yoga|class)\b",
    r"\b(?:appointment|appt|reservation|booked|booking|table\s+for|date\s+night)\b",
    r"\b(?:come\s+over|pick\s+(?:you|me)\s+up|see\s+you|swing\s+by|let'?s\s+go)\b",
]

_PLAN_HINT = re.compile("|".join(f"(?:{pattern})" for pattern in _PATTERNS), re.IGNORECASE)


def looks_like_plan(text: str) -> bool:
    """Whether a Message's text has a time, a date or an activity word in it."""
    return _PLAN_HINT.search(text) is not None
