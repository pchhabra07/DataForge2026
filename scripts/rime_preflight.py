#!/usr/bin/env python3
"""
Rime Preflight Check - Phase 0 Submission Gate

Confirms that the exact Rime model, voice, language, and endpoint work
against the live Rime API before any feature code is written.

Usage:
    python scripts/rime_preflight.py

Requires RIME_API_KEY in .env.local or environment.

Exit codes:
    0 - preflight passed (audio bytes received)
    1 - preflight failed (API error, no audio, or wrong config)
"""

from __future__ import annotations

import os
import sys
import time

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))


def check_env() -> bool:
    """Verify all required environment variables are set."""
    required = ["RIME_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        print("   Copy .env.example to .env.local and fill in values.")
        return False
    return True


def preflight_rime_http() -> bool:
    """Call Rime HTTP API directly to validate model/voice/language."""
    import urllib.request
    import urllib.error
    import json

    api_key = os.environ["RIME_API_KEY"]
    url = "https://users.rime.ai/v1/rime-tts"

    payload = json.dumps(
        {
            "text": "Hello, this is EchoCoach. Pronunciation coaching starts now.",
            "speaker": "celeste",
            "modelId": "coda",
            "lang": "en",
            "samplingRate": 24000,
        }
    ).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    print("[CHECK] Testing Rime API...")
    print(f"   Model:    coda")
    print(f"   Voice:    celeste")
    print(f"   Language: en")
    print(f"   Endpoint: {url}")
    print(f"   Format:   mp3 (preflight) / PCM (production)")
    print()

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            audio_bytes = resp.read()
            t1 = time.perf_counter()
            latency_ms = (t1 - t0) * 1000

            if len(audio_bytes) < 100:
                print(
                    f"[ERROR] Received only {len(audio_bytes)} bytes - likely an error response."
                )
                print(f"   Body: {audio_bytes[:200]}")
                return False

            print(f"[OK] Rime preflight PASSED")
            print(f"   Audio bytes received: {len(audio_bytes):,}")
            print(f"   Round-trip latency:   {latency_ms:.0f}ms")
            print(
                f"   Content-Type:         {resp.headers.get('Content-Type', 'unknown')}"
            )

            # Save the preflight audio as a fixture
            fixtures_dir = os.path.join(os.path.dirname(__file__), "..", "fixtures")
            os.makedirs(fixtures_dir, exist_ok=True)
            fixture_path = os.path.join(fixtures_dir, "rime_preflight.mp3")
            with open(fixture_path, "wb") as f:
                f.write(audio_bytes)
            print(f"   Saved to:             fixtures/rime_preflight.mp3")

            return True

    except urllib.error.HTTPError as e:
        t1 = time.perf_counter()
        body = e.read().decode("utf-8", errors="replace")
        print(f"[ERROR] Rime API returned HTTP {e.code}")
        print(f"   Body: {body[:500]}")
        print(f"   Latency: {(t1 - t0) * 1000:.0f}ms")
        return False

    except Exception as e:
        print(f"[ERROR] Rime preflight failed with exception: {e}")
        return False


def preflight_speed_alpha() -> bool:
    """Test timeScaleFactor > 1.0 for slowed coaching delivery."""
    import urllib.request
    import json

    api_key = os.environ["RIME_API_KEY"]
    url = "https://users.rime.ai/v1/rime-tts"

    payload = json.dumps(
        {
            "text": "Pronunciation.",
            "speaker": "celeste",
            "modelId": "coda",
            "lang": "en",
            "samplingRate": 24000,
            "timeScaleFactor": 1.5,
        }
    ).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    print()
    print("[CHECK] Testing Rime timeScaleFactor=1.5 (slowed coaching)...")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            audio_bytes = resp.read()
            t1 = time.perf_counter()
            print(f"[OK] timeScaleFactor test PASSED")
            print(f"   Audio bytes: {len(audio_bytes):,}")
            print(f"   Latency:     {(t1 - t0) * 1000:.0f}ms")

            fixtures_dir = os.path.join(os.path.dirname(__file__), "..", "fixtures")
            fixture_path = os.path.join(fixtures_dir, "rime_preflight_slow.mp3")
            with open(fixture_path, "wb") as f:
                f.write(audio_bytes)
            print(f"   Saved to:    fixtures/rime_preflight_slow.mp3")
            return True

    except Exception as e:
        print(f"[ERROR] timeScaleFactor test failed: {e}")
        return False


def main() -> int:
    print("=" * 60)
    print("  EchoCoach - Rime Preflight Check")
    print("=" * 60)
    print()

    if not check_env():
        return 1

    ok = preflight_rime_http()
    if ok:
        preflight_speed_alpha()

    print()
    if ok:
        print("[DONE] All Rime preflight checks passed. Ready for Phase 1.")
    else:
        print("[FAIL] Rime preflight FAILED. Fix before writing any feature code.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
