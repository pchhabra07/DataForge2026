"""
EchoCoach — Free On-Device Pronunciation Assessment

Uses the open-source pronounce-assess engine (wav2vec2 phoneme model, MIT)
to evaluate pronunciation quality with zero API cost and no key.
Takes raw PCM audio + reference text, returns per-word accuracy scores.

Audio requirements: 16kHz mono float32 for the engine (resampled in-house).
LiveKit typically delivers 48kHz — we resample before sending.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import struct
import threading
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger("echocoach.pronunciation")

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Flag threshold: words below this score get flagged for correction
DEFAULT_FLAG_THRESHOLD = 60

_MODEL_LOCK = threading.RLock()
_SCORER = None


@dataclass
class WordScore:
    """Pronunciation score for a single word."""

    word: str
    accuracy_score: float  # 0–100
    error_type: str  # "None", "Mispronunciation", "Omission", "Insertion"

    @property
    def is_flagged(self) -> bool:
        return self.accuracy_score < DEFAULT_FLAG_THRESHOLD or self.error_type == "Mispronunciation"

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "accuracyScore": self.accuracy_score,
            "errorType": self.error_type,
            "isFlagged": self.is_flagged,
        }


@dataclass
class PronunciationResult:
    """Full pronunciation assessment result for a sentence."""

    recognized_text: str
    accuracy_score: float  # 0–100, sentence-level
    fluency_score: float
    completeness_score: float
    prosody_score: float
    words: list[WordScore] = field(default_factory=list)

    @property
    def flagged_words(self) -> list[WordScore]:
        return [w for w in self.words if w.is_flagged]

    @property
    def has_issues(self) -> bool:
        return len(self.flagged_words) > 0

    def to_dict(self) -> dict:
        return {
            "recognizedText": self.recognized_text,
            "accuracyScore": self.accuracy_score,
            "fluencyScore": self.fluency_score,
            "completenessScore": self.completeness_score,
            "prosodyScore": self.prosody_score,
            "words": [w.to_dict() for w in self.words],
            "flaggedWords": [w.to_dict() for w in self.flagged_words],
            "hasIssues": self.has_issues,
        }


def resample_pcm(
    audio_bytes: bytes,
    source_rate: int,
    target_rate: int = 16000,
    sample_width: int = 2,
) -> bytes:
    """Resample PCM audio from source_rate to target_rate using linear interpolation.

    This is a simple resampler suitable for speech assessment. For production,
    consider using a proper DSP library.

    Args:
        audio_bytes: Raw PCM bytes (16-bit signed LE mono).
        source_rate: Original sample rate (e.g. 48000).
        target_rate: Desired sample rate (default 16000).
        sample_width: Bytes per sample (default 2 for 16-bit).

    Returns:
        Resampled PCM bytes at target_rate.
    """
    if source_rate == target_rate:
        return audio_bytes

    # Unpack 16-bit signed samples
    num_samples = len(audio_bytes) // sample_width
    if num_samples == 0:
        return b""

    samples = struct.unpack(f"<{num_samples}h", audio_bytes[: num_samples * sample_width])

    # Calculate output size
    ratio = target_rate / source_rate
    out_len = int(num_samples * ratio)
    if out_len == 0:
        return b""

    # Linear interpolation resample
    resampled = []
    for i in range(out_len):
        src_pos = i / ratio
        idx = int(src_pos)
        frac = src_pos - idx
        if idx + 1 < num_samples:
            val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
        else:
            val = samples[min(idx, num_samples - 1)]
        resampled.append(int(max(-32768, min(32767, val))))

    return struct.pack(f"<{len(resampled)}h", *resampled)


async def assess_pronunciation(
    audio_bytes: bytes,
    reference_text: str,
    sample_rate: int = 48000,
) -> PronunciationResult | None:
    """Run on-device pronunciation assessment on raw PCM audio.

    Args:
        audio_bytes: Raw PCM audio (16-bit signed LE, mono).
        reference_text: The target sentence the user was reading.
        sample_rate: Sample rate of the input audio (will resample to 16kHz).

    Returns:
        PronunciationResult with per-word scores, or None on failure.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _assess_pronunciation_sync,
        audio_bytes,
        reference_text,
        sample_rate,
    )


