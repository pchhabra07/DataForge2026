"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useRoomContext,
  useTranscriptions,
  useVoiceAssistant,
  BarVisualizer,
} from "@livekit/components-react";
import { ConnectionState, RoomEvent } from "livekit-client";
import type { Participant, TranscriptionSegment } from "livekit-client";
import { summarize, upsertLine } from "./lib/metrics";
import type { TranscriptLine } from "./lib/metrics";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface TokenResponse {
  token: string;
  room: string;
  identity: string;
  url: string;
}

interface TargetSentence {
  id: number;
  text: string;
  difficulty: string;
  category: string;
}

interface WordScoreData {
  word: string;
  accuracyScore: number;
  errorType: string;
  isFlagged: boolean;
}

interface PronunciationData {
  recognizedText: string;
  accuracyScore: number;
  fluencyScore: number;
  completenessScore: number;
  prosodyScore: number;
  words: WordScoreData[];
  flaggedWords: WordScoreData[];
  hasIssues: boolean;
  assessmentLatencyMs?: number;
}

interface CoachingData {
  coachingText: string;
  wordsToModel: string[];
  latencyMs: number;
  source: string;
}

interface PipelineMetrics {
  totalPipelineMs: number;
  correctionLatencyMs: number;
}

type SessionState =
  | "connecting"
  | "listening"
  | "listening_active"
  | "assessing"
  | "coaching"
  | "idle";

