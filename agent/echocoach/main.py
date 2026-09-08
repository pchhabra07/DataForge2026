"""
EchoCoach — LiveKit Agent Entry Point (Phase 5+6)

This agent joins a LiveKit room, presents target sentences for reading practice,
captures user audio, runs free on-device pronunciation assessment, generates
coaching feedback via LLM, and speaks corrections using Rime TTS (normal + slow speed).

Phase 3: pronunciation assessment with per-word scoring
Phase 4: coaching logic + corrective Rime at normal/slow speed
Phase 5: interruption / barge-in with generation fencing
Phase 6: preset-already-running, metrics measurement, polish
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
from echocoach.measure import MetricsSample, SessionMetrics
from echocoach.pronunciation import (
    assess_pronunciation,
    warmup_free_assessor,
)
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

    Phase 5+6: pronunciation assessment + coaching corrections via Rime
    with barge-in support and generation fencing.
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
    6. Handle barge-in: stop TTS, fence stale corrections
    """
    t0 = time.perf_counter()
    logger.info("EchoCoach session starting…")

    # Track current target sentence
    current_sentence = get_first_sentence()

    # --- Phase 5: Generation fence for barge-in ---
    # Each correction run gets a generation number. Before any say() or
    # send_to_client() in the coaching path, check that the current gen
    # hasn't been superseded. If it has, bail silently.
    correction_gen = 0
    speaking_active = False
    session_metrics = SessionMetrics()

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
        frames = await fetch_slow_frames(text)
        await _play_slow_frames(text, frames)

    async def fetch_slow_frames(text: str) -> list[rtc.AudioFrame]:
        """Synthesize slow audio without playing it, so callers can fence first."""
        frames: list[rtc.AudioFrame] = []
        async for chunk in slow_tts.synthesize(text):
            frames.append(chunk.frame)
        return frames

    async def _play_slow_frames(text: str, frames: list[rtc.AudioFrame]):
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

    async def _report_model_progress() -> None:
        """Poll download bytes and stream live progress to the client."""
        from echocoach.pronunciation import get_download_progress

        last_sent = -1
        for _ in range(1200):
            await asyncio.sleep(0.5)
            snap = get_download_progress()
            if snap["phase"] != "downloading" or not snap["total"]:
                continue
            total = snap["total"] or 0
            done = snap["downloaded"] or 0
            percent = round(100.0 * done / total, 1) if total > 0 else 0.0
            if percent - last_sent >= 1.0 or (percent >= 100.0 and last_sent < 100):
                last_sent = percent
                await send_to_client(
                    "model_status",
                    {
                        "status": "downloading",
                        "file": snap["file"],
                        "downloadedBytes": done,
                        "totalBytes": total,
                        "percent": percent,
                    },
                )
            if percent >= 100.0:
                return

    asyncio.create_task(
        warmup_free_assessor(
            lambda status, **info: send_to_client("model_status", {"status": status, **info})
        )
    )
    asyncio.create_task(_report_model_progress())

    # --- Phase 5: Generation-fenced say helper ---
    async def say_fenced(text: str, gen: int) -> bool:
        """Speak text via Rime, but bail if generation has been superseded.

        Returns True if the speech completed, False if fenced out.
        """
        nonlocal speaking_active
        if gen != correction_gen:
            logger.debug("Fenced out say() for gen %d (current=%d)", gen, correction_gen)
            return False
        speaking_active = True
        try:
            await session.say(text)
        finally:
            speaking_active = False
        return gen == correction_gen

    async def say_slow_fenced(text: str, gen: int) -> bool:
        """Speak text at slow speed, but bail if generation has been superseded."""
        if gen != correction_gen:
            logger.debug("Fenced out slow say() for gen %d (current=%d)", gen, correction_gen)
            return False
        frames = await fetch_slow_frames(text)
        if gen != correction_gen:
            logger.debug("Fenced out slow playback for gen %d (current=%d)", gen, correction_gen)
            return False
        nonlocal speaking_active
        speaking_active = True
        try:
            await _play_slow_frames(text, frames)
        finally:
            speaking_active = False
        return gen == correction_gen

    # --- Phase 5: Interrupt helper ---
    async def interrupt_coaching(source: str = "unknown"):
        """Stop current coaching output and fence stale corrections."""
        nonlocal correction_gen
        was_speaking = speaking_active
        correction_gen += 1
        logger.info(
            "Interrupting coaching (source=%s, new_gen=%d, was_speaking=%s)",
            source,
            correction_gen,
            was_speaking,
        )

        if was_speaking:
            t_interrupt = time.perf_counter()
            try:
                maybe = session.interrupt()
                if asyncio.isfuture(maybe) or asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                logger.debug("session.interrupt() not available or failed")

            interrupt_ms = (time.perf_counter() - t_interrupt) * 1000
            session_metrics.record_interruption(interrupt_ms)
            await send_to_client(
                "interruption",
                {
                    "interruptionMs": round(interrupt_ms, 1),
                    "source": source,
                    "gen": correction_gen,
                },
            )
            logger.info("Interruption complete in %.1fms (source=%s)", interrupt_ms, source)

        await send_to_client("state", {"state": "listening"})

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

    # --- Speak greeting with target sentence (fenced, user can barge in) ---
    greeting = (
        f"Welcome to EchoCoach! Let's practice your pronunciation. "
        f"Please read this sentence aloud: {current_sentence.text}"
    )
    t_speak = time.perf_counter()
    correction_gen += 1
    greet_ok = await say_fenced(greeting, correction_gen)
    t_done = time.perf_counter()
    logger.info(f"Rime greeting latency: {(t_done - t_speak) * 1000:.0f}ms (completed={greet_ok})")

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
        nonlocal current_sentence, speaking_active
        await interrupt_coaching("next_sentence")
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
        speaking_active = True
        try:
            await session.say(f"Great, let's try this one: {current_sentence.text}")
        finally:
            speaking_active = False
        return json.dumps({"id": current_sentence.id, "text": current_sentence.text})

    @ctx.room.local_participant.register_rpc_method("hear_word")
    async def handle_hear_word(data: rtc.RpcInvocationData):
        """Client requests to hear a specific word spoken by Rime."""
        nonlocal speaking_active
        try:
            payload = json.loads(data.payload)
            word = payload.get("word", "")
            speed = payload.get("speed", "normal")  # "normal" or "slow"
            if not word:
                return json.dumps({"error": "No word specified"})

            await interrupt_coaching("hear_word")
            speaking_active = True
            try:
                if speed == "slow":
                    # Use slow TTS for word-by-word modeling
                    await say_slow(word)
                else:
                    await session.say(word)
            finally:
                speaking_active = False
            return json.dumps({"ok": True, "word": word, "speed": speed})
        except Exception as e:
            logger.exception("hear_word RPC error")
            return json.dumps({"error": str(e)})

    # --- Phase 5: Skip correction RPC ---
    @ctx.room.local_participant.register_rpc_method("skip_correction")
    async def handle_skip_correction(data: rtc.RpcInvocationData):
        """Client pressed Skip — stop coaching, fence stale corrections."""
        await interrupt_coaching("skip_button")
        return json.dumps({"ok": True, "gen": correction_gen})

    # --- Process user audio for pronunciation assessment ---
    @_serialize_utterances
    async def process_utterance(audio_data: bytes, ref_text: str):
        """Run pronunciation assessment + coaching on captured audio."""
        try:
            await _process_utterance_inner(audio_data, ref_text)
        except Exception:
            logger.exception("Utterance processing failed, returning to listening")
            await send_to_client("state", {"state": "listening"})

    async def _process_utterance_inner(audio_data: bytes, ref_text: str):
        nonlocal correction_gen

        if len(audio_data) < 4800:  # Too short
            logger.debug("Utterance too short (%d bytes), skipping", len(audio_data))
            return

        snap_gen = correction_gen
        t_assess_start = time.perf_counter()

        # Send "assessing" state to client
        await send_to_client("state", {"state": "assessing"})

        # Run pronunciation assessment in a worker thread
        result = await assess_pronunciation(
            audio_bytes=bytes(audio_data),
            reference_text=ref_text,
            sample_rate=LIVEKIT_SAMPLE_RATE,
        )

        if result is None:
            logger.warning("Pronunciation assessment returned no result")
            await send_to_client("state", {"state": "listening"})
            return

        if snap_gen != correction_gen:
            logger.info("Utterance superseded during assessment, dropping stale result")
            return

        if (result.completeness_score or 0) < 20:
            logger.info(
                "Discarding assessment with no usable speech (completeness=%.1f)",
                result.completeness_score or 0,
            )
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
        result_data["isDemo"] = False
        await send_to_client("pronunciation", result_data)

        # --- Phase 4+5: Generate and speak coaching correction (fenced) ---
        if result.has_issues:
            # Bump generation for this correction run
            correction_gen += 1
            my_gen = correction_gen

            await send_to_client("state", {"state": "coaching"})

            # Generate coaching plan
            flagged_dicts = [w.to_dict() for w in result.flagged_words]
            correction = await generate_correction(
                flagged_words=flagged_dicts,
                reference_text=ref_text,
            )

            # Check fence before sending coaching data
            if my_gen != correction_gen:
                logger.info("Correction fenced out (gen %d != %d)", my_gen, correction_gen)
                return

            # Send coaching plan to client
            correction_data = correction.to_dict()
            correction_data["isDemo"] = False
            await send_to_client("coaching", correction_data)

            # Speak the coaching feedback via Rime (normal speed), fenced
            t_correction_start = time.perf_counter()
            if not await say_fenced(correction.coaching_text, my_gen):
                logger.info("Coaching speech interrupted at coaching_text")
                return

            # Speak each flagged word at normal speed, then slow — fenced
            for word in correction.words_to_model:
                if not await say_fenced(f"The word is: {word}", my_gen):
                    logger.info("Coaching speech interrupted at word '%s'", word)
                    return
                await asyncio.sleep(0.3)  # Brief pause
                if my_gen != correction_gen:
                    logger.info("Coaching fenced during pause at word '%s'", word)
                    return
                if not await say_slow_fenced(f"Now slowly: {word}", my_gen):
                    logger.info("Coaching slow speech interrupted at word '%s'", word)
                    return
                await asyncio.sleep(0.3)
                if my_gen != correction_gen:
                    logger.info("Coaching fenced during pause at word '%s'", word)
                    return

            t_correction_end = time.perf_counter()
            correction_ms = (t_correction_end - t_correction_start) * 1000
            total_ms = (t_correction_end - t_assess_start) * 1000

            logger.info(
                "Coaching complete: correction=%.0fms, total_pipeline=%.0fms",
                correction_ms,
                total_ms,
            )

            # Record metrics
            sample = MetricsSample(
                assessment_ms=assess_ms,
                correction_ms=correction_ms,
                total_pipeline_ms=total_ms,
                flagged_word_count=len(result.flagged_words),
                correction_source=correction.source,
            )
            session_metrics.record(sample)

            # Send enriched metrics to client
            if my_gen == correction_gen:
                await send_to_client("metrics", session_metrics.latest_dict())
                await say_fenced("Now try reading the sentence again!", my_gen)
        else:
            # No issues — encourage and move on
            sample = MetricsSample(
                assessment_ms=assess_ms,
                flagged_word_count=0,
                correction_source="none",
            )
            session_metrics.record(sample)
            nonlocal speaking_active
            speaking_active = True
            try:
                await session.say("Excellent pronunciation! You nailed that sentence. Well done!")
            finally:
                speaking_active = False
            await send_to_client("metrics", session_metrics.latest_dict())

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
                        voiced_frames = 0
                        speech_active = False
                        turn_tainted = False
                        last_speaking_seen = 0.0
                        ECHO_TAIL_S = 1.5
                        MIN_VOICED_FRAMES = 25
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

                            if speaking_active:
                                last_speaking_seen = time.perf_counter()

                            if energy > 200:  # Speech threshold
                                if not speech_active:
                                    speech_active = True
                                    speech_frames = []
                                    voiced_frames = 0
                                    # Turns starting while the coach speaks are
                                    # mostly speaker echo, never score them.
                                    # The tail covers echo lingering right after
                                    # an interrupt stops coach speech.
                                    turn_tainted = speaking_active or (
                                        time.perf_counter() - last_speaking_seen < ECHO_TAIL_S
                                    )
                                    turn_tainted = speaking_active
                                    # Phase 5: interrupt coaching when user starts speaking
                                    asyncio.create_task(interrupt_coaching("user_speech"))
                                    await send_to_client("state", {"state": "listening_active"})
                                    logger.debug("Speech started")
                                if speaking_active:
                                    turn_tainted = True
                                silence_count = 0
                                voiced_frames += 1
                                speech_frames.append(frame_bytes)
                            elif speech_active:
                                silence_count += 1
                                speech_frames.append(frame_bytes)

                                if silence_count >= SILENCE_THRESHOLD:
                                    speech_active = False
                                    logger.info(
                                        "Speech ended, %d frames captured",
                                        len(speech_frames),
                                    )
                                    if turn_tainted:
                                        logger.info(
                                            "Discarding turn overlapping coach speech (echo)"
                                        )
                                        speech_frames = []
                                        continue
                                    if voiced_frames < MIN_VOICED_FRAMES:
                                        logger.info("Discarding turn with too little voiced audio")
                                        speech_frames = []
                                        continue
                                    all_audio = b"".join(speech_frames)
                                    speech_frames = []
                                    # Snapshot the sentence so a mid-pipeline
                                    # next_sentence cannot misattribute audio
                                    ref_snapshot = current_sentence.text
                                    # Process async
                                    asyncio.create_task(process_utterance(all_audio, ref_snapshot))

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
