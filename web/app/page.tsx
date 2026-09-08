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
    <div className="stage">
      <header className="rail">
        <div className="wordmark">
          <h1>
            Echo<em>Coach</em>
          </h1>
          <span>Voice Lab · v1</span>
        </div>
        <div
          className={`live-readout ${connectionDetails ? "on" : ""}`}
        >
          <span className="dot" />
          <span>{connectionDetails ? "Live" : "Offline"}</span>
        </div>
      </header>

      <main style={{ display: "contents" }}>
        {!connectionDetails ? (
          <div className="hero fade-in">
            <div className="hero-kicker">Real-time speaking coach</div>
            <h2 className="hero-title">
              Hear <span className="thin">how</span> you speak
            </h2>
            <p className="hero-sub">
              EchoCoach listens while you speak, scores every word, and{" "}
              <strong>speaks the correction back</strong> in a natural
              human voice. Read a sentence, get flagged, hear it fixed.
            </p>
            {error && <p className="errline">{error}</p>}
            <button
              className="start-btn"
              onClick={handleConnect}
              disabled={isConnecting}
            >
              {isConnecting ? (
                <>
                  <span className="spinner" />
                  Connecting
                </>
              ) : (
                <>
                  Start coaching session <span className="arrow">→</span>
                </>
              )}
            </button>
          </div>
        ) : (
          <LiveKitRoom
            serverUrl={connectionDetails.url}
            token={connectionDetails.token}
            audio={true}
            video={false}
            connectOptions={{ autoSubscribe: true }}
            onDisconnected={handleDisconnect}
            style={{ width: "100%", display: "contents" }}
          >
            <SessionView
              onDisconnect={handleDisconnect}
              userIdentity={connectionDetails.identity}
            />
            <RoomAudioRenderer />
          </LiveKitRoom>
        )}
      </main>

      <footer className="colophon">
        EchoCoach · <a href="https://rime.ai" target="_blank" rel="noopener">Rime</a> +{" "}
        <a href="https://livekit.io" target="_blank" rel="noopener">LiveKit</a> · DataForge 2026
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
  if (word.isFlagged || word.errorType !== "None") return "w-poor";
  if (word.accuracyScore >= 80) return "w-good";
  if (word.accuracyScore >= 60) return "w-fair";
  return "w-poor";
}