const KNOWN_STATES: readonly SessionState[] = [
  "connecting",
  "listening",
  "listening_active",
  "assessing",
  "coaching",
  "idle",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toNumberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function toStringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function toWordList(value: unknown): WordScoreData[] {
  if (!Array.isArray(value)) return [];
  const out: WordScoreData[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    out.push({
      word: toStringValue(item.word, ""),
      accuracyScore: toNumberValue(item.accuracyScore, 0),
      errorType: toStringValue(item.errorType, "None"),
      isFlagged: item.isFlagged === true,
    });
  }
  return out;
}

function isAgentParticipant(p: Participant): boolean {
  if (p.identity === "echocoach") return true;
  if (p.identity.toLowerCase().includes("agent")) return true;
  return p.permissions?.canPublish === true;
}

function findAgent(
  participants: Iterable<Participant>
): Participant | undefined {
  const list = Array.from(participants);
  const exact = list.find((p) => p.identity === "echocoach");
  if (exact) return exact;
  return list.find((p) => p.permissions?.canPublish === true);
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------
export default function Home() {
  const [connectionDetails, setConnectionDetails] =
    useState<TokenResponse | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = useCallback(async () => {
    setIsConnecting(true);
    setError(null);
    try {
      const resp = await fetch("/api/token?room=echocoach-dev");
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.error || `HTTP ${resp.status}`);
      }
      const data: TokenResponse = await resp.json();
      setConnectionDetails(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect");
    } finally {
      setIsConnecting(false);
    }
  }, []);

  const handleDisconnect = useCallback(() => {
    setConnectionDetails(null);
  }, []);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="app-logo">
          <h1>EchoCoach</h1>
          <span className="logo-badge">v1 · Phase 3+4</span>
        </div>
        <div className="header-status">
          <span
            className={`status-dot ${
              connectionDetails ? "connected" : "disconnected"
            }`}
          />
          <span>
            {connectionDetails ? "Connected" : "Not connected"}
          </span>
        </div>
      </header>

      {/* Main */}
      <main className="app-main">
        {!connectionDetails ? (
          /* --- Pre-session: Connect Panel --- */
          <div className="connect-panel fade-in">
            <h2>
              Hear <span className="highlight">how</span> you speak
            </h2>
            <p className="subtitle">
              EchoCoach listens while you speak, detects mispronunciations and
              filler words, and{" "}
              <span className="highlight">
                immediately speaks back the correct pronunciation
              </span>{" "}
              using a natural human voice.
            </p>
            {error && (
              <p
                style={{
                  color: "var(--accent-rose)",
                  fontSize: 14,
                  marginBottom: 16,
                }}
              >
                ⚠ {error}
              </p>
            )}
            <button
              className="btn btn-primary btn-large"
              onClick={handleConnect}
              disabled={isConnecting}
            >
              {isConnecting ? (
                <>
                  <span className="spinner" />
                  Connecting…
                </>
              ) : (
                <>🎙 Start Coaching Session</>
              )}
            </button>
          </div>
        ) : (
          /* --- In-session: LiveKit Room --- */
          <LiveKitRoom
            serverUrl={connectionDetails.url}
            token={connectionDetails.token}
            audio={true}
            video={false}
            connectOptions={{ autoSubscribe: true }}
            onDisconnected={handleDisconnect}
            style={{ width: "100%", maxWidth: 800 }}
          >
            <SessionView
              onDisconnect={handleDisconnect}
              userIdentity={connectionDetails.identity}
            />
            <RoomAudioRenderer />
          </LiveKitRoom>
        )}
      </main>

      {/* Footer */}
      <footer className="app-footer">
        EchoCoach · Powered by{" "}
        <a href="https://rime.ai" target="_blank" rel="noopener">
          Rime TTS
        </a>{" "}
        +{" "}
        <a href="https://livekit.io" target="_blank" rel="noopener">
          LiveKit
        </a>
        {" · "}DataForge 2026
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper: score color class
// ---------------------------------------------------------------------------
function scoreClass(score: number): string {
  if (score >= 80) return "good";
  if (score >= 60) return "fair";
  return "poor";
}

function wordScoreClass(word: WordScoreData): string {
  if (word.isFlagged || word.errorType !== "None") return "word-poor";
  if (word.accuracyScore >= 80) return "word-good";
  if (word.accuracyScore >= 60) return "word-fair";
  return "word-poor";
}

// ---------------------------------------------------------------------------
// Session State Label
// ---------------------------------------------------------------------------
const STATE_LABELS: Record<SessionState, { icon: string; text: string; class: string }> = {
  connecting: { icon: "⏳", text: "Connecting…", class: "" },
  listening: { icon: "🎧", text: "Listening — read the sentence aloud", class: "state-listening" },
  listening_active: { icon: "🎤", text: "Hearing you speak…", class: "state-listening" },
  assessing: { icon: "🔍", text: "Analyzing pronunciation…", class: "state-assessing" },
  coaching: { icon: "🎓", text: "Coach is correcting…", class: "state-coaching" },
  idle: { icon: "✨", text: "Ready", class: "state-listening" },
};

// ---------------------------------------------------------------------------
// Session View (inside LiveKitRoom context)
// ---------------------------------------------------------------------------
function SessionView({
  onDisconnect,
  userIdentity,
}: {
  onDisconnect: () => void;
  userIdentity: string;
}) {
  const connectionState = useConnectionState();
  const room = useRoomContext();
  const { state: agentState, audioTrack: agentAudioTrack } =
    useVoiceAssistant();
  const transcriptions = useTranscriptions({
    participantIdentities: [userIdentity],
  });

  // --- Transcript state ---
  const [fallbackLines, setFallbackLines] = useState<TranscriptLine[]>([]);
  const primaryLines = useMemo(() => {
    let acc: TranscriptLine[] = [];
    for (const entry of transcriptions) {
      acc = upsertLine(acc, {
        id: entry.streamInfo.id,
        text: entry.text,
        isFinal:
          entry.streamInfo.attributes?.["lk.transcription_final"] === "true",
        receivedAt: entry.streamInfo.timestamp,
      });
    }
    return acc;
  }, [transcriptions]);
  const usePrimary = primaryLines.length > 0;
  const lines = usePrimary ? primaryLines.slice(-50) : fallbackLines;
  const summary = useMemo(() => summarize(lines), [lines]);

  // --- Phase 3+4 state ---
  const [sessionState, setSessionState] = useState<SessionState>(() =>
    connectionState === ConnectionState.Connected ? "listening" : "connecting"
  );
  const [targetSentence, setTargetSentence] = useState<TargetSentence | null>(null);
  const [pronunciation, setPronunciation] = useState<PronunciationData | null>(null);
  const [coaching, setCoaching] = useState<CoachingData | null>(null);
  const [pipelineMetrics, setPipelineMetrics] =
    useState<PipelineMetrics | null>(null);
  const [participantVersion, setParticipantVersion] = useState(0);

  // --- Fallback transcript handler ---
  useEffect(() => {
    if (usePrimary) return;
    const handler = (
      segments: TranscriptionSegment[],
      participant?: Participant
    ) => {
      if (participant && participant.identity !== userIdentity) return;
      setFallbackLines((prev) => {
        let next = prev;
        for (const seg of segments) {
          next = upsertLine(next, {
            id: seg.id,
            text: seg.text,
            isFinal: seg.final,
            receivedAt: Date.now(),
          });
        }
        return next;
      });
    };
    room.on(RoomEvent.TranscriptionReceived, handler);
    return () => {
      room.off(RoomEvent.TranscriptionReceived, handler);
    };
  }, [room, userIdentity, usePrimary]);

  // --- Listen for data messages from agent ---
  useEffect(() => {
    const handleDataReceived = (
      payload: Uint8Array,
      participant?: Participant,
      _kind?: unknown,
      topic?: string,
    ) => {
      if (!topic) return;

      let raw: unknown;
      try {
        const text = new TextDecoder().decode(payload);
        raw = JSON.parse(text);
      } catch (e) {
        console.warn("[EchoCoach] Failed to parse data message", topic, e);
        return;
      }

      if (!isRecord(raw)) {
        console.warn("[EchoCoach] Unexpected data payload shape", topic);
        return;
      }

      switch (topic) {
        case "sentence":
          setTargetSentence({
            id: toNumberValue(raw.id, 0),
            text: toStringValue(raw.text, ""),
            difficulty: toStringValue(raw.difficulty, ""),
            category: toStringValue(raw.category, ""),
          });
          break;
        case "pronunciation": {
          if (participant && !isAgentParticipant(participant)) return;
          const parsed: PronunciationData = {
            recognizedText: toStringValue(raw.recognizedText, ""),
            accuracyScore: toNumberValue(raw.accuracyScore, 0),
            fluencyScore: toNumberValue(raw.fluencyScore, 0),
            completenessScore: toNumberValue(raw.completenessScore, 0),
            prosodyScore: toNumberValue(raw.prosodyScore, 0),
            words: toWordList(raw.words),
            flaggedWords: toWordList(raw.flaggedWords),
            hasIssues: raw.hasIssues === true,
            assessmentLatencyMs:
              typeof raw.assessmentLatencyMs === "number" &&
              Number.isFinite(raw.assessmentLatencyMs)
                ? raw.assessmentLatencyMs
                : undefined,
          };
          setPronunciation(parsed);
          if (!parsed.hasIssues) {
            setCoaching(null);
          }
          break;
        }
        case "coaching": {
          if (participant && !isAgentParticipant(participant)) return;
          setCoaching({
            coachingText: toStringValue(raw.coachingText, ""),
            wordsToModel: toStringList(raw.wordsToModel),
            latencyMs: toNumberValue(raw.latencyMs, 0),
            source: toStringValue(raw.source, ""),
          });
          break;
        }
        case "state": {
          const s = raw.state;
          if (
            typeof s !== "string" ||
            !(KNOWN_STATES as readonly string[]).includes(s)
          ) {
            return;
          }
          setSessionState(s as SessionState);
          break;
        }
        case "metrics": {
          if (participant && !isAgentParticipant(participant)) return;
          setPipelineMetrics({
            totalPipelineMs: toNumberValue(raw.totalPipelineMs, 0),
            correctionLatencyMs: toNumberValue(raw.correctionLatencyMs, 0),
          });
          break;
        }
      }
    };

    const handleConnected = () => {
      setSessionState("listening");
    };

    room.on(RoomEvent.DataReceived, handleDataReceived);
    room.on(RoomEvent.Connected, handleConnected);
    return () => {
      room.off(RoomEvent.DataReceived, handleDataReceived);
      room.off(RoomEvent.Connected, handleConnected);
    };
  }, [room]);

  useEffect(() => {
    const bump = () => {
      setParticipantVersion((v) => v + 1);
    };
    room.on(RoomEvent.ParticipantConnected, bump);
    room.on(RoomEvent.ParticipantDisconnected, bump);
    room.on(RoomEvent.Connected, bump);
    return () => {
      room.off(RoomEvent.ParticipantConnected, bump);
      room.off(RoomEvent.ParticipantDisconnected, bump);
      room.off(RoomEvent.Connected, bump);
    };
  }, [room]);

  useEffect(() => {
    if (sessionState !== "assessing" && sessionState !== "coaching") return;
    const timer = setTimeout(() => {
      setSessionState("listening");
    }, 20000);
    return () => clearTimeout(timer);
  }, [sessionState]);

  const agentParticipant = useMemo(() => {
    void participantVersion;
    return findAgent(room.remoteParticipants.values());
  }, [room, participantVersion]);
  const agentMissing = !agentParticipant;

  // --- RPC: Request next sentence ---
  const handleNextSentence = useCallback(async () => {
    try {
      const agent = agentParticipant;
      if (!agent) {
        console.warn("No agent participant found for RPC");
        return;
      }
      setPronunciation(null);
      setCoaching(null);
      await room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: "next_sentence",
        payload: "",
      });
    } catch (e) {
      console.error("next_sentence RPC failed:", e);
    }
  }, [room, agentParticipant]);

  const handleRetry = useCallback(() => {
    setPronunciation(null);
    setCoaching(null);
  }, []);

  // --- RPC: Hear a word ---
  const handleHearWord = useCallback(
    async (word: string, speed: "normal" | "slow") => {
      try {
        const agent = agentParticipant;
        if (!agent) {
          console.warn("No agent participant found for RPC");
          return;
        }
        await room.localParticipant.performRpc({
          destinationIdentity: agent.identity,
          method: "hear_word",
          payload: JSON.stringify({ word, speed }),
        });
      } catch (e) {
        console.error("hear_word RPC failed:", e);
      }
    },
    [room, agentParticipant]
  );

  const visibleLines = lines.slice(-6);
  const isSpeaking = agentState === "speaking";
  const stateInfo = STATE_LABELS[sessionState] || STATE_LABELS.idle;

  return (
    <div className="session-panel fade-in">
      {/* Session State Indicator */}
      <div style={{ display: "flex", justifyContent: "center" }}>
        <div className={`session-state ${stateInfo.class}`}>
          {stateInfo.icon} {stateInfo.text}
        </div>
      </div>

      {agentMissing && (
        <div
          className="agent-error"
          style={{ color: "var(--accent-rose)", fontSize: 13, textAlign: "center" }}
        >
          Agent not connected — voice actions disabled
        </div>
      )}

      {/* Target Sentence Card */}
      {targetSentence && (
        <div className="glass-card target-sentence-card">
          <div className="target-sentence-label">Read this sentence aloud</div>
          <div className="target-sentence-meta">
            Sentence #{targetSentence.id}
            <span className={`difficulty-badge ${targetSentence.difficulty}`}>
              {targetSentence.difficulty}
            </span>
          </div>
          <div className="target-sentence-text">
            &ldquo;{targetSentence.text}&rdquo;
          </div>
          {pronunciation && pronunciation.recognizedText && (
            <div className="recognized-text" style={{ fontSize: 13, marginTop: 8 }}>
              Heard: &ldquo;{pronunciation.recognizedText}&rdquo;
            </div>
          )}
          <div className="target-sentence-actions">
            <button
              className="btn btn-secondary"
              onClick={handleNextSentence}
              disabled={agentMissing}
            >
              ↻ Next Sentence
            </button>
            <button className="btn btn-secondary" onClick={handleRetry}>
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Coach Output / Audio Visualizer */}
      <div className="glass-card coach-output">
        <div className="coach-label">
          {isSpeaking ? "🔊 Coach is speaking" : "🎧 Coach is listening"}
        </div>

        {agentAudioTrack && (
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              marginBottom: 16,
            }}
          >
            <BarVisualizer
              state={agentState}
              trackRef={agentAudioTrack}
              barCount={5}
              style={{ width: 120, height: 48 }}
            />
          </div>
        )}

        <div className={`coach-text ${isSpeaking ? "speaking" : ""}`}>
          {connectionState === ConnectionState.Connecting && (
            <span style={{ color: "var(--text-secondary)" }}>
              <span
                className="spinner"
                style={{ marginRight: 8, display: "inline-block" }}
              />
              Connecting to EchoCoach…
            </span>
          )}
          {connectionState === ConnectionState.Connected && !isSpeaking && (
            <span style={{ color: "var(--text-secondary)" }}>
              Waiting for coach to respond…
            </span>
          )}
          {connectionState === ConnectionState.Connected && isSpeaking && (
            <span>Coach is speaking — listen carefully</span>
          )}
        </div>
      </div>

      {/* Pronunciation Results */}
      {pronunciation && (
        <div className="glass-card pronunciation-panel fade-in">
          <div className="pronunciation-header">
            <span className="pronunciation-label">
              Pronunciation Scores
            </span>
            <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
              Flag threshold 60
            </span>
            <div className="score-stats">
              <div className="score-stat">
                Accuracy{" "}
                <span
                  className={`stat-value ${scoreClass(
                    pronunciation.accuracyScore
                  )}`}
                >
                  {Math.round(pronunciation.accuracyScore)}
                </span>
              </div>
              <div className="score-stat">
                Fluency{" "}
                <span
                  className={`stat-value ${scoreClass(
                    pronunciation.fluencyScore
                  )}`}
                >
                  {Math.round(pronunciation.fluencyScore)}
                </span>
              </div>
              <div className="score-stat">
                Completeness{" "}
                <span
                  className={`stat-value ${scoreClass(
                    pronunciation.completenessScore
                  )}`}
                >
                  {Math.round(pronunciation.completenessScore)}
                </span>
              </div>
              {pronunciation.prosodyScore > 0 && (
                <div className="score-stat">
                  Prosody{" "}
                  <span
                    className={`stat-value ${scoreClass(
                      pronunciation.prosodyScore
                    )}`}
                  >
                    {Math.round(pronunciation.prosodyScore)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Per-word scores */}
          <div className="word-scores">
            {pronunciation.words.map((w, i) => (
              <div key={`${w.word}-${i}`} className={`word-score ${wordScoreClass(w)}`}>
                <span className="word-text">{w.word}</span>
                <span className="word-accuracy">
                  {Math.round(w.accuracyScore)}
                </span>
              </div>
            ))}
          </div>

          {pronunciation.assessmentLatencyMs && (
            <div className="metrics-bar" style={{ marginTop: 12 }}>
              <div className="metric-pill">
                Assessment{" "}
                <span className="metric-value">
                  {Math.round(pronunciation.assessmentLatencyMs)}ms
                </span>
              </div>
              {pipelineMetrics && (
                <>
                  <div className="metric-pill">
                    Total pipeline{" "}
                    <span className="metric-value">
                      {Math.round(pipelineMetrics.totalPipelineMs)}ms
                    </span>
                  </div>
                  <div className="metric-pill">
                    Correction{" "}
                    <span className="metric-value">
                      {Math.round(pipelineMetrics.correctionLatencyMs)}ms
                    </span>
                  </div>
                </>
              )}
            </div>
          )}
          {!pronunciation.assessmentLatencyMs && pipelineMetrics && (
            <div className="metrics-bar" style={{ marginTop: 12 }}>
              <div className="metric-pill">
                Total pipeline{" "}
                <span className="metric-value">
                  {Math.round(pipelineMetrics.totalPipelineMs)}ms
                </span>
              </div>
              <div className="metric-pill">
                Correction{" "}
                <span className="metric-value">
                  {Math.round(pipelineMetrics.correctionLatencyMs)}ms
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Coaching Card */}
      {coaching && (
        <div className="glass-card coaching-card fade-in">
          <div className="coaching-label">🎓 Coach Feedback</div>
          <div className="coaching-text">
            &ldquo;{coaching.coachingText}&rdquo;
          </div>
          {coaching.wordsToModel.length > 0 && (
            <div className="correction-words">
              {coaching.wordsToModel.map((word, i) => (
                <div key={`${word}-${i}`} className="correction-word">
                  <span className="cw-text">{word}</span>
                  <div className="cw-buttons">
                    <button
                      className="btn-hear"
                      onClick={() => handleHearWord(word, "normal")}
                      disabled={agentMissing}
                    >
                      🔊 Normal
                    </button>
                    <button
                      className="btn-hear slow"
                      onClick={() => handleHearWord(word, "slow")}
                      disabled={agentMissing}
                    >
                      🐢 Slow
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {coaching.latencyMs > 0 && (
            <div className="metrics-bar" style={{ marginTop: 12 }}>
              <div className="metric-pill">
                Coaching ({coaching.source}){" "}
                <span className="metric-value">
                  {Math.round(coaching.latencyMs)}ms
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {pipelineMetrics && !pronunciation && (
        <div className="glass-card metrics-panel">
          <div className="metrics-bar">
            <div className="metric-pill">
              Total pipeline{" "}
              <span className="metric-value">
                {Math.round(pipelineMetrics.totalPipelineMs)}ms
              </span>
            </div>
            <div className="metric-pill">
              Correction{" "}
              <span className="metric-value">
                {Math.round(pipelineMetrics.correctionLatencyMs)}ms
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Live Transcript */}
      <div className="glass-card transcript-panel">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
          }}
        >
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: "0.08em",
              textTransform: "uppercase" as const,
              color: "var(--text-secondary)",
            }}
          >
            Live Transcript
          </span>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            {summary.wpm} WPM · {summary.fillers}{" "}
            {summary.fillers === 1 ? "filler" : "fillers"}
          </span>
        </div>
        {visibleLines.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            Speak and your words appear here
          </p>
        ) : (
          <div
            style={{ display: "flex", flexDirection: "column", gap: 6 }}
          >
            {visibleLines.map((line) => (
              <p
                key={line.id}
                style={{
                  fontSize: 14,
                  lineHeight: 1.5,
                  margin: 0,
                  color: line.isFinal
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
                  opacity: line.isFinal ? 1 : 0.55,
                  fontStyle: line.isFinal ? "normal" : "italic",
                }}
              >
                {line.text}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* User Input */}
      <div className="glass-card user-input-area">
        <div className="audio-bars active" style={{ height: 32 }}>
          {[...Array(5)].map((_, i) => (
            <div key={i} className="audio-bar" />
          ))}
        </div>
        <div className="input-label">
          {connectionState === ConnectionState.Connected
            ? "Your microphone is active — speak now"
            : "Connecting microphone…"}
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", justifyContent: "center", gap: 12 }}>
        <button
          className="btn btn-danger"
          onClick={() => {
            room.disconnect();
            onDisconnect();
          }}
        >
          ✕ End Session
        </button>
      </div>
    </div>
  );
}
