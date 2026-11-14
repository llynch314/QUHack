"""Spot urgent situations in chat so a patient's family can be alerted.

Crisis language uses the same patterns as the chatbot's crisis panel (prompts).
Panic attacks and meltdowns are extra keyword checks. This is a hackathon-level
heuristic, not a clinical tool, and it errs on the side of flagging.
"""
import re

from prompts import mentions_crisis

_PATTERNS = {
    'panic_attack': [
        r'\bpanic attack', r'\bpanicking\b', r"\bcan'?t breathe\b", r'\bhyperventilat',
        r'\bheart (is )?(racing|pounding)\b', r'\bchest (is |feels )?tight',
    ],
    'meltdown': [
        r'\bmelt ?down\b', r'\bbreaking down\b', r"\bcan'?t cope\b", r'\bfalling apart\b',
        r'\blosing (it|control)\b', r"\bcan'?t (take|handle) (it|this) anymore\b",
    ],
}
_COMPILED = {kind: re.compile('|'.join(p), re.IGNORECASE) for kind, p in _PATTERNS.items()}

# What family members see. Never includes what the patient wrote.
ALERT_NOTES = {
    'crisis': 'AttuneMIND noticed signs of a crisis. Please check in with them now.',
    'panic_attack': 'AttuneMIND noticed signs of a panic attack. Please check in with them.',
    'meltdown': 'AttuneMIND noticed signs of a meltdown. Please check in with them.',
}


def detect_urgent(text):
    """Return 'crisis', 'panic_attack', 'meltdown' or None. Crisis is checked first."""
    if not text:
        return None
    if mentions_crisis(text):
        return 'crisis'
    for kind, pattern in _COMPILED.items():
        if pattern.search(text):
            return kind
    return None
