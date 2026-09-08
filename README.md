# EchoCoach — Real-Time Speaking Coach

> **EchoCoach** listens while you speak, detects *how* you spoke (pronunciation, filler words, pace, fluency) — not just *what* you said — and immediately models the correct version back to you in a natural human voice using **Rime TTS**.

🏆 **DataForge 2026 — Rime Hackathon Challenge**

---

## Quick Start

### Prerequisites

- Python ≥ 3.10
- Node.js ≥ 20
- ffmpeg installed and on PATH (audio decode for scoring)
- A [LiveKit Cloud](https://cloud.livekit.io) account (free tier)
- API keys: Rime, Deepgram, OpenAI (see `.env.example`)
- Pronunciation scoring is free and on-device, no key needed.
  First run downloads a ~1.2GB model to the HuggingFace cache.

### 1. Clone & Configure

```bash
git clone https://github.com/YOUR_USERNAME/DataForge2026.git
cd DataForge2026
cp .env.example .env.local
# Fill in your API keys in .env.local
```

### 2. Agent (Python)

```bash
cd agent
python -m venv .venv
```

Activate the venv every time before running the agent:

```powershell
.\.venv\Scripts\Activate.ps1
```

```bash
pip install -e ".[dev]"
```

### 3. Web Client (Next.js)

```bash
cd web
npm install
```

### 4. Run Rime Preflight (do this first!)

```bash
python scripts/rime_preflight.py
```

This validates your Rime API key, model, voice, and speed control work.

### 5. Start the Agent

Keep this terminal running. Open a new terminal for the web client.

```bash
cd agent
.\.venv\Scripts\Activate.ps1
python -m echocoach.main dev
```

### 6. Start the Web Client

```bash
cd web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Architecture

```
User speaks → Browser (mic, UI, audio playback)
                    ↓ WebRTC via LiveKit
              LiveKit Agent (Python)
               ├── STT: Deepgram (words + timestamps)
               ├── Pronunciation: free on-device engine (wav2vec2 phonemes)
               ├── Coaching Logic: LLM (error selection, rules fallback)
               └── TTS: Rime (primary spoken output)
                    ↓ streamed audio
              Back to browser → user hears correction
```

## Rime Configuration

| Parameter | Value |
|-----------|-------|
| Model | `coda` (primary), `mistv3` (fallback) |
| Voice | `celeste` |
| Language | `en` |
| Audio | Streamed PCM/L16 via WebSocket |
| Transport | LiveKit (WebRTC) |
| Speed | `speed_alpha > 1.0` for slowed coaching |

## Project Structure

```
DataForge2026/
├── agent/              # Python LiveKit agent
│   ├── echocoach/      # Agent source code
│   └── pyproject.toml  # Python dependencies
├── web/                # Next.js web client
│   ├── app/            # App Router pages & API
│   └── package.json    # Node dependencies
├── scripts/            # Utility scripts
│   ├── rime_preflight.py
│   └── generate_token.py
├── fixtures/           # Recorded audio fixtures
├── docs/               # PRD, implementation plan, evidence
│   ├── PRD.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── RIME_EVIDENCE.md
├── .env.example        # API key placeholders (no secrets!)
└── .gitignore
```

## Third-Party Services

| Service | Purpose | Required |
|---------|---------|----------|
| [Rime](https://rime.ai) | TTS — primary spoken output | ✅ |
| [LiveKit](https://livekit.io) | WebRTC transport & orchestration | ✅ |
| [Deepgram](https://deepgram.com) | Speech-to-text (word timestamps) | ✅ |
| pronounce-assess (MIT) | On-device pronunciation scoring, no key | ✅ |
| [OpenAI](https://openai.com) | LLM coaching logic (rules fallback) | Optional |

## Known Limitations

- English only (`en-US`).
- Reading mode only (scripted target sentences).
- Requires stable internet for LiveKit, Rime, Deepgram calls. Scoring itself is offline.
- First scoring attempt loads the model (about 15s once per session, warmed up at start).
- Words missing from the phoneme dictionary get the sentence average, never flagged.

## License

MIT
