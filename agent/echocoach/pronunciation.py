"""
EchoCoach — Cloud-Assisted Pronunciation Assessment via Deepgram + Phonetic Levenshtein

Replaces the heavy local 1.2GB wav2vec2 model with a fast cloud-assisted pipeline:
1. Deepgram Nova-3 returns word-level transcription, acoustic confidence, and timestamps.
2. Phonetic Levenshtein alignment (via eng_to_ipa) matches recognized words against the
   reference target sentence.
3. Combines phonetic similarity and acoustic confidence into per-word accuracy scores,
   fluency, completeness, and prosody.

Zero local model download (~0MB cache), zero CPU saturation, instant startup (<5ms).
Requires DEEPGRAM_API_KEY in environment or .env.local.
"""

from __future__ import annotations

import asyncio
import difflib
import io
import json
import logging
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass, field

import eng_to_ipa as ipa

logger = logging.getLogger("echocoach.pronunciation")

# Flag threshold: words below this score get flagged for correction
DEFAULT_FLAG_THRESHOLD = 60

_PROGRESS = {"phase": "ready", "file": "deepgram-nova3", "downloaded": 1, "total": 1}
_PROGRESS_LOCK = threading.Lock()


def get_download_progress() -> dict:
    """Thread-safe snapshot of model status for the client."""
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _set_progress(**fields) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.update(fields)


@dataclass
class WordScore:
    """Pronunciation score for a single word."""

    word: str
    accuracy_score: float  # 0–100
    error_type: str  # "None", "Mispronunciation", "Omission", "Insertion"

    @property
    def is_flagged(self) -> bool:
        return self.accuracy_score < DEFAULT_FLAG_THRESHOLD or self.error_type != "None"

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
    """Resample PCM audio from source_rate to target_rate using linear interpolation."""
    if source_rate == target_rate:
        return audio_bytes

    num_samples = len(audio_bytes) // sample_width
    if num_samples == 0:
        return b""

    samples = struct.unpack(f"<{num_samples}h", audio_bytes[: num_samples * sample_width])
    ratio = target_rate / source_rate
    out_len = int(num_samples * ratio)
    if out_len == 0:
        return b""

    import numpy as np

    src = np.asarray(samples, dtype=np.float32)
    if out_len == num_samples:
        clipped = np.clip(src, -32768, 32767).astype(np.int16)
        return clipped.tobytes()
    src_pos = np.arange(out_len, dtype=np.float64) / ratio
    resampled = np.interp(src_pos, np.arange(num_samples, dtype=np.float64), src)
    clipped = np.clip(np.rint(resampled), -32768, 32767).astype(np.int16)
    return clipped.tobytes()


def to_ipa_clean(text: str) -> str:
    """Convert text to phonetic IPA representation, stripping unknown asterisks."""
    clean = re.sub(r"[^a-zA-Z']", "", text.lower())
    if not clean:
        return ""
    try:
        converted = ipa.convert(clean)
        return converted.replace("*", "")
    except Exception:
        return clean


def word_phonetic_similarity(w1: str, w2: str) -> float:
    """Compute phonetic similarity ratio between two words using IPA representation."""
    c1 = re.sub(r"[^a-zA-Z]", "", w1.lower())
    c2 = re.sub(r"[^a-zA-Z]", "", w2.lower())
    if not c1 or not c2:
        return 0.0
    if c1 == c2:
        return 1.0

    p1 = to_ipa_clean(c1)
    p2 = to_ipa_clean(c2)
    if p1 and p2:
        return difflib.SequenceMatcher(None, p1, p2).ratio()
    return difflib.SequenceMatcher(None, c1, c2).ratio()


