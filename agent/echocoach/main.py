"""
EchoCoach — LiveKit Agent Entry Point (Phase 3+4)

This agent joins a LiveKit room, presents target sentences for reading practice,
captures user audio, runs Azure Pronunciation Assessment, generates coaching
feedback via LLM, and speaks corrections using Rime TTS (normal + slow speed).

Phase 3: pronunciation assessment with per-word scoring
Phase 4: coaching logic + corrective Rime at normal/slow speed
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import Agent, AgentServer, AgentSession, RoomInputOptions
from livekit.plugins import deepgram, rime, silero

from echocoach.coaching import generate_correction
from echocoach.pronunciation import assess_pronunciation
from echocoach.sentences import get_first_sentence, get_next_sentence

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

logger = logging.getLogger("echocoach")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Rime configuration — locked from PRD §8
# ---------------------------------------------------------------------------
RIME_MODEL = "coda"
RIME_VOICE = "celeste"
RIME_LANGUAGE = "en"
RIME_NORMAL_SPEED = 1.0
RIME_SLOW_SPEED = 1.5  # timeScaleFactor >1.0 = slower delivery for coaching

# LiveKit audio is typically 48kHz
LIVEKIT_SAMPLE_RATE = 48000


class EchoCoachAgent(Agent):
    """EchoCoach speaking coach agent.

    Phase 3+4: pronunciation assessment + coaching corrections via Rime.
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

    Flow:
    1. Connect, greet user, send first target sentence
    2. Capture user audio during speech
    3. On speech end: run pronunciation assessment
    4. If issues found: generate coaching + speak correction via Rime
    5. Send all results to client via data messages
    """
    t0 = time.perf_counter()
    logger.info("EchoCoach session starting…")

    # Track current target sentence
    current_sentence = get_first_sentence()

    # --- Build agent session with Rime TTS ---
    session = AgentSession(
        tts=rime.TTS(
            model=RIME_MODEL,
            speaker=RIME_VOICE,
            speed_alpha=RIME_NORMAL_SPEED,
            use_websocket=True,
        ),
        stt=deepgram.STT(
            model="nova-3",
            language="en",
            filler_words=True,
            interim_results=True,
            punctuate=True,
        ),
        vad=silero.VAD.load(
            activation_threshold=0.35,
            prefix_padding_duration=0.5,
        ),
    )

    # Slow-speed Rime TTS instance for word-by-word coaching.
    # HTTP one-shot with timeScaleFactor >1.0 = slower. WebSocket is not
    # used here because per-call voice override is unsupported by say().
    slow_tts = rime.TTS(
        model=RIME_MODEL,
        speaker=RIME_VOICE,
        time_scale_factor=RIME_SLOW_SPEED,
        use_websocket=False,
    )

    async def say_slow(text: str):
        """Speak text at slow coaching speed via the HTTP slow voice."""
        frames: list[rtc.AudioFrame] = []
        async for chunk in slow_tts.synthesize(text):
            frames.append(chunk.frame)

        async def _play():
            for f in frames:
                yield f

        await session.say(text, audio=_play())

    # Start the session
    await session.start(
        room=ctx.room,
        agent=EchoCoachAgent(),
        room_input_options=RoomInputOptions(),
    )

    t1 = time.perf_counter()
    logger.info(f"Session started in {(t1 - t0) * 1000:.0f}ms")

    # --- Helper: send JSON data to client ---
    async def send_to_client(topic: str, data: dict):
        """Send structured data to the client via LiveKit data channel."""
        try:
            payload = json.dumps(data)
            await ctx.room.local_participant.publish_data(
                payload.encode("utf-8"),
                topic=topic,
            )
            logger.debug("Sent %s: %s", topic, payload[:120])
        except Exception:
            logger.exception("Failed to send data to client (topic=%s)", topic)

    # --- Send initial target sentence ---
    await send_to_client(
        "sentence",
        {
            "id": current_sentence.id,
            "text": current_sentence.text,
            "difficulty": current_sentence.difficulty,
            "category": current_sentence.category,
        },
    )

    # --- Speak greeting with target sentence ---
    greeting = (
        f"Welcome to EchoCoach! Let's practice your pronunciation. "
        f"Please read this sentence aloud: {current_sentence.text}"
    )
    t_speak = time.perf_counter()
    await session.say(greeting)
    t_done = time.perf_counter()
    logger.info(f"Rime greeting latency: {(t_done - t_speak) * 1000:.0f}ms")

    # --- Audio capture buffer ---
    # One utterance is assessed and coached at a time so slow speech
    # never overlaps itself when the user speaks rapidly.
    def _serialize_utterances(fn):
        lock = asyncio.Lock()

        async def wrapper(*args, **kwargs):
            async with lock:
                return await fn(*args, **kwargs)

        return wrapper

    # --- Handle RPC calls from client ---
    @ctx.room.local_participant.register_rpc_method("next_sentence")
    async def handle_next_sentence(data: rtc.RpcInvocationData):
        nonlocal current_sentence
        current_sentence = get_next_sentence(current_sentence.id)
        await send_to_client(
            "sentence",
            {
                "id": current_sentence.id,
                "text": current_sentence.text,
                "difficulty": current_sentence.difficulty,
                "category": current_sentence.category,
            },
        )
        await session.say(f"Great, let's try this one: {current_sentence.text}")
        return json.dumps({"id": current_sentence.id, "text": current_sentence.text})

    @ctx.room.local_participant.register_rpc_method("hear_word")
    async def handle_hear_word(data: rtc.RpcInvocationData):
        """Client requests to hear a specific word spoken by Rime."""
        try:
            payload = json.loads(data.payload)
            word = payload.get("word", "")
            speed = payload.get("speed", "normal")  # "normal" or "slow"
            if not word:
                return json.dumps({"error": "No word specified"})

            if speed == "slow":
                # Use slow TTS for word-by-word modeling
                await say_slow(word)
            else:
                await session.say(word)
            return json.dumps({"ok": True, "word": word, "speed": speed})
        except Exception as e:
            logger.exception("hear_word RPC error")
            return json.dumps({"error": str(e)})

    # --- Process user audio for pronunciation assessment ---
    @_serialize_utterances
    async def process_utterance(audio_data: bytes):
        """Run pronunciation assessment + coaching on captured audio."""
        nonlocal current_sentence

        if len(audio_data) < 4800:  # Too short
            logger.debug("Utterance too short (%d bytes), skipping", len(audio_data))
            return

        t_assess_start = time.perf_counter()

        # Send "assessing" state to client
        await send_to_client("state", {"state": "assessing"})

        # Run pronunciation assessment
        # Note: Azure SDK internally uses synchronous blocking calls
        # but our assess_pronunciation wraps them properly
        result = await assess_pronunciation(
            audio_bytes=bytes(audio_data),
            reference_text=current_sentence.text,
            sample_rate=LIVEKIT_SAMPLE_RATE,
        )

        if result is None:
            logger.warning("Pronunciation assessment returned no result")
            await send_to_client("state", {"state": "listening"})
            return

        t_assess_end = time.perf_counter()
        assess_ms = (t_assess_end - t_assess_start) * 1000
        logger.info(
            "Pronunciation assessment in %.0fms: accuracy=%.0f, flagged=%d words",
            assess_ms,
            result.accuracy_score,
            len(result.flagged_words),
        )

        # Send pronunciation results to client
        result_data = result.to_dict()
        result_data["assessmentLatencyMs"] = round(assess_ms, 1)
        await send_to_client("pronunciation", result_data)

        # --- Phase 4: Generate and speak coaching correction ---
        if result.has_issues:
            await send_to_client("state", {"state": "coaching"})

            # Generate coaching plan
            flagged_dicts = [w.to_dict() for w in result.flagged_words]
            correction = await generate_correction(
                flagged_words=flagged_dicts,
                reference_text=current_sentence.text,
            )

            # Send coaching plan to client
            correction_data = correction.to_dict()
            await send_to_client("coaching", correction_data)

            # Speak the coaching feedback via Rime (normal speed)
            t_correction_start = time.perf_counter()
            await session.say(correction.coaching_text)

            # Speak each flagged word at normal speed, then slow
            for word in correction.words_to_model:
                await session.say(f"The word is: {word}")
                await asyncio.sleep(0.3)  # Brief pause
                await say_slow(f"Now slowly: {word}")
                await asyncio.sleep(0.3)

            t_correction_end = time.perf_counter()
            correction_ms = (t_correction_end - t_correction_start) * 1000
            total_ms = (t_correction_end - t_assess_start) * 1000

            logger.info(
                "Coaching complete: correction=%.0fms, total_pipeline=%.0fms",
                correction_ms,
                total_ms,
            )

            await send_to_client(
                "metrics",
                {
                    "assessmentLatencyMs": round(assess_ms, 1),
                    "correctionLatencyMs": round(correction_ms, 1),
                    "totalPipelineMs": round(total_ms, 1),
                    "correctionSource": correction.source,
                },
            )

            await session.say("Now try reading the sentence again!")
        else:
            # No issues — encourage and move on
            await session.say("Excellent pronunciation! You nailed that sentence. Well done!")

        await send_to_client("state", {"state": "listening"})

    # --- Audio stream capture loop ---
    # Wait for the user participant to join and publish audio
    async def capture_audio_loop():
        # Wait for a remote participant with an audio track
        while True:
            participants = ctx.room.remote_participants
            for p in participants.values():
                for pub in p.track_publications.values():
                    if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
                        logger.info("Found audio track from participant %s", p.identity)
                        audio_track = pub.track
                        audio_stream = rtc.AudioStream(audio_track)

                        # Listen for VAD events to determine speech boundaries
                        # We use a simpler approach: accumulate audio frames and
                        # process on silence detection
                        speech_frames: list[bytes] = []
                        silence_count = 0
                        speech_active = False
                        SILENCE_THRESHOLD = 15  # ~750ms of silence at 20ms frames

                        async for event in audio_stream:
                            frame = event.frame
                            if frame.sample_rate != LIVEKIT_SAMPLE_RATE or frame.num_channels != 1:
                                logger.debug(
                                    "Skipping frame with unexpected format: %dHz %dch",
                                    frame.sample_rate,
                                    frame.num_channels,
                                )
                                continue
                            frame_bytes = bytes(frame.data)

                            # Simple energy-based speech detection
                            energy = _compute_energy(frame_bytes)

                            if energy > 200:  # Speech threshold
                                if not speech_active:
                                    speech_active = True
                                    speech_frames = []
                                    await send_to_client("state", {"state": "listening_active"})
                                    logger.debug("Speech started")
                                silence_count = 0
                                speech_frames.append(frame_bytes)
                            elif speech_active:
                                silence_count += 1
                                speech_frames.append(frame_bytes)  # Keep trailing audio

                                if silence_count >= SILENCE_THRESHOLD:
                                    # Speech ended — process the utterance
                                    speech_active = False
                                    logger.info(
                                        "Speech ended, %d frames captured",
                                        len(speech_frames),
                                    )
                                    all_audio = b"".join(speech_frames)
                                    speech_frames = []
                                    # Process async
                                    asyncio.create_task(process_utterance(all_audio))

                        return  # Stream ended

            await asyncio.sleep(0.5)

    # Start audio capture in background
    asyncio.create_task(capture_audio_loop())


def _compute_energy(frame_bytes: bytes) -> float:
    """Compute RMS energy of a 16-bit PCM audio frame."""
    if len(frame_bytes) < 2:
        return 0.0
    num_samples = len(frame_bytes) // 2
    samples = struct.unpack(f"<{num_samples}h", frame_bytes[: num_samples * 2])
    if not samples:
        return 0.0
    rms = (sum(s * s for s in samples) / num_samples) ** 0.5
    return rms


if __name__ == "__main__":
    agents.cli.run_app(server)
