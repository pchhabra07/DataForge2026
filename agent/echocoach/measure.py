"""
EchoCoach — Session Metrics Accumulator

Tracks running averages for pipeline latencies and counts
across a single coaching session. Used for Phase 6 measurement
and RIME_EVIDENCE.md reporting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MetricsSample:
    """A single pipeline measurement."""

    assessment_ms: float = 0.0
    correction_ms: float = 0.0
    total_pipeline_ms: float = 0.0
    interruption_ms: float = 0.0
    flagged_word_count: int = 0
    correction_source: str = "rules"
    is_cached: bool = False


@dataclass
class SessionMetrics:
    """Accumulates metrics across a session for averaging and reporting."""

    samples: list[MetricsSample] = field(default_factory=list)
    interruption_samples: list[float] = field(default_factory=list)
    session_start: float = field(default_factory=time.perf_counter)

    def record(self, sample: MetricsSample) -> None:
        """Record a pipeline measurement."""
        self.samples.append(sample)

    def record_interruption(self, stop_ms: float) -> None:
        """Record an interruption stop time."""
        self.interruption_samples.append(stop_ms)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def avg_assessment_ms(self) -> float:
        vals = [s.assessment_ms for s in self.samples if s.assessment_ms > 0]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_correction_ms(self) -> float:
        vals = [s.correction_ms for s in self.samples if s.correction_ms > 0]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_total_pipeline_ms(self) -> float:
        vals = [s.total_pipeline_ms for s in self.samples if s.total_pipeline_ms > 0]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def avg_interruption_ms(self) -> float:
        if not self.interruption_samples:
            return 0.0
        return sum(self.interruption_samples) / len(self.interruption_samples)

    @property
    def total_flagged_words(self) -> int:
        return sum(s.flagged_word_count for s in self.samples)

    @property
    def session_elapsed_s(self) -> float:
        return time.perf_counter() - self.session_start

    def to_dict(self) -> dict:
        """Return full session metrics summary."""
        return {
            "attemptCount": self.count,
            "avgAssessmentMs": round(self.avg_assessment_ms, 1),
            "avgCorrectionMs": round(self.avg_correction_ms, 1),
            "avgTotalPipelineMs": round(self.avg_total_pipeline_ms, 1),
            "avgInterruptionMs": round(self.avg_interruption_ms, 1),
            "interruptionCount": len(self.interruption_samples),
            "totalFlaggedWords": self.total_flagged_words,
            "sessionElapsedS": round(self.session_elapsed_s, 1),
        }

    def latest_dict(self) -> dict:
        """Return metrics for the most recent sample (for per-attempt sending)."""
        if not self.samples:
            return {}
        s = self.samples[-1]
        d: dict = {
            "assessmentLatencyMs": round(s.assessment_ms, 1),
            "correctionLatencyMs": round(s.correction_ms, 1),
            "totalPipelineMs": round(s.total_pipeline_ms, 1),
            "correctionSource": s.correction_source,
            "flaggedWordCount": s.flagged_word_count,
            "isCached": s.is_cached,
            "attemptNumber": self.count,
        }
        if self.interruption_samples:
            d["lastInterruptionMs"] = round(self.interruption_samples[-1], 1)
        # Include running averages
        d["avgAssessmentMs"] = round(self.avg_assessment_ms, 1)
        d["avgCorrectionMs"] = round(self.avg_correction_ms, 1)
        d["avgTotalPipelineMs"] = round(self.avg_total_pipeline_ms, 1)
        d["avgInterruptionMs"] = round(self.avg_interruption_ms, 1)
        return d
