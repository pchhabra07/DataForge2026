"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useLocalParticipant,
  useRoomContext,
  useTranscriptions,
  useVoiceAssistant,
  BarVisualizer,
} from "@livekit/components-react";
import { ConnectionState, RoomEvent } from "livekit-client";
import type { Participant, TranscriptionSegment } from "livekit-client";
import {
  summarize,
  upsertLine,
  formatDuration,
  toPipelineSnapshot,
} from "./lib/metrics";
import type { TranscriptLine, PipelineSnapshot } from "./lib/metrics";
import { FIRST_SENTENCE, SENTENCES } from "./lib/sentences";

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
  isDemo?: boolean;
}

interface CoachingData {
  coachingText: string;
  wordsToModel: string[];
  latencyMs: number;
  source: string;
  isDemo?: boolean;
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

function isAgentParticipant(p: Participant, selfIdentity?: string): boolean {
  if (selfIdentity && p.identity === selfIdentity) return false;
  const id = p.identity.toLowerCase();
  if (id === "echocoach" || id.includes("echocoach")) return true;
  // Random rooms hold only you plus the coach, so any other remote peer is the coach.
  return true;
}

function findAgent(
  participants: Iterable<Participant>,
  selfIdentity?: string,
): Participant | undefined {
  const list = Array.from(participants).filter((p) =>
    selfIdentity ? p.identity !== selfIdentity : true
  );
  if (list.length === 0) return undefined;
  const exact = list.find((p) => p.identity === "echocoach");
  if (exact) return exact;
  const contains = list.find((p) => p.identity.toLowerCase().includes("echocoach"));
  if (contains) return contains;
  return list[0];
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------
export default function Home() {
  const [connectionDetails, setConnectionDetails] =
    useState<TokenResponse | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showExample, setShowExample] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem("ec-seen") !== "1") {
        setShowExample(true);
      }
    } catch {
      // ignore storage errors
    }
  }, []);

  const dismissExample = useCallback(() => {
    setShowExample(false);
    try {
      localStorage.setItem("ec-seen", "1");
    } catch {
      // ignore storage errors
    }
  }, []);

  const handleConnect = useCallback(async () => {
    setIsConnecting(true);
    setError(null);
    try {
      const room = `coach-${crypto.randomUUID().slice(0, 8)}`;
      const resp = await fetch(`/api/token?room=${encodeURIComponent(room)}`);
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
          <>
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
                  Start Coaching Session <span className="arrow">→</span>
                </>
              )}
            </button>
          </div>
          {showExample && (
            <div
              className="modal-overlay fade-in"
              onClick={dismissExample}
              role="dialog"
              aria-modal="true"
              onKeyDown={(e) => {
                if (e.key === "Escape") dismissExample();
              }}
            >
              <div className="modal" onClick={(e) => e.stopPropagation()}>
                <button
                  className="modal-close"
                  onClick={dismissExample}
                  aria-label="Dismiss"
                >
                  ×
                </button>
                <div className="modal-kicker">
                  Your first sentence · {FIRST_SENTENCE.difficulty}
                </div>
                <p className="modal-sentence">
                  &ldquo;{FIRST_SENTENCE.text}&rdquo;
                </p>
                <div className="modal-kicker" style={{ marginTop: 20 }}>
                  Sample scoring
                </div>
                <div className="attempt-line" style={{ fontSize: 20 }}>
                  {[
                    ["The", 51],
                    ["quick", 100],
                    ["brown", 100],
                    ["fox", 100],
                    ["jumps", 100],
                    ["over", 58],
                    ["the", 100],
                    ["lazy", 100],
                    ["dog", 100],
                  ].map(([w, s], i) => (
                    <span
                      key={`${w as string}-${i}`}
                      className={`w ${
                        (s as number) >= 80
                          ? "w-good"
                          : (s as number) >= 60
                            ? "w-fair"
                            : "w-poor"
                      }`}
                    >
                      {w}
                      <sup>{s}</sup>
                    </span>
                  ))}
                </div>
                <div className="score-strip">
                  <div className="score-cell">
                    Accuracy <b className="fair">90</b>
                  </div>
                  <div className="score-cell">
                    Flagged <b className="poor">2</b>
                  </div>
                  <div className="score-cell">
                    <span className="thresh">real engine output on clean audio</span>
                  </div>
                </div>
                <p className="modal-hint">
                  Close this and press Start below. Read the sentence aloud
                  and the coach scores you live, then speaks the fix back.
                </p>
              </div>
            </div>
          )}
          </>
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
    useState<PipelineSnapshot | null>(null);
  const [participantVersion, setParticipantVersion] = useState(0);

  // --- Phase 5: Skip/interruption state ---
  const [showSkippedToast, setShowSkippedToast] = useState(false);

  // --- Phase 6: Slow-mode toggle ---
  const [slowMode, setSlowMode] = useState(false);

  const [modelStatus, setModelStatus] = useState<string | null>(null);
  const [micMuted, setMicMuted] = useState(false);

  const [sessionStart, setSessionStart] = useState<number | null>(() => null);
  const [sessionElapsed, setSessionElapsed] = useState(0);
  const [nextBusy, setNextBusy] = useState(false);
  const [rpcError, setRpcError] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [showMetrics, setShowMetrics] = useState(false);

  useEffect(() => {
    if (sessionStart == null) return;
    const interval = setInterval(() => {
      setSessionElapsed(Date.now() - sessionStart);
    }, 1000);
    return () => clearInterval(interval);
  }, [sessionStart]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (connectionState !== ConnectionState.Connected) return;
    const id = setTimeout(() => {
      setSessionStart((prev) => (prev == null ? Date.now() : prev));
      setSessionState("listening");
    }, 0);
    return () => clearTimeout(id);
  }, [connectionState]);

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
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
          setTargetSentence({
            id: toNumberValue(raw.id, 0),
            text: toStringValue(raw.text, ""),
            difficulty: toStringValue(raw.difficulty, ""),
            category: toStringValue(raw.category, ""),
          });
          break;
        case "pronunciation": {
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
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
            isDemo: raw.isDemo === true,
          };
          setPronunciation(parsed);
          if (!parsed.hasIssues) {
            setCoaching(null);
          }
          break;
        }
        case "coaching": {
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
          setCoaching({
            coachingText: toStringValue(raw.coachingText, ""),
            wordsToModel: toStringList(raw.wordsToModel),
            latencyMs: toNumberValue(raw.latencyMs, 0),
            source: toStringValue(raw.source, ""),
            isDemo: raw.isDemo === true,
          });
          break;
        }
        case "state": {
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
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
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
          setPipelineMetrics(toPipelineSnapshot(raw));
          break;
        }
        case "model_status": {
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
          const s = toStringValue(raw.status, "");
          if (s === "loading" || s === "ready" || s === "error") {
            setModelStatus(s);
          }
          if (s === "downloading") {
            setModelStatus("downloading");
          }
          break;
        }
        case "interruption": {
          if (participant && !isAgentParticipant(participant, userIdentity)) return;
          if (raw.source !== "skip_button") break;
          setShowSkippedToast(true);
          if (toastTimerRef.current) {
            clearTimeout(toastTimerRef.current);
          }
          toastTimerRef.current = setTimeout(() => setShowSkippedToast(false), 2000);
          break;
        }
      }
    };

    const handleConnected = () => {
      setSessionStart((prev) => (prev == null ? Date.now() : prev));
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
      setSessionState((s) => (s === "assessing" || s === "coaching" ? "idle" : s));
    }, 20000);
    return () => clearTimeout(timer);
  }, [sessionState]);

  const agentParticipant = useMemo(() => {
    void participantVersion;
    return findAgent(room.remoteParticipants.values(), userIdentity);
  }, [room, participantVersion, userIdentity]);
  const agentMissing = !agentParticipant;

  useEffect(() => {
    if (!agentParticipant) return;
    let cancelled = false;
    let timer: NodeJS.Timeout;

    const performSync = (delay: number, retriesLeft: number) => {
      timer = setTimeout(async () => {
        if (cancelled) return;
        try {
          await room.localParticipant.performRpc({
            destinationIdentity: agentParticipant.identity,
            method: "get_state",
            payload: "",
          });
        } catch (e) {
          if (retriesLeft > 0 && !cancelled) {
            performSync(800, retriesLeft - 1);
          } else {
            console.warn("get_state resync failed:", e);
          }
        }
      }, delay);
    };

    performSync(500, 2);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [room, agentParticipant]);

  // --- RPC: Request next sentence ---
  const handleNextSentence = useCallback(async () => {
    if (nextBusy) return;
    const fallbackNext = () => {
      const base = targetSentence ?? FIRST_SENTENCE;
      const idx = SENTENCES.findIndex((s) => s.id === base.id);
      const next = SENTENCES[(idx + 1 + SENTENCES.length) % SENTENCES.length];
      setTargetSentence({
        id: next.id,
        text: next.text,
        difficulty: next.difficulty,
        category: next.category,
      });
      setPronunciation(null);
      setCoaching(null);
      setPipelineMetrics(null);
      setSessionState("listening");
    };
    try {
      const agent = agentParticipant;
      if (!agent) {
        fallbackNext();
        setRpcError("Agent offline - cycled locally");
        return;
      }
      setNextBusy(true);
      await room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: "next_sentence",
        payload: "",
      });
      setPronunciation(null);
      setCoaching(null);
      setPipelineMetrics(null);
      setSessionState("listening");
      setRpcError(null);
    } catch (e) {
      console.error("next_sentence RPC failed:", e);
      fallbackNext();
      setRpcError(e instanceof Error ? e.message : "Next sentence failed");
    } finally {
      setNextBusy(false);
    }
  }, [room, agentParticipant, nextBusy, targetSentence]);

  const handleRetry = useCallback(() => {
    setPronunciation(null);
    setCoaching(null);
    setPipelineMetrics(null);
    setSessionState("listening");
  }, []);

  const { localParticipant } = useLocalParticipant();

  const handleToggleMute = useCallback(async () => {
    try {
      const next = !micMuted;
      await localParticipant.setMicrophoneEnabled(!next);
      setMicMuted(next);
    } catch (e) {
      console.error("Mic toggle failed:", e);
    }
  }, [localParticipant, micMuted]);
  // --- RPC: Hear a word ---
  const handleHearWord = useCallback(
    async (word: string, speed: "normal" | "slow") => {
      try {
        const agent = agentParticipant;
        if (!agent) {
          console.warn("No agent participant found for RPC");
          return;
        }
        // Phase 6: respect slow-mode toggle
        const effectiveSpeed = slowMode ? "slow" : speed;
        await room.localParticipant.performRpc({
          destinationIdentity: agent.identity,
          method: "hear_word",
          payload: JSON.stringify({ word, speed: effectiveSpeed }),
        });
      } catch (e) {
        console.error("hear_word RPC failed:", e);
      }
    },
    [room, agentParticipant, slowMode]
  );

  // --- Phase 5: RPC: Skip correction ---
  const handleSkipCorrection = useCallback(async () => {
    try {
      const agent = agentParticipant;
      if (!agent) {
        console.warn("No agent participant found for RPC");
        return;
      }
      await room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: "skip_correction",
        payload: "",
      });
    } catch (e) {
      console.error("skip_correction RPC failed:", e);
    }
  }, [room, agentParticipant]);

  const visibleLines = lines.slice(-6);
  const isSpeaking = agentState === "speaking";
  const modelReady = modelStatus === "ready";
  const uiBlocked = agentMissing || !modelReady;
  const stateInfo = STATE_LABELS[sessionState] || STATE_LABELS.idle;
  const deckStatus =
    micMuted
      ? "Mic muted — unmute to speak"
      : connectionState !== ConnectionState.Connected
        ? "Connecting microphone…"
        : sessionState === "listening"
        ? "Mic live — read the sentence aloud"
        : sessionState === "listening_active"
          ? "Mic live — hearing you…"
          : stateInfo.text;

  return (
    <div className="console fade-in">
      {/* Phase 5: Skipped toast */}
      {showSkippedToast && (
        <div className="skip-toast fade-in">⏭ Skipped</div>
      )}

      <div className={`live-readout ${connectionState === ConnectionState.Connected ? "on" : ""} ${stateInfo.class}`}>
        <span className="dot" />
        <span>{stateInfo.text}</span>
        {/* Phase 6: Session timer */}
        <span className="session-timer">{formatDuration(sessionElapsed)}</span>
        {isSpeaking && agentAudioTrack && (
          <BarVisualizer
            state={agentState}
            trackRef={agentAudioTrack}
            barCount={5}
            style={{ width: 72, height: 22 }}
          />
        )}
      </div>
      {(() => {
        const ready = modelStatus === "ready";
        if (ready) return null;
        const isError = modelStatus === "error";
        const label = agentMissing
          ? "Waiting for coach to join..."
          : isError
            ? "Scoring model failed to load - check agent terminal"
            : "Model download ho raha hai. Thoda wait karo.";
        return (
          <div className="modal-overlay fade-in" role="dialog" aria-modal="true">
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-kicker">Setup needed</div>
              <p className="modal-sentence">{label}</p>
              <p className="modal-hint">
                {agentMissing
                  ? "Start the agent with python -m echocoach.main dev then rejoin."
                  : "Live percent terminal me dikhega. Ready hote hi ye hat jayega."}
              </p>
            </div>
          </div>
        );
      })()}
      {modelStatus === "error" && (
        <div className="agent-line">
          Scoring model failed to load — check agent logs
        </div>
      )}

      {agentMissing && (
        <div className="agent-line">
          Agent not connected — start it with python -m echocoach.main dev then rejoin
        </div>
      )}

      {(() => {
        const shown = targetSentence ?? FIRST_SENTENCE;
        const isLocal = !targetSentence;
        return (
          <>
            <div className="prompt-kicker" style={{ marginTop: 28 }}>
              Read this aloud
              {shown.id ? ` · #${shown.id}` : ""}
              {shown.difficulty || shown.category ? " · " : ""}
              <span className="prompt-meta" style={{ margin: 0 }}>
                {shown.difficulty ? <span className="lvl">{shown.difficulty}</span> : null}
                {shown.category ? <span>{shown.category}</span> : null}
              </span>
              {isLocal && <span> · local</span>}
            </div>
            <div className="prompt-text">&ldquo;{shown.text}&rdquo;</div>
          {pronunciation && pronunciation.recognizedText && !pronunciation.isDemo && (
            <div className="heard-line">
              Scored against <b>&ldquo;{pronunciation.recognizedText}&rdquo;</b> · tumne kya bola neeche transcript me dekho
            </div>
          )}
          {(!pronunciation || !pronunciation.recognizedText || pronunciation.isDemo) && (
            <div style={{ marginBottom: 28 }} />
          )}
          </>
        );
      })()}

      {connectionState === ConnectionState.Connecting && (
        <div className="agent-line">Linking you to the coach…</div>
      )}

      {pronunciation && (
        <div className="fade-in">
          <div className="attempt-kicker">
            {pronunciation.isDemo ? "Example scoring · try it yourself" : "Your attempt · scored live"}
          </div>

          {/* Phase 6: Truth-beside-estimate layout */}
          <div className="attempt-line">
            {pronunciation.words.map((w, i) => (
              <span key={`${w.word}-${i}`} className={`w ${wordScoreClass(w)}`}>
                {w.word}
                <sup>{Math.round(w.accuracyScore)}</sup>
                {/* Inline Play/Slow for flagged words (truth beside estimate) */}
                {w.isFlagged && (
                  <span className="inline-btns">
                    <button
                      className="inline-play"
                      onClick={() => handleHearWord(w.word, "normal")}
                      disabled={uiBlocked}
                      title="Hear correct pronunciation"
                    >
                      ▶
                    </button>
                    <button
                      className="inline-play"
                      onClick={() => handleHearWord(w.word, "slow")}
                      disabled={uiBlocked}
                      title="Hear it slowly"
                    >
                      🐢
                    </button>
                  </span>
                )}
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
            <div className="score-cell">
              Prosody{" "}
              <b className={pronunciation.prosodyScore > 0 ? scoreClass(pronunciation.prosodyScore) : ""}>
                {pronunciation.prosodyScore > 0
                  ? Math.round(pronunciation.prosodyScore)
                  : "-"}
              </b>
            </div>
            <div className="score-cell">
              <span className="thresh">flags under 60</span>
            </div>
          </div>

          {pronunciation.assessmentLatencyMs != null && !pronunciation.isDemo ? (
            <div className="latency-line" style={{ paddingLeft: 0, marginBottom: 24 }}>
              scored in {Math.round(pronunciation.assessmentLatencyMs)}ms
              {pipelineMetrics
                ? ` · pipeline total ${Math.round(pipelineMetrics.totalPipelineMs)}ms · correction ${Math.round(pipelineMetrics.correctionLatencyMs)}ms`
                : ""}
            </div>
          ) : (
            !pronunciation.isDemo && pipelineMetrics && (
              <div className="latency-line" style={{ paddingLeft: 0, marginBottom: 24 }}>
                pipeline total {Math.round(pipelineMetrics.totalPipelineMs)}ms ·
                correction {Math.round(pipelineMetrics.correctionLatencyMs)}ms
              </div>
            )
          )}
        </div>
      )}

      {coaching && (
        <div className="fade-in">
          <div className="coach-note">
            <div className="who">
              Coach note · {coaching.source}
              {coaching.isDemo && " · demo"}
            </div>
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
          {coaching.latencyMs > 0 && !coaching.isDemo && (
            <div className="latency-line">
              coach note {Math.round(coaching.latencyMs)}ms
            </div>
          )}
        </div>
      )}

      {/* Phase 6: Metrics dashboard panel */}
      {pipelineMetrics && (
        <div className="fade-in">
          <button
            className="metrics-toggle"
            onClick={() => setShowMetrics((v) => !v)}
          >
            {showMetrics ? "▾ Hide metrics" : "▸ Show metrics"}
          </button>
          {showMetrics && (
            <div className="metrics-panel">
              <table>
                <tbody>
                  <tr>
                    <td>Attempt</td>
                    <td>#{pipelineMetrics.attemptNumber}</td>
                  </tr>
                  <tr>
                    <td>Assessment</td>
                    <td>{Math.round(pipelineMetrics.assessmentLatencyMs)}ms (avg {Math.round(pipelineMetrics.avgAssessmentMs)}ms)</td>
                  </tr>
                  <tr>
                    <td>Correction</td>
                    <td>{Math.round(pipelineMetrics.correctionLatencyMs)}ms (avg {Math.round(pipelineMetrics.avgCorrectionMs)}ms)</td>
                  </tr>
                  <tr>
                    <td>Total pipeline</td>
                    <td>{Math.round(pipelineMetrics.totalPipelineMs)}ms (avg {Math.round(pipelineMetrics.avgTotalPipelineMs)}ms)</td>
                  </tr>
                  {pipelineMetrics.lastInterruptionMs != null && (
                    <tr>
                      <td>Interruption stop</td>
                      <td>{Math.round(pipelineMetrics.lastInterruptionMs)}ms (avg {Math.round(pipelineMetrics.avgInterruptionMs)}ms)</td>
                    </tr>
                  )}
                  <tr>
                    <td>Flagged words</td>
                    <td>{pipelineMetrics.flaggedWordCount}</td>
                  </tr>
                  <tr>
                    <td>Source</td>
                    <td>{pipelineMetrics.correctionSource}{pipelineMetrics.isCached ? " (cached)" : ""}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="ticker-kicker" style={{ marginTop: 8 }}>
        Live transcript
        <span className="pace">
          {summary.wpm > 0 ? `${summary.wpm} WPM` : "-- WPM"} · {summary.fillers}{" "}
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

      {slowMode && (
        <div className="latency-line" style={{ marginBottom: 12 }}>
          Slow mode on — Play buttons play slowly
        </div>
      )}
      {rpcError && (
        <div className="latency-line" style={{ marginBottom: 12 }}>
          {rpcError}
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
            <button
              className="deck-btn"
              onClick={handleToggleMute}
              title={micMuted ? "Unmute microphone" : "Mute microphone"}
              disabled={uiBlocked}
            >
              {micMuted ? "Unmute" : "Mute"}
            </button>
            {/* Phase 6: Slow-mode toggle */}
            <button
              className={`deck-btn toggle-btn ${slowMode ? "active" : ""}`}
              onClick={() => setSlowMode((v) => !v)}
              title={slowMode ? "Slow mode ON" : "Slow mode OFF"}
              disabled={uiBlocked}
            >
              🐢 {slowMode ? "Slow" : "Normal"}
            </button>
            <button className="deck-btn" onClick={handleRetry} disabled={uiBlocked}>
              Try again ↺
            </button>
            {/* Phase 5: Skip button (visible during coaching) */}
            {sessionState === "coaching" && (
              <button
                className="deck-btn skip-btn"
                onClick={handleSkipCorrection}
                disabled={uiBlocked}
              >
                Skip ⏭
              </button>
            )}
            <button
              className="deck-btn"
              onClick={handleNextSentence}
              disabled={nextBusy || uiBlocked}
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
