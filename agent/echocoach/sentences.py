"""
EchoCoach — Target Sentence Bank (Reading Mode)

Curated practice sentences for pronunciation coaching.
Each sentence is tagged with a difficulty level and category.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetSentence:
    """A single target sentence for the user to read aloud."""

    id: int
    text: str
    difficulty: str  # "easy", "medium", "hard"
    category: str  # e.g. "general", "technical", "tongue-twister"


# ---------------------------------------------------------------------------
# Sentence bank — designed for clear pronunciation scoring
# Roughly ordered from easy to hard within each difficulty band
# ---------------------------------------------------------------------------
SENTENCES: list[TargetSentence] = [
    # Easy — common words, short sentences
    TargetSentence(
        id=1,
        text="The quick brown fox jumps over the lazy dog.",
        difficulty="easy",
        category="general",
    ),
    TargetSentence(
        id=2,
        text="Good morning, my name is Alex and I am happy to be here.",
        difficulty="easy",
        category="general",
    ),
    TargetSentence(
        id=3,
        text="Please remember to bring your notebook to the meeting.",
        difficulty="easy",
        category="general",
    ),
    # Medium — longer sentences, more syllables
    TargetSentence(
        id=4,
        text="The university library is an excellent resource for international students.",
        difficulty="medium",
        category="general",
    ),
    TargetSentence(
        id=5,
        text="Communication skills are particularly important for professional development.",
        difficulty="medium",
        category="general",
    ),
    TargetSentence(
        id=6,
        text="The temperature has been fluctuating considerably throughout the week.",
        difficulty="medium",
        category="general",
    ),
    # Hard — technical terms, tricky pronunciation
    TargetSentence(
        id=7,
        text="The pharmaceutical company developed an extraordinarily effective vaccine.",
        difficulty="hard",
        category="technical",
    ),
    TargetSentence(
        id=8,
        text="Statistical analysis revealed a significant correlation between the variables.",
        difficulty="hard",
        category="technical",
    ),
    TargetSentence(
        id=9,
        text="She sells seashells by the seashore, and the shells she sells are seashells.",
        difficulty="hard",
        category="tongue-twister",
    ),
    TargetSentence(
        id=10,
        text="The entrepreneur's innovative algorithm revolutionized the manufacturing process.",
        difficulty="hard",
        category="technical",
    ),
]


def get_sentence(sentence_id: int) -> TargetSentence | None:
    """Get a sentence by ID."""
    for s in SENTENCES:
        if s.id == sentence_id:
            return s
    return None


def get_sentence_by_index(index: int) -> TargetSentence:
    """Get a sentence by list index (wraps around)."""
    return SENTENCES[index % len(SENTENCES)]


def get_first_sentence() -> TargetSentence:
    """Get the first (default) sentence."""
    return SENTENCES[0]


def get_next_sentence(current_id: int) -> TargetSentence:
    """Get the next sentence after the given ID (wraps around)."""
    for i, s in enumerate(SENTENCES):
        if s.id == current_id:
            return SENTENCES[(i + 1) % len(SENTENCES)]
    return SENTENCES[0]


def get_all_sentences() -> list[TargetSentence]:
    """Return all available sentences."""
    return list(SENTENCES)