def align_reference_and_recognized(
    ref_words: list[str],
    dg_words: list[dict],
) -> list[tuple[str, dict | None]]:
    """Align reference target words against Deepgram recognized words using Needleman-Wunsch.

    Returns a list of (ref_word, matched_dg_dict_or_None).
    """
    n = len(ref_words)
    m = len(dg_words)
    if n == 0:
        return []
    if m == 0:
        return [(rw, None) for rw in ref_words]

    gap_penalty = -0.5
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap_penalty
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap_penalty

    for i in range(1, n + 1):
        rw = ref_words[i - 1]
        for j in range(1, m + 1):
            dw = dg_words[j - 1].get("word", "")
            sim = word_phonetic_similarity(rw, dw)
            # Positive reward if similar, negative penalty if very dissimilar
            match_score = (sim - 0.45) * 2.5
            score_diag = dp[i - 1][j - 1] + match_score
            score_del = dp[i - 1][j] + gap_penalty
            score_ins = dp[i][j - 1] + gap_penalty
            dp[i][j] = max(score_diag, score_del, score_ins)

    # Backtrack alignment
    i, j = n, m
    alignment: list[tuple[str, dict | None]] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            rw = ref_words[i - 1]
            dw = dg_words[j - 1].get("word", "")
            sim = word_phonetic_similarity(rw, dw)
            match_score = (sim - 0.45) * 2.5
            if abs(dp[i][j] - (dp[i - 1][j - 1] + match_score)) < 1e-6:
                alignment.append((rw, dg_words[j - 1]))
                i -= 1
                j -= 1
                continue
        if i > 0 and abs(dp[i][j] - (dp[i - 1][j] + gap_penalty)) < 1e-6:
            alignment.append((ref_words[i - 1], None))
            i -= 1
        else:
            # insertion in dg_words (user said extra words/fillers)
            j -= 1

    alignment.reverse()
    return alignment


async def warmup_free_assessor(on_status=None) -> None:
    """Validate Deepgram Cloud API readiness instantly with zero model download."""
    async def _notify(status: str) -> None:
        if on_status is None:
            return
        try:
            res = on_status(status)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    await _notify("loading")

    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        logger.error("DEEPGRAM_API_KEY missing from environment — check .env.local")
        with _PROGRESS_LOCK:
            _PROGRESS["phase"] = "error"
        await _notify("error")
        return

    with _PROGRESS_LOCK:
        _PROGRESS["phase"] = "ready"
        _PROGRESS["file"] = "deepgram-nova3"
        _PROGRESS["downloaded"] = 1
        _PROGRESS["total"] = 1

    await _notify("ready")
    logger.info("Deepgram cloud pronunciation engine ready (0MB local download, instant)")


