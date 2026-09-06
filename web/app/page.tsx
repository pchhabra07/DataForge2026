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
          <span className="logo-badge">v1 · Phase 1</span>
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
            <SessionView onDisconnect={handleDisconnect} userIdentity={connectionDetails.identity} />
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
  const { state: agentState, audioTrack: agentAudioTrack } = useVoiceAssistant();
  const transcriptions = useTranscriptions({
    participantIdentities: [userIdentity],
  });
  const [fallbackLines, setFallbackLines] = useState<TranscriptLine[]>([]);
  const primaryLines = useMemo(
    () =>
      transcriptions.map((entry) => ({
        id: entry.streamInfo.id,
        text: entry.text,
        isFinal:
          entry.streamInfo.attributes?.["lk.transcription_final"] === "true",
        receivedAt: entry.streamInfo.timestamp,
      })),
    [transcriptions]
  );
  const usePrimary = primaryLines.length > 0;
  const lines = usePrimary ? primaryLines.slice(-50) : fallbackLines;
  const summary = useMemo(() => summarize(lines), [lines]);

  useEffect(() => {
    if (usePrimary) {
      return;
    }
    const handler = (
      segments: TranscriptionSegment[],
      participant?: Participant
    ) => {
      if (participant && participant.identity !== userIdentity) {
        return;
      }
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

  const visibleLines = lines.slice(-6);
  const isSpeaking = agentState === "speaking";

  return (
    <div className="session-panel fade-in">
      {/* Coach Output */}
      <div className="glass-card coach-output">
        <div className="coach-label">
          {isSpeaking ? "🔊 Coach is speaking" : "🎧 Coach is listening"}
        </div>

        {/* Audio Visualizer */}
        {agentAudioTrack && (
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
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
              <span className="spinner" style={{ marginRight: 8, display: "inline-block" }} />
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
              textTransform: "uppercase",
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
        <div
          className="audio-bars active"
          style={{ height: 32 }}
        >
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