async def warmup_free_assessor() -> None:
    """Preload the scoring model in the background so the first attempt is fast."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _get_scorer)
    except Exception:
        logger.exception("Pronunciation model warmup failed, first attempt will load it")


def _get_scorer():
    """Load the phoneme scoring model once and reuse it for every attempt."""
    global _SCORER
    if _SCORER is not None:
        return _SCORER
    with _MODEL_LOCK:
        if _SCORER is not None:
            return _SCORER
        import time

        from pronounce_assess.models import PronounceAssessModel

        t0 = time.perf_counter()
        _SCORER = PronounceAssessModel(device="cpu")
        logger.info("Pronunciation model loaded in %.1fs", time.perf_counter() - t0)
        return _SCORER


def _mock_pronunciation_assessment(reference_text: str) -> PronunciationResult:
    """Generate a realistic simulated pronunciation assessment for UI tests.

    Allows running and testing the complete UI and coaching loop without audio.
    """
    import re

    words_raw = re.findall(r"\b[\w'-]+\b", reference_text)
    if not words_raw:
        words_raw = reference_text.split()

    # Select a candidate word to flag (prefer longer words with len >= 5)
    flag_idx = -1
    max_len = 0
    for idx, w in enumerate(words_raw):
        clean_w = w.strip(".,!?:;\"'")
        if len(clean_w) > max_len and len(clean_w) >= 5:
            max_len = len(clean_w)
            flag_idx = idx

    if flag_idx == -1 and words_raw:
        flag_idx = len(words_raw) // 2

    word_scores: list[WordScore] = []
    for idx, w in enumerate(words_raw):
        clean_w = w.strip(".,!?:;\"'")
        if idx == flag_idx:
            word_scores.append(
                WordScore(
                    word=clean_w,
                    accuracy_score=52.0,
                    error_type="Mispronunciation",
                )
            )
        else:
            score = 86.0 + float((len(clean_w) * 7) % 11)
            word_scores.append(
                WordScore(
                    word=clean_w,
                    accuracy_score=score,
                    error_type="None",
                )
            )

    avg_acc = (
        sum(w.accuracy_score for w in word_scores) / max(len(word_scores), 1)
        if word_scores
        else 85.0
    )

    return PronunciationResult(
        recognized_text=reference_text,
        accuracy_score=round(avg_acc, 1),
        fluency_score=84.0,
        completeness_score=100.0,
        prosody_score=81.0,
        words=word_scores,
    )


def _assess_pronunciation_sync(
    audio_bytes: bytes,
    reference_text: str,
    sample_rate: int = 48000,
) -> PronunciationResult | None:
    """Synchronous pronunciation assessment — runs in executor thread."""
    import time

    from pronounce_assess import phonemes

    if len(audio_bytes) < 3200:
        logger.warning("Audio too short for pronunciation assessment (%d bytes)", len(audio_bytes))
        return None

    words_raw = re.findall(r"[A-Za-z']+", reference_text)
    if not words_raw:
        words_raw = reference_text.split()
    if not words_raw:
        return None

    pcm_16k = resample_pcm(audio_bytes, source_rate=sample_rate, target_rate=16000)
    if len(pcm_16k) < 3200:
        logger.warning("Resampled audio is empty")
        return None

    samples = np.frombuffer(pcm_16k, dtype=np.int16).astype(np.float32) / 32768.0

    logger.info(
        "Running free pronunciation assessment: %d bytes PCM, ref=%r",
        len(audio_bytes),
        reference_text[:60],
    )
    t0 = time.perf_counter()
    try:
        with _MODEL_LOCK:
            scorer = _get_scorer()
            scorer.set_sentence(reference_text)
            raw_events = list(scorer.stream_decode(iter([samples])))
    except Exception:
        logger.exception("Free pronunciation assessment failed")
        return None
    score_ms = (time.perf_counter() - t0) * 1000

    prosody = next((e for e in raw_events if e.label == "prosody"), None)
    events = [e for e in raw_events if e.label != "prosody"]

    processor = scorer.processor
    sentence_phns = list(scorer.reference_phonemes or [])
    word_phns = [phonemes.sentence_to_phonemes(w, processor) for w in words_raw]
    flat_concat = [p for wps in word_phns for p in wps]
    if flat_concat != sentence_phns:
        logger.warning(
            "Per-word phonemes diverge from sentence reference (%d vs %d), scores approximate",
            len(flat_concat),
            len(sentence_phns),
        )
    starts: list[int] = []
    acc = 0
    for wps in word_phns:
        starts.append(acc)
        acc += len(wps)

    scored_rows: list[tuple[str, float, str] | None] = []
    aligned_words = 0
    for w, wps, s in zip(words_raw, word_phns, starts):
        n = len(wps)
        if n == 0:
            scored_rows.append(None)
            continue
        by_pos = {}
        for e in events:
            if e.position is not None and s <= e.position < s + n:
                by_pos.setdefault(e.position, e)
        gops: list[float] = []
        labels: list[str] = []
        for k in range(n):
            e = by_pos.get(s + k)
            if e is None:
                gops.append(0.0)
                labels.append("omitted")
            else:
                labels.append(e.label)
                gops.append(float(e.gop) if e.gop is not None else float("nan"))
        valid = [g for g in gops if g == g]
        word_acc = round(100.0 * float(np.mean(valid)), 1) if valid else 0.0
        if any(label == "omitted" for label in labels):
            err: str = "Omission"
        elif any(label == "mispronounced" for label in labels):
            err = "Mispronunciation"
        else:
            err = "None"
        heard = sum(1 for label, g in zip(labels, gops) if label != "omitted" or g > 0)
        if heard * 2 >= n:
            aligned_words += 1
        scored_rows.append((w, word_acc, err))

    present = [r[1] for r in scored_rows if r is not None]
    sent_mean = round(float(np.mean(present)), 1) if present else 0.0
    word_scores = [
        WordScore(
            word=w,
            accuracy_score=(r[1] if r is not None else sent_mean),
            error_type=(r[2] if r is not None else "None"),
        )
        for w, r in zip(words_raw, scored_rows)
    ]

    phoneme_words = [w for w, wps in zip(words_raw, word_phns) if len(wps) > 0]
    completeness = (
        round(100.0 * aligned_words / max(len(phoneme_words), 1), 1) if phoneme_words else 0.0
    )
    rhythm = prosody.rhythm_score if prosody is not None else None
    boundary = prosody.boundary_score if prosody is not None else None
    fluency = round(100.0 * float(rhythm), 1) if rhythm is not None else sent_mean
    prosody_score = (
        round(100.0 * float(boundary), 1) if boundary is not None and float(boundary) > 0 else 0.0
    )

    logger.info(
        "Free assessment in %.0fms: accuracy=%.1f, flagged=%d words",
        score_ms,
        sent_mean,
        sum(1 for ws in word_scores if ws.is_flagged),
    )
    return PronunciationResult(
        recognized_text=reference_text,
        accuracy_score=sent_mean,
        fluency_score=fluency,
        completeness_score=completeness,
        prosody_score=prosody_score,
        words=word_scores,
    )
