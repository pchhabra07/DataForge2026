"""
EchoCoach — Azure Pronunciation Assessment

Integrates with Azure Speech SDK to evaluate pronunciation quality.
Takes raw PCM audio + reference text, returns per-word accuracy scores.

Audio requirements: 16kHz, 16-bit, mono PCM (standard for Azure Speech).
LiveKit typically delivers 48kHz — we resample before sending.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
from dataclasses import dataclass, field

logger = logging.getLogger("echocoach.pronunciation")

# Flag threshold: words below this score get flagged for correction
DEFAULT_FLAG_THRESHOLD = 60


@dataclass
class WordScore:
    """Pronunciation score for a single word."""

    word: str
    accuracy_score: float  # 0–100
    error_type: str  # "None", "Mispronunciation", "Omission", "Insertion"

    @property
    def is_flagged(self) -> bool:
        return (
            self.accuracy_score < DEFAULT_FLAG_THRESHOLD
            or self.error_type == "Mispronunciation"
        )

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

    samples = struct.unpack(f"<{num_samples}h", audio_bytes[:num_samples * sample_width])

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
    """Run Azure Pronunciation Assessment on raw PCM audio.

    Args:
        audio_bytes: Raw PCM audio (16-bit signed LE, mono).
        reference_text: The target sentence the user was reading.
        sample_rate: Sample rate of the input audio (will resample to 16kHz).

    Returns:
        PronunciationResult with per-word scores, or None on failure.
    """
    # Run the blocking Azure SDK call in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _assess_pronunciation_sync,
        audio_bytes,
        reference_text,
        sample_rate,
    )


def _mock_pronunciation_assessment(reference_text: str) -> PronunciationResult:
    """Generate a realistic simulated pronunciation assessment when Azure Speech is not set.

    Allows running and testing the complete UI and coaching loop without an Azure API key.
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
    speech_key = (os.environ.get("AZURE_SPEECH_KEY") or "").strip()
    speech_region = (os.environ.get("AZURE_SPEECH_REGION") or "eastus").strip()

    # If Azure Speech is not configured, provide simulated assessment for testing
    if not speech_key or speech_key.startswith("your_"):
        logger.info(
            "AZURE_SPEECH_KEY not configured — using simulated pronunciation assessment (demo mode)"
        )
        return _mock_pronunciation_assessment(reference_text)

    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        logger.error(
            "azure-cognitiveservices-speech not installed. "
            "Run: pip install azure-cognitiveservices-speech"
        )
        return None

    if len(audio_bytes) < 3200:  # less than ~100ms at 16kHz
        logger.warning("Audio too short for pronunciation assessment (%d bytes)", len(audio_bytes))
        return None

    # Resample to 16kHz for Azure
    pcm_16k = resample_pcm(audio_bytes, source_rate=sample_rate, target_rate=16000)
    if len(pcm_16k) == 0:
        logger.warning("Resampled audio is empty")
        return None

    logger.info(
        "Running pronunciation assessment: %d bytes PCM → %d bytes @16kHz, ref=%r",
        len(audio_bytes),
        len(pcm_16k),
        reference_text[:60],
    )

    try:
        # Set up Azure Speech config
        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key,
            region=speech_region,
        )
        speech_config.speech_recognition_language = "en-US"

        # Create push audio stream (16kHz, 16-bit, mono)
        stream_format = speechsdk.audio.AudioStreamFormat.get_wave_format_pcm(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

        # Create recognizer
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # Configure pronunciation assessment
        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True,
        )
        pron_config.enable_prosody_assessment()
        pron_config.apply_to(recognizer)

        # Start recognition and push data
        result_future = recognizer.recognize_once_async()

        # Push audio in chunks to avoid blocking
        chunk_size = 32000  # ~1 second at 16kHz/16-bit
        for offset in range(0, len(pcm_16k), chunk_size):
            push_stream.write(pcm_16k[offset : offset + chunk_size])
        push_stream.close()

        # Get result (blocking)
        result = result_future.get()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return _parse_result(result, reference_text)
        elif result.reason == speechsdk.ResultReason.NoMatch:
            logger.warning("Azure Speech: no match — audio may not contain clear speech")
            return None
        else:
            cancellation = result.cancellation_details
            logger.error(
                "Azure Speech assessment failed: reason=%s, error=%s",
                cancellation.reason if cancellation else "unknown",
                cancellation.error_details if cancellation else "unknown",
            )
            return None

    except Exception:
        logger.exception("Pronunciation assessment error")
        return None


def _parse_result(result, reference_text: str) -> PronunciationResult:
    """Parse Azure Speech SDK result into our PronunciationResult structure."""
    import azure.cognitiveservices.speech as speechsdk

    pron_result = speechsdk.PronunciationAssessmentResult(result)

    # Extract per-word scores from the JSON response
    words: list[WordScore] = []
    json_str = result.properties.get(
        speechsdk.PropertyId.SpeechServiceResponse_JsonResult
    )

    if json_str:
        try:
            json_data = json.loads(json_str)
            nbest = json_data.get("NBest", [])
            if nbest:
                best = nbest[0]
                pa_words = best.get("PronunciationAssessment", {}).get("Words", [])
                # If Words not at that path, try the Words key directly
                if not pa_words:
                    pa_words = best.get("Words", [])
                for w in pa_words:
                    pa = w.get("PronunciationAssessment", {})
                    words.append(
                        WordScore(
                            word=w.get("Word", ""),
                            accuracy_score=pa.get("AccuracyScore", 0),
                            error_type=pa.get("ErrorType", "None"),
                        )
                    )
        except (json.JSONDecodeError, KeyError, IndexError):
            logger.warning("Failed to parse per-word scores from JSON response")

    return PronunciationResult(
        recognized_text=result.text or "",
        accuracy_score=pron_result.accuracy_score or 0,
        fluency_score=pron_result.fluency_score or 0,
        completeness_score=pron_result.completeness_score or 0,
        prosody_score=getattr(pron_result, "prosody_score", 0) or 0,
        words=words,
    )
