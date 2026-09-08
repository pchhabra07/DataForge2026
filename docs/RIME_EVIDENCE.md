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
2. While Rime is speaking the correction, either:
   a. Speak aloud (voice barge-in), or
   b. Click the "Skip ⏭" button in the transport deck.

**Expected result:**
- Rime audio stops within ≤300ms of barge-in.
- No stale correction audio plays afterward.
- App state transitions from `coaching` → `listening`.
- A "⏭ Skipped" toast briefly appears.
- The generation fence prevents any in-flight corrections from being spoken.

**Implementation:**
- Agent uses a monotonically increasing `correction_gen` counter.
- Each correction run checks its generation before every `session.say()`.
- Barge-in (voice or button) increments the counter and calls `session.interrupt()`.
- Stale results are silently discarded.

### Test 4: Punctuation Variant Delivery

**Procedure:**
1. Compare fixtures `variant_1.json` (period) and `variant_2.json` (exclamation).
2. The same sentence with different terminal punctuation.

**Expected result:**
- The exclamation variant has slightly rising/emphatic intonation on the final word.
- Both are intelligible and natural.

---

## Preflight Check

Run before submission:

```bash
python scripts/rime_preflight.py
```

This script validates:
- Rime API key is set and works
- Model `coda` + voice `celeste` returns audio
- `timeScaleFactor=1.5` returns audio (slowed delivery)
- Saves fixture audio files to `fixtures/`

Last run: 2026-09-06, both checks PASSED via `https://users.rime.ai/v1/rime-tts`.

---

## Results

> Preflight measured on 2026-09-06. Pipeline metrics are tracked per-session by `measure.py` and sent to the client metrics panel.

| Metric | Target | Measured (uncached) | Measured (cached) | Notes |
|--------|--------|--------------------|--------------------|-------|
| Preflight normal clip latency | — | 2866ms, 84960 bytes | — | Initial cold call |
| Preflight slowed clip latency | — | 1432ms, 35520 bytes | — | timeScaleFactor=1.5 |
| Detection→correction latency | ≤ 1s | *see metrics panel* | *see metrics panel* | End of speech → first Rime byte |
| Pronunciation flag accuracy | ≥ 8/10 | *see metrics panel* | — | Per-word wav2vec2 GOP |
| Interruption stop time | ≤ 300ms | *see metrics panel* | — | Generation fence + session.interrupt() |
| Slow-mode intelligibility | Natural (human check) | Pass | — | Human-verified on preflight clip |

**How to measure live:** Open the app, run attempts, and click "▸ Show metrics" below the coaching output. The panel shows per-attempt and running average latencies.

**Automated measurement:**
```bash
cd agent
python ../scripts/measure_latency.py
```
Results are saved to `fixtures/latency_results.json`.

---

## Limitations

1. **English only** — `en-US` single language for v1.
2. **Reading mode only** — scripted target sentences, no free-speak scoring.
3. **Pronunciation scoring is approximate** — on-device GOP (goodness of pronunciation) estimates from wav2vec2, not human grades. Words missing from the phoneme dictionary get the sentence average and are never flagged.
4. **Rime latency varies** — by region and API load; uncached first call may exceed the 1s target. Subsequent calls benefit from connection reuse.
5. **No persistent sessions** — scores and metrics reset on disconnect.
6. **Barge-in depends on VAD** — voice-triggered interruption requires speech energy above threshold. The Skip button is the reliable fallback.
7. **LLM coaching optional** — without `OPENAI_API_KEY`, coaching uses rules-based fallback (still functional).

---

## Fixtures

| File | Description |
|------|-------------|
| `fixtures/rime_preflight.mp3` | Normal-speed greeting from preflight |
| `fixtures/rime_preflight_slow.mp3` | Slowed greeting from preflight (speed_alpha=1.5) |
| `fixtures/variant_1.json` | Sentence with period — standard delivery |
| `fixtures/variant_2.json` | Same sentence with exclamation — emphatic delivery |
| `fixtures/latency_results.json` | Automated measurement results (generated by `measure_latency.py`) |

*Variant fixtures document how punctuation changes Rime's spoken delivery, as required by PRD §6.*
