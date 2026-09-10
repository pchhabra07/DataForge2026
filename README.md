# EchoCoach — Real-Time Speaking Coach

**EchoCoach** listens while you speak, scores every word, and **speaks the correction back** in a natural human voice using [Rime TTS](https://rime.ai). Read a sentence, get flagged, hear it fixed.

> *When a user mispronounces a target word, EchoCoach detects it within ~1 second and speaks back the correct pronunciation using Rime — first at normal speed, then slowed down word-by-word — so the user can immediately repeat and match it.*

---

## Quick Start

### Prerequisites

- **Node.js** ≥ 18 (for web client)
- **Python** ≥ 3.10 (for agent)
- **ffmpeg** installed on PATH (for audio processing)
- API keys for: **Rime**, **Deepgram**, **LiveKit** (free tiers work)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/pchhabra07/DataForge2026.git
cd DataForge2026

# 2. Create .env.local from the example (fill in your keys)
cp .env.example .env.local
# Web needs only LiveKit vars in web/.env.local - never copy Rime or Deepgram keys there
# Copy these 3 lines manually: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

# 3. Start the Python agent
cd agent
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate
pip install -e ".[dev]"
python -m echocoach.main dev

# 4. In another terminal — start the web client
cd web
npm install
npm run dev
```

Open **http://localhost:3000**, click "Start Coaching Session", and speak!

---

## Architecture

```
                    ┌──────────────────────────────────────────┐
   User speaks →    │  Browser client (mic capture, UI, audio) │
                    └───────────────┬──────────────────────────┘
                                    │  audio (WebRTC / LiveKit)
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │       LiveKit Agent (Python server)      │
                    │  - VAD + turn detection (Silero)         │
                    │  - orchestration & interruption handling │
                    │  - generation fencing for barge-in       │
                    └───┬───────────────┬───────────────┬──────┘
                        │               │               │
            ┌───────────▼──┐   ┌────────▼─────────┐   ┌──▼───────────────┐
            │  ASR (STT)   │   │ Pronunciation    │   │ Coaching Logic   │
            │  Deepgram    │   │ Assessment       │   │ (rules engine):  │
            │  Nova-3      │   │ pronounce-assess │   │ decide what to   │
            │  → words +   │   │ (wav2vec2)       │   │ correct & how    │
            │  timestamps  │   │ → per-word score │   │                  │
            └──────┬───────┘   └────────┬─────────┘   └──────┬───────────┘
                   │                    │                    │
                   └──── "what" ────────┴──── "how" ─────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │   RIME TTS (primary spoken output)         │
                    │   - normal-speed correction                │
                    │   - slowed word-by-word (time_scale_factor)│
                    └──────────────────┬─────────────────────────┘
                                       │  streamed audio
                                       ▼
                              Back to browser → user hears it
```

---

## Third-Party Services

| Layer | Service | Purpose | Cost |
|-------|---------|---------|------|
| **Transport** | [LiveKit](https://livekit.io) | WebRTC rooms, agent orchestration, turn detection | Free tier |
| **STT** | [Deepgram](https://deepgram.com) Nova-3 | Word-level transcription + timestamps + fillers | Free tier |
| **Pronunciation** | [pronounce-assess](https://github.com/thenomadlad/pronounce-assess) (wav2vec2) | Per-word accuracy scoring | Free, on-device |
| **TTS** | [Rime](https://rime.ai) Coda | **Primary spoken output** — corrections, word modeling, slow delivery | API key |
| **Coaching** | Offline rules engine | Picks worst words, templates feedback | Free, on-device |

---

## Rime Configuration

| Parameter | Value |
|-----------|-------|
| **Model** | `coda` |
| **Speaker/Voice** | `celeste` |
| **Language** | `eng` in LiveKit plugin, `en` in direct HTTP preflight, both US English |
| **Audio format** | Streamed PCM/L16 |
| **Transport** | LiveKit (WebRTC) |
| **Normal speed** | `speed_alpha = 1.0` |
| **Slow coaching** | `time_scale_factor = 1.5` |
| **WebSocket** | Yes (normal); HTTP one-shot (slow) |

Rime is the **primary spoken output**. Every correction is spoken by Rime. Removing the spoken output makes the product collapse into a scorecard — the lesson *is* the sound.

---

## Features

### Core Loop
- **Reading mode**: curated target sentences from easy to tongue-twister
- **Per-word scoring**: accuracy, fluency, completeness, prosody
- **Coaching corrections**: flagged words spoken back via Rime (normal + slow)
- **Re-attempt loop**: speak again, see scores update in real time

### Barge-in / Interruption (Phase 5)
- **Full-duplex**: mic keeps recording while Rime speaks
- **Skip button**: stops coaching audio within ≤300ms
- **Generation fencing**: stale corrections cannot re-enter the conversation
- **Voice barge-in**: speaking while coach is correcting auto-interrupts

### Polish (Phase 6)
- **Preset already running**: opens with a pre-scored example (no blank canvas)
- **Truth beside estimate**: flagged words show inline Play/Slow buttons
- **Slow-mode toggle**: global toggle for all Rime output
- **Metrics dashboard**: collapsible panel with latency averages
- **Session timer**: elapsed time in header

---

## Known Limitations

1. **English only** — `en-US` single language for v1
2. **Reading mode only** — free-speak not scored (no reference text)
3. **On-device model size** — wav2vec2 model is ~1.2GB, first run downloads it
4. **ffmpeg required** — audio resampling depends on ffmpeg being on PATH
5. **No persistent sessions** — scores reset when you disconnect
6. **Offline coaching** — feedback comes from a local rules engine, no LLM key needed

---

## Failure Behavior

| Scenario | Behavior |
|----------|----------|
| Rime API down | Agent fails to speak; error logged; client shows "Agent not connected" |
| Deepgram API down | No transcription; pronunciation assessment still runs on raw audio |
| Pronunciation model fails to load | Falls back to mock assessment for UI testing |
| User barge-in during correction | Audio stops ≤300ms; stale corrections fenced out |
| Very short utterance (<100ms) | Silently dropped, no assessment attempted |

---

## Project Structure

```
DataForge2026/
├── agent/                  # Python LiveKit agent
│   ├── echocoach/
│   │   ├── main.py         # Agent entry point, session handler
│   │   ├── coaching.py     # Offline rules coaching logic
│   │   ├── pronunciation.py # On-device wav2vec2 scoring
│   │   ├── measure.py      # Session metrics accumulator
│   │   └── sentences.py    # Target sentence bank
│   └── pyproject.toml
├── web/                    # Next.js web client
│   ├── app/
│   │   ├── page.tsx        # Main UI
│   │   ├── globals.css     # Console-style design system
│   │   ├── lib/metrics.ts  # WPM, fillers, pipeline metrics
│   │   └── api/token/      # LiveKit token endpoint
│   └── package.json
├── docs/
│   ├── PRD.md              # Product requirements
│   ├── IMPLEMENTATION_PLAN.md
│   └── RIME_EVIDENCE.md    # Hard voice problem evidence
├── fixtures/               # Test clips, variants, measurements
├── scripts/                # Preflight, token gen, latency measurement
├── .env.example            # Template (no secrets)
└── README.md               # This file
```

---

## Development

```bash
# Lint agent
cd agent && ruff check echocoach/

# Typecheck web
cd web && npm run typecheck

# Measure latencies
cd agent && python ../scripts/measure_latency.py
```

---

## License

Built for DataForge 2026 — Rime Hackathon Challenge.
