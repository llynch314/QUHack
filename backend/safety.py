"""Simple keyword screening for urgent situations in chat messages.

This is a hackathon-level heuristic, not a clinical tool. It errs on the side
of flagging. Crisis language is checked first because it matters most.
"""
import re

_PATTERNS = {
    "crisis": [
        r"\bkill(ing)? myself\b", r"\bsuicid", r"\bend (it all|my life)\b",
        r"\bwant to die\b", r"\bdon'?t want to (live|be alive)\b",
        r"\bself[- ]?harm", r"\bhurt(ing)? myself\b", r"\bcut(ting)? myself\b",
    ],
    "panic_attack": [
        r"\bpanic attack", r"\bpanicking\b", r"\bcan'?t breathe\b",
        r"\bhyperventilat", r"\bheart (is )?(racing|pounding)\b", r"\bchest (is )?tight",
    ],
    "meltdown": [
        r"\bmelt ?down\b", r"\bbreaking down\b", r"\bcan'?t cope\b",
        r"\bfalling apart\b", r"\blosing (it|control)\b", r"\bcan'?t take (it|this) anymore\b",
    ],
}

CRISIS_RESOURCES = (
    "If you're in danger or thinking about ending your life, please reach out right now: "
    "call or text 988 (Suicide & Crisis Lifeline, US), text HOME to 741741 (Crisis Text Line), "
    "or call 911 if you're in immediate danger. You don't have to go through this alone."
)


def detect_urgent(text):
    """Return 'crisis', 'panic_attack', 'meltdown' or None."""
    lowered = text.lower()
    for kind, patterns in _PATTERNS.items():
        if any(re.search(p, lowered) for p in patterns):
            return kind
    return None
