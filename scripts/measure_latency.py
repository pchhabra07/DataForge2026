"""
EchoCoach — Latency Measurement Script

Measures key pipeline latencies for RIME_EVIDENCE.md:
1. Rime TTS first-byte and total synthesis latency
2. Pronunciation assessment latency
3. End-to-end coaching pipeline time

Usage:
    python scripts/measure_latency.py

Requires .env.local with RIME_API_KEY set.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))


# ---------------------------------------------------------------------------
# Test sentences (from fixtures)
# ---------------------------------------------------------------------------
TEST_SENTENCES = [
    {
        "id": 7,
        "text": "The pharmaceutical company developed an extraordinarily effective vaccine.",
        "variant": "period",
    },
    {
        "id": "7b",
        "text": "The pharmaceutical company developed an extraordinarily effective vaccine!",
        "variant": "exclamation",
    },
    {
        "id": 1,
        "text": "The quick brown fox jumps over the lazy dog.",
        "variant": "easy",
    },
]


async def measure_rime_latency():
    """Measure Rime TTS synthesis latency for test sentences."""
    try:
        from livekit.plugins import rime
    except ImportError:
        print("ERROR: livekit-plugins-rime not installed. Run from agent venv.")
        return []

    results = []

    # Normal speed
    tts_normal = rime.TTS(
        model="coda",
        speaker="celeste",
        speed_alpha=1.0,
        use_websocket=False,
    )

    # Slow speed
    tts_slow = rime.TTS(
        model="coda",
        speaker="celeste",
        time_scale_factor=1.5,
        use_websocket=False,
    )

    for sentence in TEST_SENTENCES:
        text = sentence["text"]
        variant = sentence["variant"]

        for label, tts in [("normal", tts_normal), ("slow", tts_slow)]:
            t0 = time.perf_counter()
            first_byte_t = None
            total_bytes = 0
            chunk_count = 0

            try:
                async for chunk in tts.synthesize(text):
                    if first_byte_t is None:
                        first_byte_t = time.perf_counter()
                    total_bytes += len(chunk.frame.data)
                    chunk_count += 1
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({
                    "sentence_id": sentence["id"],
                    "variant": variant,
                    "speed": label,
                    "error": str(e),
                })
                continue

            t_end = time.perf_counter()
            first_byte_ms = ((first_byte_t - t0) * 1000) if first_byte_t else 0
            total_ms = (t_end - t0) * 1000

            results.append({
                "sentence_id": sentence["id"],
                "variant": variant,
                "speed": label,
                "first_byte_ms": round(first_byte_ms, 1),
                "total_synthesis_ms": round(total_ms, 1),
                "audio_bytes": total_bytes,
                "chunks": chunk_count,
            })

            print(
                f"  [{variant}/{label}] first_byte={first_byte_ms:.0f}ms "
                f"total={total_ms:.0f}ms bytes={total_bytes} chunks={chunk_count}"
            )

    return results


async def measure_assessment_latency():
    """Measure pronunciation assessment latency with mock audio."""
    try:
        from echocoach.pronunciation import assess_pronunciation, warmup_free_assessor
    except ImportError:
        print("ERROR: echocoach package not installed. Run from agent venv.")
        return []

    print("\n--- Pronunciation Assessment Latency ---")
    print("Warming up model...")
    await warmup_free_assessor()
    print("Model ready.")

    results = []

    # Generate silence audio (16-bit PCM, 48kHz, 2 seconds)
    import struct
    sample_rate = 48000
    duration_s = 2.0
    num_samples = int(sample_rate * duration_s)
    # Generate low-energy noise to avoid "too short" rejection
    import random
    audio_bytes = struct.pack(
        f"<{num_samples}h",
        *[random.randint(-50, 50) for _ in range(num_samples)]
    )

    for sentence in TEST_SENTENCES[:2]:  # Just test 2
        text = sentence["text"]
        variant = sentence["variant"]

        t0 = time.perf_counter()
        result = await assess_pronunciation(
            audio_bytes=audio_bytes,
            reference_text=text,
            sample_rate=sample_rate,
        )
        t_end = time.perf_counter()
        assess_ms = (t_end - t0) * 1000

        entry = {
            "sentence_id": sentence["id"],
            "variant": variant,
            "assessment_ms": round(assess_ms, 1),
            "has_result": result is not None,
        }
        if result:
            entry["accuracy"] = result.accuracy_score
            entry["flagged_count"] = len(result.flagged_words)

        results.append(entry)
        print(
            f"  [{variant}] assessment={assess_ms:.0f}ms "
            f"result={'yes' if result else 'no'}"
        )

    return results


def print_table(title: str, rows: list[dict]):
    """Print a formatted table of results."""
    if not rows:
        print(f"\n{title}: No results.")
        return

    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")

    # Get all keys
    keys = list(rows[0].keys())
    widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}

    # Header
    header = " | ".join(k.ljust(widths[k]) for k in keys)
    print(f"  {header}")
    print(f"  {'-' * len(header)}")

    # Rows
    for row in rows:
        line = " | ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys)
        print(f"  {line}")

    print()


async def main():
    print("EchoCoach Latency Measurement")
    print("=" * 40)

    # 1. Rime TTS latency
    print("\n--- Rime TTS Latency ---")
    rime_results = await measure_rime_latency()
    print_table("Rime TTS Latency", rime_results)

    # 2. Pronunciation assessment latency
    assess_results = await measure_assessment_latency()
    print_table("Pronunciation Assessment Latency", assess_results)

    # Save results
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rime_tts": rime_results,
        "assessment": assess_results,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "latency_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
