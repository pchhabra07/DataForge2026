"""
EchoCoach — Coaching Logic

Decides what to correct and how to phrase the coaching feedback.
Fully offline rules engine: instant, deterministic, no API key needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("echocoach.coaching")


@dataclass
class CorrectionPlan:
    """What the coach will say and which words to model."""

    coaching_text: str  # The spoken feedback sentence
    words_to_model: list[str]  # Words to speak at normal + slow speed
    latency_ms: float = 0  # Time to generate this plan
    source: str = "rules"

    def to_dict(self) -> dict:
        return {
            "coachingText": self.coaching_text,
            "wordsToModel": self.words_to_model,
            "latencyMs": round(self.latency_ms, 1),
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Rules engine (instant, no API call)
# ---------------------------------------------------------------------------

_ENCOURAGEMENTS = [
    "Almost there!",
    "Good effort!",
    "Let's polish that up!",
    "You're getting closer!",
    "Nice try!",
]


def _next_encouragement() -> str:
    import random

    return random.choice(_ENCOURAGEMENTS)


def _generate_rules_correction(
    flagged_words: list[dict],
    reference_text: str,
) -> CorrectionPlan:
    """Fast, deterministic coaching — no API call needed."""
    t0 = time.perf_counter()

    words = [str(w.get("word", "")).strip() for w in flagged_words[:3] if isinstance(w, dict)]
    words = [w for w in words if w]  # Drop empties to avoid KeyError on bad input
    if not words:
        return CorrectionPlan(
            coaching_text="Great job! Your pronunciation sounds good.",
            words_to_model=[],
            latency_ms=(time.perf_counter() - t0) * 1000,
            source="rules",
        )

    encouragement = _next_encouragement()

    if len(words) == 1:
        coaching_text = (
            f"{encouragement} Let's work on the word '{words[0]}'. "
            f"Listen carefully and try to match it."
        )
    elif len(words) == 2:
        coaching_text = (
            f"{encouragement} Let's focus on '{words[0]}' and '{words[1]}'. "
            f"I'll say each one clearly for you."
        )
    else:
        word_list = ", ".join(f"'{w}'" for w in words[:-1]) + f", and '{words[-1]}'"
        coaching_text = (
            f"{encouragement} I noticed a few words that need attention: {word_list}. "
            f"Let me model them for you."
        )

    elapsed = (time.perf_counter() - t0) * 1000
    return CorrectionPlan(
        coaching_text=coaching_text,
        words_to_model=words,
        latency_ms=elapsed,
        source="rules",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_correction(
    flagged_words: list[dict],
    reference_text: str,
) -> CorrectionPlan:
    """Generate a coaching correction plan.

    Args:
        flagged_words: List of word dicts with 'word' and 'accuracyScore'.
        reference_text: The target sentence.

    Returns:
        A CorrectionPlan with coaching text and words to model.
    """
    if not flagged_words:
        return CorrectionPlan(
            coaching_text="Excellent pronunciation! You nailed that sentence.",
            words_to_model=[],
            source="rules",
        )

    return _generate_rules_correction(flagged_words, reference_text)
