# EchoCoach — Real-Time Speaking Coach

> **EchoCoach** listens while you speak, detects *how* you spoke (pronunciation, filler words, pace, fluency) — not just *what* you said — and immediately models the correct version back to you in a natural human voice using **Rime TTS**.

🏆 **DataForge 2026 — Rime Hackathon Challenge**

---

## Quick Start

### Prerequisites

- Python ≥ 3.10
- Node.js ≥ 20
- A [LiveKit Cloud](https://cloud.livekit.io) account (free tier)
- API keys: Rime, Deepgram, Azure Speech, OpenAI (see `.env.example`)

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
.venv/Scripts/activate     # Windows
# source .venv/bin/activate  # macOS/Linux
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

```bash
cd agent
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
              ├── Pronunciation: Azure Speech Assessment
              ├── Coaching Logic: LLM (error selection)
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
| [Azure Speech](https://azure.microsoft.com/en-us/products/ai-services/speech-service) | Pronunciation assessment | ✅ |
| [OpenAI](https://openai.com) | LLM coaching logic | ✅ |

## Known Limitations

- English only (`en-US`).
- Reading mode only (scripted target sentences).
- Requires stable internet for all API calls.
- First Rime call may have higher latency (cold start).

## License

MIT
