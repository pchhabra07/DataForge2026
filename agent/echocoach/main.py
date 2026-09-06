"""
EchoCoach — LiveKit Agent Entry Point (Phase 1: Rime Voice Loop)

This agent joins a LiveKit room, greets the user with a fixed coaching line
spoken by Rime TTS, and accepts mic audio from the browser client.

Phase 1 goal: prove end-to-end audio path — click → Rime voice plays in browser.
"""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, RoomInputOptions
from livekit.plugins import deepgram, rime, silero

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

logger = logging.getLogger("echocoach")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Rime configuration — locked from PRD §8
# Model: coda (primary quality), mistv3 (low-latency fallback)
# Voice: celeste (warm, encouraging — picked from Rime catalog)
# Language: en
# Audio format: streamed PCM for web
# ---------------------------------------------------------------------------
RIME_MODEL = "coda"
RIME_VOICE = "celeste"
RIME_LANGUAGE = "en"

COACHING_GREETING = (
    "Welcome to EchoCoach! I'm your real-time speaking coach. "
    "I'll listen while you speak and help you improve your pronunciation, "
    "pace, and fluency. Let's get started — try reading the sentence on screen."
)


class EchoCoachAgent(Agent):
    """EchoCoach speaking coach agent.

    Phase 1: speaks a fixed greeting via Rime TTS.
    Later phases add pronunciation assessment, corrective feedback, etc.
    """

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are EchoCoach, a warm and encouraging real-time speaking coach. "
                "You help users improve their English pronunciation, pace, and fluency. "
                "You listen to their speech, detect mispronunciations and filler words, "
                "and immediately speak back the correct pronunciation using clear, "
                "natural voice. Keep your feedback short and actionable."
            ),
        )


server = AgentServer()


@server.rtc_session(agent_name="echocoach")
async def echocoach_session(ctx: agents.JobContext):
    """Handle a single coaching session.

    Phase 1: connect → speak greeting via Rime → accept mic input.
    """
    t0 = time.perf_counter()
    logger.info("EchoCoach session starting…")

    # Build the agent session with Rime TTS (primary spoken output)
    session = AgentSession(
        # --- TTS: Rime is the ONLY spoken output (PRD §3 — non-negotiable) ---
        tts=rime.TTS(
            model=RIME_MODEL,
            speaker=RIME_VOICE,
            speed_alpha=1.0,
            use_websocket=True,  # lower latency + word-level timestamps
        ),
        # --- STT: Deepgram (verbatim, word timestamps) — wired for Phase 2 ---
        stt=deepgram.STT(
            model="nova-3",
            language="en",
        ),
        # --- VAD: Silero for turn detection ---
        vad=silero.VAD.load(),
    )

    # Start the session — connects agent to the room
    await session.start(
        room=ctx.room,
        agent=EchoCoachAgent(),
        room_input_options=RoomInputOptions(),
    )

    t1 = time.perf_counter()
    logger.info(f"Session started in {(t1 - t0) * 1000:.0f}ms")

    # Speak the coaching greeting via Rime
    # This is the Phase 1 acceptance test: user must hear this in the browser.
    t_speak = time.perf_counter()
    await session.say(COACHING_GREETING)
    t_done = time.perf_counter()
    logger.info(f"Rime greeting first-byte latency: {(t_done - t_speak) * 1000:.0f}ms (approx)")


if __name__ == "__main__":
    agents.cli.run_app(server)
