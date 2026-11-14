"""Mood guesses for the aura (backend/mood.py).  Run: pytest  (from backend/)"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mood import MOODS, detect_mood  # noqa: E402


@pytest.mark.parametrize('text, mood', [
    ('I am so stressed about my exam', 'stressed'),
    ('I was really mad at my brother', 'angry'),
    ('Honestly I feel so lonely lately', 'lonely'),
    ('everything is too much', 'overwhelmed'),
    ("having a panic attack, I can't breathe", 'panic'),
    ('I want to die', 'hurting'),
    ("I don't feel anything", 'numb'),
    ('I feel good today', 'happy'),
    ('not angry just tired', 'tired'),
    ("I'm fine", 'content'),
])
def test_detects_feelings(text, mood):
    assert detect_mood(text) == mood


@pytest.mark.parametrize('text', [
    'good morning', 'thanks for the help', "I'm not really angry", "I can't calm down",
    'I lost my keys', 'what is grounding?', '', '   ',
])
def test_no_clear_feeling_keeps_current_aura(text):
    assert detect_mood(text) is None


def test_backend_moods_match_the_aura():
    """Every mood the server can send must exist in the aura's palette (and the other way round)."""
    js = (Path(__file__).resolve().parents[2] / 'frontend' / 'static' / 'js' / 'aura.js').read_text()
    aura_ids = set(re.findall(r"\{ id: '([a-z]+)'", js))
    assert aura_ids == set(MOODS)
