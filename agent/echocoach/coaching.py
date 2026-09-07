"""
EchoCoach — Coaching Logic

Decides what to correct and how to phrase the coaching feedback.
Uses an LLM (OpenAI-compatible) for natural coaching phrasing,
with a fast rules-based fallback to keep latency low.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger("echocoach.coaching")


@dataclass
class CorrectionPlan:
    """What the coach will say and which words to model."""

    coaching_text: str  # The spoken feedback sentence
    words_to_model: list[str]  # Words to speak at normal + slow speed
    latency_ms: float = 0  # Time to generate this plan
    source: str = "rules"  # "llm" or "rules"

    def to_dict(self) -> dict:
        return {
            "coachingText": self.coaching_text,
            "wordsToModel": self.words_to_model,
            "latencyMs": round(self.latency_ms, 1),
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Rules-based fallback (instant, no API call)
# ---------------------------------------------------------------------------

_ENCOURAGEMENTS = [
    "Almost there!",
    "Good effort!",
    "Let's polish that up!",
    "You're getting closer!",
    "Nice try!",
]

_ENCOURAGEMENT_IDX = 0


def _next_encouragement() -> str:
    global _ENCOURAGEMENT_IDX
    e = _ENCOURAGEMENTS[_ENCOURAGEMENT_IDX % len(_ENCOURAGEMENTS)]
    _ENCOURAGEMENT_IDX += 1
    return e


def _generate_rules_correction(
    flagged_words: list[dict],
    reference_text: str,
) -> CorrectionPlan:
    """Fast, deterministic fallback — no API call needed."""
    t0 = time.perf_counter()

    words = [w["word"] for w in flagged_words[:3]]  # Limit to top 3
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
# LLM-based coaching (richer, more natural)
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are EchoCoach, a warm and encouraging speaking coach.
The user just read a sentence aloud and some words were mispronounced.
Generate a SHORT coaching response (1-2 sentences max) that:
1. Acknowledges their effort positively
2. Names the specific word(s) to work on
3. Tells them you'll model the correct pronunciation

Be conversational and warm — like a supportive tutor, not a grading machine.
Do NOT include phonetic spellings or IPA. Just name the words naturally.
Keep it under 30 words."""


async def _generate_llm_correction(
    flagged_words: list[dict],
    reference_text: str,
    timeout: float = 2.0,
) -> CorrectionPlan | None:
    """Generate coaching text via OpenAI LLM."""
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key or api_key.startswith("your_"):
        logger.info("OPENAI_API_KEY not configured — using fast rules-based coaching")
        return None

    words = [w["word"] for w in flagged_words[:3]]
    if not words:
        return None

    t0 = time.perf_counter()

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)

        word_details = ", ".join(
            f"'{w['word']}' (score: {w.get('accuracyScore', '?')})"
            for w in flagged_words[:3]
        )

        user_msg = (
            f"Target sentence: \"{reference_text}\"\n"
            f"Mispronounced words: {word_details}\n"
            f"Generate your coaching response."
        )

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=80,
                temperature=0.7,
            ),
            timeout=timeout,
        )

        coaching_text = response.choices[0].message.content or ""
        coaching_text = coaching_text.strip().strip('"')

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info("LLM coaching generated in %.0fms: %r", elapsed, coaching_text[:80])

        return CorrectionPlan(
            coaching_text=coaching_text,
            words_to_model=words,
            latency_ms=elapsed,
            source="llm",
        )

    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning("LLM coaching timed out after %.0fms, using rules fallback", elapsed)
        return None
    except Exception:
        logger.exception("LLM coaching generation failed")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_correction(
    flagged_words: list[dict],
    reference_text: str,
    use_llm: bool = True,
    llm_timeout: float = 2.0,
) -> CorrectionPlan:
    """Generate a coaching correction plan.

    Tries the LLM first for natural phrasing, falls back to rules if
    the LLM is slow or unavailable.

    Args:
        flagged_words: List of word dicts with 'word' and 'accuracyScore'.
        reference_text: The target sentence.
        use_llm: Whether to attempt LLM generation.
        llm_timeout: Max seconds to wait for LLM response.

    Returns:
        A CorrectionPlan with coaching text and words to model.
    """
    if not flagged_words:
        return CorrectionPlan(
            coaching_text="Excellent pronunciation! You nailed that sentence.",
            words_to_model=[],
            source="rules",
        )

    # Try LLM first
    if use_llm:
        plan = await _generate_llm_correction(
            flagged_words, reference_text, timeout=llm_timeout
        )
        if plan:
            return plan

    # Fallback to rules
    return _generate_rules_correction(flagged_words, reference_text)
