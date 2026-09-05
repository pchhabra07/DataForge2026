# EchoCoach — Implementation Plan

## Core target (never lose sight)
Detect mispronunciation/filler while the user speaks, then within ~1s speak back the correct pronunciation via **Rime** — normal speed first, then slowed word-by-word. Rime is the primary spoken output. Everything else serves this one claim.

## Stack (locked from PRD)
- **Transport / orchestration:** LiveKit Agents (Python agent server + browser client)
- **STT:** Deepgram (word timestamps, verbatim/fillers)
- **Pronunciation "how":** Azure Speech Pronunciation Assessment (per-word/phoneme accuracy, fluency, prosody)
- **Coaching brain:** LLM (pick errors, phrase feedback)
- **TTS:** Rime `coda` primary, `mistv3` low-latency fallback; `speed_alpha` for slow mode
- **Client:** Web (React/Next), WebRTC via LiveKit
- **Language:** en-US only

---

## Phase 0 — Foundation & Preflight (Day 1, first half)
Goal: skeleton + credentials proven before any feature code.
- Repo scaffold: `/agent` (Python LiveKit agent), `/web` (client), `/docs`, `/fixtures`, `/scripts`
- `.env.example` with placeholders only (Rime, Deepgram, Azure, LiveKit, LLM keys) — no secrets committed ever
- LiveKit project + local dev token flow
- **Rime preflight:** confirm exact model ID / voice / language / endpoint / audio format work against the live catalog. This is a submission gate — do it first.
- CI-lite: lint + typecheck both packages

Exit: `.env.example` complete, Rime preflight passes, empty rooms connect.

## Phase 1 — Rime Voice Loop "Hello World" (Day 1, second half)
Goal: end-to-end audio path proven. Highest-risk integration first.
- LiveKit agent joins room, browser captures mic, streams audio
- Agent speaks a fixed line via Rime, user hears it in browser
- Verify streamed PCM/L16 playback, measure first-byte latency raw
- **Lock the acceptance test** (write it into the RIME_EVIDENCE.md draft now, not later)

Exit: click → Rime voice plays in browser, latency logged.

## Phase 2 — ASR: What Was Said (Day 2)
Goal: transcript + word timestamps flowing.
- Wire Deepgram in agent, verbatim mode
- Stream partial + final transcripts to client
- Word-level timestamps captured (needed for pace + filler timing)
- Client: live transcript display
- Derive **WPM (pace)** from timestamps
- Derive **filler count** ("um/uh/like") from verbatim transcript + timestamp gaps

Exit: speak → see transcript, WPM, filler count update live.

## Phase 3 — Pronunciation: How It Was Said (Day 3)
Goal: the "how" signal — the product's real differentiator.
- Integrate Azure Pronunciation Assessment (streaming mode)
- Reading mode: fixed target sentence as reference text
- Per-word accuracy + phoneme scores flowing to agent
- Client: per-word score display beside transcript ("truth beside estimate")
- Flag words below threshold

Exit: mispronounced target word visibly flagged with score.

## Phase 4 — Coaching Logic + Corrective Rime (Day 4)
Goal: the teaching moment. Close the loop on the core claim.
- LLM/rules layer: given flagged words, decide what to correct + how to phrase
- Generate Rime correction: **normal speed**, then **slowed word-by-word** via `speed_alpha` / `inline_speed_alpha`
- Per-flagged-word "hear correct model" button (normal + slow)
- Keep correction on the critical path short; run scoring async so latency stays ≤1s
- Re-attempt loop: re-speak word → score updates in real time

Exit: mispronounce → hear Rime correction (normal + slow) within ~1s. **Core claim demonstrable.**

## Phase 5 — Interruption / Barge-in (Day 5, first half)
Goal: the hard-voice stress case (headline: pronunciation; supporting: interruption).
- App stays full-duplex: mic keeps recording while Rime speaks
- User barges in ("skip"/"next") → queued Rime audio stops ≤300ms
- Fence stale corrections: obsolete model/tool results cannot re-enter the conversation
- App state stays consistent with what the user actually heard
- Lean on LiveKit turn detection + speech-handle interruption

Exit: barge-in stops audio promptly, no stale correction leaks, state consistent.

## Phase 6 — Polish + Measure (Day 5 second half – Day 6)
Goal: demo-ready UI + real numbers.
- "Preset already running": open with a sample sentence + pre-scored attempt (no blank canvas)
- Truth-beside-estimate layout, slow-mode toggle, re-speak control
- **Measure everything, don't claim:**
  - detection→correction latency (≤1s target)
  - flag accuracy (≥8/10 deliberate mispronunciations)
  - interruption stop time (≤300ms)
- Label cached vs uncached runs separately
- Record fixtures: ≥2 text/prompt variants, save clips, note which wording/punctuation changed delivery (required evidence discipline)

Exit: metrics table filled with measured values, fixtures saved.

## Phase 7 — Submission Package (Day 7)
Goal: pass every eligibility gate.
- **Demo video (4–5 min):** target user + problem, normal flow, hard voice problem, one deliberate stress/failure case, measured result, confirm Rime is the active provider
- **README.md:** setup, architecture, third-party services, known limitations, failure behavior, exact Rime model ID / speaker / language / endpoint / audio format / transport
- **RIME_EVIDENCE.md:** claim, acceptance test, procedure, result, limitations, repeatable command/script/fixture
- Config hygiene: `.env.example` placeholders, no secrets anywhere, pass organizer Rime preflight
- Public repo, working demo link (no sign-in) or recording

Exit: all deliverables checked, preflight green.

---

## Critical path (risk-ordered, not date-ordered)
Rime loop (P1) → Pronunciation signal (P3) → Coaching + corrective Rime (P4) are the make-or-break spine. P2 feeds P3/P4. P5 is the headline stress demo. Build the P1→P3→P4 skeleton thin and early; if a piece fails, you know by Day 3, not Day 6.

## Eligibility kill-switches (avoid)
- Rime only for welcome/incidental speech → disqualified. Every correction must be Rime.
- No working product path → disqualified. Keep the loop runnable at every phase.
- Exposed secret → disqualified. Server-side keys only.
- Model/voice/language fails preflight uncorrected → disqualified. That is why Phase 0 does preflight first.

## Open questions (from PRD §15 — decide before Phase 3)
1. Reading mode only, or add free-speak if time? → recommend **reading-mode only** for v1 (cleanest scoring).
2. Which Rime voice for warm coach persona? → pick from live catalog during Phase 1.
3. Visual phoneme comparison, or audio-first? → recommend **audio-first** (honest, faster, matches "the lesson is the sound").
