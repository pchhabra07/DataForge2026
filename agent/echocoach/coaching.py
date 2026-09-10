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

# Openers rotate per severity so repeated attempts never read identical.
_SEVERE_OPENERS = [
    "That one needs real work.",
    "Let's rebuild those sounds.",
    "Time to slow down and fix this.",
]

_MODERATE_OPENERS = [
    "Almost there!",
    "Good effort!",
    "You're getting closer!",
]

_LIGHT_OPENERS = [
    "Nice try!",
    "Nearly perfect!",
    "Just a small polish needed.",
]


def _pick_opener(pool: list[str], key: str) -> str:
    """Deterministic pick from a pool so the same words give variety
    across attempts without pure randomness repeating."""
    if not key:
        return pool[0]
    h = 0
    for ch in key:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return pool[h % len(pool)]


def _generate_rules_correction(
    flagged_words: list[dict],
    reference_text: str,
) -> CorrectionPlan:
    """Fast, deterministic coaching — no API call needed.

    The note varies with severity so every attempt reads different:
    average flagged score under 40 is severe, under 60 moderate,
    anything above is a light touch-up. The opener pool plus the
    score number plus the word list all change with the attempt.
    """
    t0 = time.perf_counter()

    scored = []
    for w in flagged_words[:3]:
        if not isinstance(w, dict):
            continue
        word = str(w.get("word", "")).strip()
        if not word:
            continue
        try:
            score = float(w.get("accuracyScore", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        scored.append((word, score))
    words = [w for w, _ in scored]
    if not words:
        return CorrectionPlan(
            coaching_text="Great job! Your pronunciation sounds good.",
            words_to_model=[],
            latency_ms=(time.perf_counter() - t0) * 1000,
            source="rules",
        )

    avg = sum(s for _, s in scored) / max(len(scored), 1)
    worst_word, worst_score = min(scored, key=lambda p: p[1])
    key = "|".join(words)

    if avg < 40:
        opener = _pick_opener(_SEVERE_OPENERS, key)
    elif avg < 60:
        opener = _pick_opener(_MODERATE_OPENERS, key)
    else:
        opener = _pick_opener(_LIGHT_OPENERS, key)

    if len(words) == 1:
        coaching_text = (
            f"{opener} The word '{words[0]}' came out at {worst_score:.0f}. "
            f"Listen carefully and shape each sound, then repeat it back."
        )
    elif len(words) == 2:
        coaching_text = (
            f"{opener} Two words need work, averaging {avg:.0f}. "
            f"'{words[0]}' and '{words[1]}'. "
            f"I'll say each one clearly, starting with the weakest."
        )
    else:
        word_list = ", ".join(f"'{w}'" for w in words[:-1]) + f", and '{words[-1]}'"
        coaching_text = (
            f"{opener} {len(words)} words need attention, averaging {avg:.0f}: "
            f"{word_list}. '{worst_word}' is the weakest at {worst_score:.0f}. "
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