// ---------------------------------------------------------------------------
// Session State Label
// ---------------------------------------------------------------------------
const STATE_LABELS: Record<SessionState, { text: string; class: string }> = {
  connecting: { text: "Connecting", class: "" },
  listening: { text: "Listening — read the sentence aloud", class: "" },
  listening_active: { text: "Hearing you speak", class: "working" },
  assessing: { text: "Analyzing pronunciation", class: "working" },
  coaching: { text: "Coach is correcting", class: "working" },
  idle: { text: "Ready", class: "" },
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
  const deckStatus =
    connectionState !== ConnectionState.Connected
      ? "Connecting microphone…"
      : sessionState === "listening"
        ? "Mic live — read the sentence aloud"
        : sessionState === "listening_active"
          ? "Mic live — hearing you…"
          : stateInfo.text;

  return (
    <div className="console fade-in">
      <div className={`live-readout ${stateInfo.class}`}>
        <span className="dot" />
        <span>{stateInfo.text}</span>
        {isSpeaking && agentAudioTrack && (
          <BarVisualizer
            state={agentState}
            trackRef={agentAudioTrack}
            barCount={5}
            style={{ width: 72, height: 22 }}
          />
        )}
      </div>

      {agentMissing && (
        <div className="agent-line">
          Agent not connected — voice actions disabled
        </div>
      )}

      {targetSentence && (
        <>
          <div className="prompt-kicker" style={{ marginTop: 28 }}>
            Read this aloud · #{targetSentence.id} ·{" "}
            <span className="prompt-meta" style={{ margin: 0 }}>
              <span className="lvl">{targetSentence.difficulty}</span>
              <span>{targetSentence.category}</span>
            </span>
          </div>
          <div className="prompt-text">
            &ldquo;{targetSentence.text}&rdquo;
          </div>
          {pronunciation && pronunciation.recognizedText && (
            <div className="heard-line">
              Heard as <b>&ldquo;{pronunciation.recognizedText}&rdquo;</b>
            </div>
          )}
          {(!pronunciation || !pronunciation.recognizedText) && (
            <div style={{ marginBottom: 28 }} />
          )}
        </>
      )}

      {connectionState === ConnectionState.Connecting && (
        <div className="agent-line">Linking you to the coach…</div>
      )}

      {pronunciation && (
        <div className="fade-in">
          <div className="attempt-kicker">Your attempt · scored live</div>
          <div className="attempt-line">
            {pronunciation.words.map((w, i) => (
              <span key={`${w.word}-${i}`} className={`w ${wordScoreClass(w)}`}>
                {w.word}
                <sup>{Math.round(w.accuracyScore)}</sup>
              </span>
            ))}
          </div>

          <div className="score-strip">
            <div className="score-cell">
              Accuracy{" "}
              <b className={scoreClass(pronunciation.accuracyScore)}>
                {Math.round(pronunciation.accuracyScore)}
              </b>
            </div>
            <div className="score-cell">
              Fluency{" "}
              <b className={scoreClass(pronunciation.fluencyScore)}>
                {Math.round(pronunciation.fluencyScore)}
              </b>
            </div>
            <div className="score-cell">
              Complete{" "}
              <b className={scoreClass(pronunciation.completenessScore)}>
                {Math.round(pronunciation.completenessScore)}
              </b>
            </div>
            {pronunciation.prosodyScore > 0 && (
              <div className="score-cell">
                Prosody{" "}
                <b className={scoreClass(pronunciation.prosodyScore)}>
                  {Math.round(pronunciation.prosodyScore)}
                </b>
              </div>
            )}
            <div className="score-cell">
              <span className="thresh">flags under 60</span>
            </div>
          </div>

          {pronunciation.assessmentLatencyMs ? (
            <div className="latency-line" style={{ paddingLeft: 0, marginBottom: 24 }}>
              scored in {Math.round(pronunciation.assessmentLatencyMs)}ms
              {pipelineMetrics
                ? ` · pipeline ${Math.round(pipelineMetrics.totalPipelineMs)}ms · correction ${Math.round(pipelineMetrics.correctionLatencyMs)}ms`
                : ""}
            </div>
          ) : (
            pipelineMetrics && (
              <div className="latency-line" style={{ paddingLeft: 0, marginBottom: 24 }}>
                pipeline {Math.round(pipelineMetrics.totalPipelineMs)}ms ·
                correction {Math.round(pipelineMetrics.correctionLatencyMs)}ms
              </div>
            )
          )}
        </div>
      )}

      {coaching && (
        <div className="fade-in">
          <div className="coach-note">
            <div className="who">Coach note · {coaching.source}</div>
            <p>&ldquo;{coaching.coachingText}&rdquo;</p>
          </div>
          {coaching.wordsToModel.length > 0 && (
            <div className="model-row">
              {coaching.wordsToModel.map((word, i) => (
                <div key={`${word}-${i}`} className="model-word">
                  <span>{word}</span>
                  <button
                    onClick={() => handleHearWord(word, "normal")}
                    disabled={agentMissing}
                  >
                    Play
                  </button>
                  <button
                    onClick={() => handleHearWord(word, "slow")}
                    disabled={agentMissing}
                  >
                    Slow
                  </button>
                </div>
              ))}
            </div>
          )}
          {coaching.latencyMs > 0 && (
            <div className="latency-line">
              coaching {Math.round(coaching.latencyMs)}ms
            </div>
          )}
        </div>
      )}

      {pipelineMetrics && !pronunciation && (
        <div className="latency-line">
          pipeline {Math.round(pipelineMetrics.totalPipelineMs)}ms · correction{" "}
          {Math.round(pipelineMetrics.correctionLatencyMs)}ms
        </div>
      )}

      <div className="ticker-kicker" style={{ marginTop: 8 }}>
        Live transcript
        <span className="pace">
          {summary.wpm} WPM · {summary.fillers}{" "}
          {summary.fillers === 1 ? "filler" : "fillers"}
        </span>
      </div>
      {visibleLines.length === 0 ? (
        <p className="ticker-empty">Speak and your words appear here</p>
      ) : (
        <div className="ticker">
          {visibleLines.map((line, idx) => (
            <p
              key={line.id}
              className={`ticker-line${line.isFinal ? " final" : ""}${
                idx === visibleLines.length - 1 ? " latest" : ""
              }`}
            >
              {line.text}
            </p>
          ))}
        </div>
      )}

      <div className="deck">
        <div className="deck-inner">
          <div
            className={`orb ${
              connectionState === ConnectionState.Connected ? "live" : ""
            }`}
          >
            <i />
          </div>
          <div className="deck-status">{deckStatus}</div>
          <div className="deck-actions">
            <button className="deck-btn" onClick={handleRetry}>
              Retry
            </button>
            <button
              className="deck-btn"
              onClick={handleNextSentence}
              disabled={agentMissing}
            >
              Next
            </button>
            <button
              className="deck-btn quit"
              onClick={() => {
                room.disconnect();
                onDisconnect();
              }}
            >
              End
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
