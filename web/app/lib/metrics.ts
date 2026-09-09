export const FILLER_WORDS: readonly string[] = ["um", "uh", "like", "er", "ah", "hmm"];

export function countWords(text: string): number {
  const tokens = text.trim().split(/\s+/).filter((t) => t.length > 0);
  return tokens.length;
}

export function normalizeFillerWord(token: string): string | null {
  const cleaned = token.toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "");
  if (FILLER_WORDS.includes(cleaned)) {
    return cleaned;
  }
  if (/^u+m+$/.test(cleaned)) {
    return "um";
  }
  if (/^u+h+$/.test(cleaned)) {
    return "uh";
  }
  if (/^h+m+$/.test(cleaned)) {
    return "hmm";
  }
  if (/^e+r+m?$/.test(cleaned)) {
    return "er";
  }
  if (/^a+h+$/.test(cleaned)) {
    return "ah";
  }
  return null;
}

export function countFillers(text: string): number {
  const tokens = text.trim().split(/\s+/).filter((t) => t.length > 0);
  let count = 0;
  for (const token of tokens) {
    if (normalizeFillerWord(token) !== null) {
      count += 1;
    }
  }
  return count;
}

export function computeWpm(wordCount: number, elapsedMs: number): number {
  if (elapsedMs <= 0) {
    return 0;
  }
  return Math.round((wordCount * 60000) / elapsedMs);
}

export interface TranscriptLine {
  id: string;
  text: string;
  isFinal: boolean;
  receivedAt: number;
}

export function upsertLine(lines: TranscriptLine[], line: TranscriptLine): TranscriptLine[] {
  const next = [...lines];
  const index = next.findIndex((l) => l.id === line.id);
  if (index >= 0) {
    const prev = next[index];
    next[index] =
      line.text.trim().length === 0 && prev.text.trim().length > 0
        ? { ...line, text: prev.text }
        : line;
  } else {
    next.push(line);
  }
  return next.length > 50 ? next.slice(next.length - 50) : next;
}

export function summarize(lines: TranscriptLine[]): { words: number; fillers: number; wpm: number } {
  const finals = lines.filter((l) => l.isFinal);
  let words = 0;
  let fillers = 0;
  for (const line of finals) {
    words += countWords(line.text);
    fillers += countFillers(line.text);
  }
  if (finals.length === 0) {
    return { words: 0, fillers: 0, wpm: 0 };
  }
  const end = finals[finals.length - 1].receivedAt;
  const window = finals.filter((l) => end - l.receivedAt <= 30000);
  const span = window.length >= 2 ? window : finals;
  if (span.length < 2) {
    return { words, fillers, wpm: 0 };
  }
  const elapsed = span[span.length - 1].receivedAt - span[0].receivedAt;
  if (elapsed < 2000) {
    return { words, fillers, wpm: 0 };
  }
  let spanWords = 0;
  for (const line of span) {
    spanWords += countWords(line.text);
  }
  return { words, fillers, wpm: Math.min(computeWpm(spanWords, elapsed), 300) };
}

// ---------------------------------------------------------------------------
// Phase 6: Pipeline metrics accumulator (client-side)
// ---------------------------------------------------------------------------

export interface PipelineSnapshot {
  assessmentLatencyMs: number;
  correctionLatencyMs: number;
  totalPipelineMs: number;
  correctionSource: string;
  flaggedWordCount: number;
  isCached: boolean;
  attemptNumber: number;
  lastInterruptionMs?: number;
  avgAssessmentMs: number;
  avgCorrectionMs: number;
  avgTotalPipelineMs: number;
  avgInterruptionMs: number;
}

export function toPipelineSnapshot(raw: Record<string, unknown>): PipelineSnapshot {
  const num = (k: string, fallback = 0) => {
    const v = raw[k];
    return typeof v === "number" && Number.isFinite(v) ? v : fallback;
  };
  const str = (k: string, fallback = "") => {
    const v = raw[k];
    return typeof v === "string" ? v : fallback;
  };
  return {
    assessmentLatencyMs: num("assessmentLatencyMs"),
    correctionLatencyMs: num("correctionLatencyMs"),
    totalPipelineMs: num("totalPipelineMs"),
    correctionSource: str("correctionSource", "rules"),
    flaggedWordCount: num("flaggedWordCount"),
    isCached: raw.isCached === true,
    attemptNumber: num("attemptNumber", 1),
    lastInterruptionMs: raw.lastInterruptionMs != null ? num("lastInterruptionMs") : undefined,
    avgAssessmentMs: num("avgAssessmentMs"),
    avgCorrectionMs: num("avgCorrectionMs"),
    avgTotalPipelineMs: num("avgTotalPipelineMs"),
    avgInterruptionMs: num("avgInterruptionMs"),
  };
}

// ---------------------------------------------------------------------------
// Phase 6: Session timer formatter
// ---------------------------------------------------------------------------

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

