"""Guess the user's mood from a chat message, to color their aura.

Returns one of MOODS (the same ids as frontend/static/js/aura.js) or None when
nothing clear is said, so the aura keeps its current color. Keyword matching
with simple negation handling ("not angry" doesn't count): fast, free and
private, but only a rough guess. The text is never stored.
"""
import re

from safety import detect_urgent

MOODS = (
    'calm', 'peaceful', 'content', 'grateful',
    'happy', 'excited', 'hopeful', 'loved',
    'neutral', 'tired', 'sad', 'lonely', 'numb',
    'thoughtful', 'confused',
    'anxious', 'stressed', 'overwhelmed', 'frustrated', 'angry', 'scared', 'panic', 'hurting',
)

# Checked in this order: the first mood with a match wins, so stronger feelings come first.
_WORDS = [
    ('angry', r'angry|furious|mad|pissed|rage|raging|livid|hate (him|her|them|this|it|everyone)'),
    ('scared', r'scared|afraid|terrified|frightened|fearful'),
    ('overwhelmed', r'overwhelm\w*|too much|drowning|burn(ed|t)? out|burnout'),
    ('frustrated', r'frustrat\w*|annoy\w*|irritat\w*|fed up|sick of'),
    ('stressed', r'stress\w*|under pressure|tense|deadline\w*|swamped'),
    ('anxious', r'anxious|anxiety|nervous|worried|worry|worrying|on edge|uneasy|restless'),
    ('lonely', r'lonely|alone|isolated|left out|no one (cares|gets)|nobody (cares|gets)'),
    ('sad', r'sad|depressed|unhappy|miserable|heartbroken|crying|cried|upset|feeling blue|gloomy|hopeless|feeling down|so down|really down|feel down'),
    ('numb', r'numb|empty|nothing matters|don\'?t feel anything|blank'),
    ('tired', r'tired|exhausted|drained|sleepy|worn out|fatigued|no energy'),
    ('confused', r'confused|unsure|don\'?t know what to (do|think|feel)|mixed up|feel(ing)? lost'),
    ('loved', r'loved|cared for|supported|appreciated'),
    ('grateful', r'grateful|thankful|blessed'),
    ('excited', r'excited|thrilled|pumped|can\'?t wait|stoked'),
    ('hopeful', r'hopeful|optimistic|looking forward|getting better|better today'),
    ('happy', r'happy|glad|feel(ing)? (good|great|amazing|awesome|wonderful)|joy\w*|cheerful|(good|great) day'),
    ('peaceful', r'peaceful|at peace|serene|tranquil'),
    ('calm', r'calm|relaxed|chill|okay now|settled|grounded'),
    ('content', r'content|i\'?m (fine|alright|all right|ok|okay)|not (too )?bad|pretty good'),
    ('thoughtful', r'thinking|wondering|reflect\w*|pondering'),
]
_COMPILED = [(mood, re.compile(r'\b(?:' + words + r')\b', re.IGNORECASE)) for mood, words in _WORDS]
# "not", "can't", "never"... up to one word before the feeling word ("not really angry").
_NEGATION = re.compile(r"\b(not|never|no|isn'?t|aren'?t|wasn'?t|don'?t|doesn'?t|didn'?t|can'?t|cannot|couldn'?t|"
                       r"hardly|nor|without)\W+(?:\w+\W+)?$", re.IGNORECASE)

# Urgent situations (shared with the family-alert detector) override everything.
_URGENT = {'crisis': 'hurting', 'panic_attack': 'panic', 'meltdown': 'overwhelmed'}


def detect_mood(text):
    """Return a mood id from MOODS, or None if the message doesn't say how they feel."""
    if not text or not text.strip():
        return None
    urgent = detect_urgent(text)
    if urgent:
        return _URGENT[urgent]
    for mood, pattern in _COMPILED:
        for match in pattern.finditer(text):
            if not _NEGATION.search(text[:match.start()]):
                return mood
    return None