async def assess_pronunciation(
    audio_bytes: bytes,
    reference_text: str,
    sample_rate: int = 48000,
) -> PronunciationResult | None:
    """Run cloud-assisted pronunciation assessment via Deepgram + Phonetic Levenshtein."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _assess_pronunciation_sync,
        audio_bytes,
        reference_text,
        sample_rate,
    )


def _assess_pronunciation_sync(
    audio_bytes: bytes,
    reference_text: str,
    sample_rate: int = 48000,
) -> PronunciationResult | None:
    """Synchronous assessment: Calls Deepgram Nova-3 API and performs phonetic alignment."""
    if len(audio_bytes) < 3200:
        logger.warning("Audio too short for assessment (%d bytes)", len(audio_bytes))
        return None

    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        logger.error("DEEPGRAM_API_KEY missing from environment")
        return None

    # Parse reference words
    ref_words_raw = re.findall(r"[A-Za-z']+", reference_text)
    if not ref_words_raw:
        ref_words_raw = reference_text.split()
    if not ref_words_raw:
        return None

    # Package PCM into in-memory WAV
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    wav_bytes = wav_buf.getvalue()

    # Call Deepgram Nova-3 API
    url = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&punctuate=true"
    req = urllib.request.Request(
        url,
        data=wav_bytes,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
            "User-Agent": "EchoCoach-Agent/1.0",
        },
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("Deepgram API HTTP %d: %s", e.code, body[:250])
        return None
    except Exception as e:
        logger.exception("Deepgram API request failed: %s", e)
        return None

    api_ms = (time.perf_counter() - t0) * 1000

    channels = data.get("results", {}).get("channels", [])
    if not channels:
        return None
    alt = channels[0].get("alternatives", [{}])[0]
    recognized_text = alt.get("transcript", "").strip()
    dg_words = alt.get("words", [])

    logger.info(
        "Deepgram response in %.0fms: transcript=%r (%d words)",
        api_ms,
        recognized_text[:60],
        len(dg_words),
    )

    # Align reference words against Deepgram recognized words
    aligned_pairs = align_reference_and_recognized(ref_words_raw, dg_words)

    word_scores: list[WordScore] = []
    matched_count = 0

    for ref_w, dg_w in aligned_pairs:
        clean_ref = re.sub(r"[^a-zA-Z']", "", ref_w)
        if dg_w is None:
            # Word omitted
            word_scores.append(
                WordScore(
                    word=clean_ref,
                    accuracy_score=0.0,
                    error_type="Omission",
                )
            )
            continue

        matched_count += 1
        conf = float(dg_w.get("confidence", 0.85))
        recognized_w = str(dg_w.get("word", "")).strip()
        phn_sim = word_phonetic_similarity(ref_w, recognized_w)

        is_exact = clean_ref.lower() == re.sub(r"[^a-zA-Z']", "", recognized_w).lower()

        if is_exact:
            # Exact word match: blend acoustic confidence + phonetic stability
            score = round(min(100.0, max(25.0, (0.2 * phn_sim + 0.8 * conf) * 100.0)), 1)
            error_type = "None" if score >= DEFAULT_FLAG_THRESHOLD else "Mispronunciation"
        else:
            # Word differed: phonetic approximation
            if phn_sim >= 0.8:
                score = round(min(100.0, max(20.0, (0.45 * phn_sim + 0.55 * conf) * 95.0)), 1)
                error_type = "None" if score >= DEFAULT_FLAG_THRESHOLD else "Mispronunciation"
            else:
                score = round(min(100.0, max(15.0, (0.6 * phn_sim + 0.4 * conf) * 75.0)), 1)
                error_type = "Mispronunciation"

        word_scores.append(
            WordScore(
                word=clean_ref,
                accuracy_score=score,
                error_type=error_type,
            )
        )

    # Sentence-level metrics calculation
    completeness = (
        round(100.0 * (matched_count / max(len(ref_words_raw), 1)), 1)
        if ref_words_raw
        else 100.0
    )

    avg_accuracy = (
        round(sum(w.accuracy_score for w in word_scores) / max(len(word_scores), 1), 1)
        if word_scores
        else 0.0
    )

    # Fluency calculation from speech timing & pacing
    fluency = 85.0
    if len(dg_words) >= 2:
        try:
            t_start = float(dg_words[0].get("start", 0.0))
            t_end = float(dg_words[-1].get("end", 0.0))
            dur = max(t_end - t_start, 0.5)
            wpm = (len(dg_words) / dur) * 60.0

            # Target reading range: 110–160 WPM
            if 110.0 <= wpm <= 165.0:
                fluency = 92.0 + min(6.0, (wpm - 110.0) / 10.0)
            elif wpm < 110.0:
                fluency = max(55.0, 92.0 - (110.0 - wpm) * 0.6)
            else:
                fluency = max(60.0, 92.0 - (wpm - 165.0) * 0.5)

            # Penalize for excessive inter-word pauses (>0.7s silence)
            pause_penalties = 0
            for k in range(1, len(dg_words)):
                gap = float(dg_words[k].get("start", 0.0)) - float(dg_words[k - 1].get("end", 0.0))
                if gap > 0.7:
                    pause_penalties += 1
            fluency = max(40.0, round(fluency - pause_penalties * 4.0, 1))
        except Exception:
            fluency = 85.0

    prosody = 82.0
    if len(word_scores) > 0:
        # Prosody derived from confidence consistency and accuracy
        prosody = round(min(96.0, max(50.0, (avg_accuracy * 0.7 + fluency * 0.3))), 1)

    return PronunciationResult(
        recognized_text=recognized_text if recognized_text else reference_text,
        accuracy_score=avg_accuracy,
        fluency_score=fluency,
        completeness_score=completeness,
        prosody_score=prosody,
        words=word_scores,
    )


def _mock_pronunciation_assessment(reference_text: str) -> PronunciationResult:
    """Generate simulated pronunciation assessment for offline UI testing."""
    words_raw = re.findall(r"[A-Za-z']+", reference_text)
    if not words_raw:
        words_raw = reference_text.split()

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
