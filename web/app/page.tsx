"use client";

import { useCallback, useEffect, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useRoomContext,
  useVoiceAssistant,
  BarVisualizer,
} from "@livekit/components-react";
import { ConnectionState } from "livekit-client";

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
            connectOptions={{ autoSubscribe: true }}
            onDisconnected={handleDisconnect}
            style={{ width: "100%", maxWidth: 800 }}
          >
            <SessionView onDisconnect={handleDisconnect} />
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
function SessionView({ onDisconnect }: { onDisconnect: () => void }) {
  const connectionState = useConnectionState();
  const room = useRoomContext();
  const { state: agentState, audioTrack: agentAudioTrack } = useVoiceAssistant();

  // Track whether the agent is speaking
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
