# RIME_EVIDENCE.md — EchoCoach

## Rime Configuration (Locked)

| Parameter       | Value                          |
|-----------------|--------------------------------|
| **Model**       | `coda` (primary quality)       |
| **Fallback**    | `mistv3` (lowest latency)      |
| **Voice**       | `celeste`                      |
| **Language**     | `en`                          |
| **Endpoint**    | Rime API via `livekit-plugins-rime` |
| **Audio format**| Streamed PCM/L16 (WebSocket)   |
| **Transport**   | LiveKit (WebRTC)               |
| **Speed control**| `speed_alpha > 1.0` for slowed word-by-word coaching |

---

## The Hard Voice Claim

### Headline: Pronunciation & Controlled Delivery

**Claim:** When a user mispronounces a target word while reading a sentence, EchoCoach detects it within ~1 second and speaks back the correct pronunciation using Rime — first at normal speed, then slowed down word-by-word — so the user can immediately repeat and match it.

### Supporting: Interruption & Recovery (barge-in)

**Claim:** While the coach is speaking a correction, the user can cut in ("skip", "next word"). Queued Rime audio stops within ≤300ms, stale corrections do not re-enter the conversation, and app state stays consistent.

---

## Acceptance Test

### Test 1: Corrective Pronunciation (Core)

**Procedure:**
1. Open EchoCoach in a browser.
2. Read the target sentence on screen.
3. Deliberately mispronounce one word (e.g., "peculiar" → "pee-CUE-lee-ar").
4. Wait for the coach to respond.

**Expected result:**
- EchoCoach detects the mispronunciation within ~1s.
- Rime TTS speaks the correct pronunciation at normal speed.
- Rime TTS then speaks the word slowed down (speed_alpha > 1.0).
- User can hear both clips clearly in the browser.

**Measured metrics:**
- Detection-to-correction latency: ≤ 1s (target)
- Flag accuracy: ≥ 8/10 deliberately mispronounced words

### Test 2: Speed Alpha (Slowed Delivery)

**Procedure:**
1. Trigger a correction (per Test 1).
2. Listen to the slowed-down word-by-word clip.

**Expected result:**
- Slowed clip is intelligible and sounds natural.
- Speed is noticeably slower than normal.

### Test 3: Interruption / Barge-in

**Procedure:**
1. Trigger a correction.
2. While Rime is speaking the correction, speak "skip" or "next".

**Expected result:**
- Rime audio stops within ≤300ms of barge-in.
- No stale correction audio plays afterward.
- App state is consistent with what the user heard.

---

## Preflight Check

Run before submission:

```bash
python scripts/rime_preflight.py
```

This script validates:
- Rime API key is set and works
- Model `coda` + voice `celeste` returns audio
- `speed_alpha=1.5` returns audio (slowed delivery)
- Saves fixture audio files to `fixtures/`

---

## Results

> **TODO:** Fill in measured values after Phase 4–6.

| Metric | Target | Measured (uncached) | Measured (cached) |
|--------|--------|--------------------|--------------------|
| Detection→correction latency | ≤ 1s | — | — |
| Pronunciation flag accuracy | ≥ 8/10 | — | — |
| Interruption stop time | ≤ 300ms | — | — |
| Slow-mode intelligibility | Natural (human check) | — | — |

---

## Limitations

- English only (`en-US`).
- Reading mode only (scripted target sentence).
- Pronunciation scoring depends on Azure Speech Assessment accuracy.
- Rime latency varies by region and load; uncached first call may exceed target.

---

## Fixtures

| File | Description |
|------|-------------|
| `fixtures/rime_preflight.mp3` | Normal-speed greeting from preflight |
| `fixtures/rime_preflight_slow.mp3` | Slowed greeting from preflight (speed_alpha=1.5) |

*More fixtures will be added during Phase 6 (evidence discipline).*
