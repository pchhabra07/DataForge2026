# PRD: EchoCoach — A Real-Time Speaking Coach That Hears *How* You Spoke

**Hackathon:** DataForge 2026 — Rime Hackathon Challenge
**Version:** 1.0
**Status:** Draft
**Timeline:** 7 days

---

## 1. One-Sentence Summary

EchoCoach is a real-time speaking coach that listens while you speak, detects *how* you spoke (pronunciation, filler words, pace, fluency) — not just *what* you said — and immediately models the correct version back to you in a natural human voice using Rime TTS.

---

## 2. The Core Claim (Acceptance Test)

> **When a user mispronounces a target word or overuses filler words while speaking, EchoCoach detects it within ~1 second and speaks back the correct pronunciation using Rime — first at normal speed, then slowed down word-by-word — so the user can immediately repeat and match it.**

This claim is falsifiable and reproducible: if the coach cannot detect a deliberately mispronounced word and respond with corrective Rime audio, the product fails its own test.

---

## 3. Problem & Why Voice Is Essential

### The problem
People who want to improve their spoken English (interview prep, non-native speakers, public speakers) get feedback that is:
- **Delayed** — you record, then get a report later, breaking the practice loop.
- **Text-only** — a score of "72/100" does not teach you *how* the word should actually sound.
- **Silent about delivery** — most tools grade grammar/content, not pronunciation, pace, or fillers.

### Why Rime (voice) is non-negotiable here
Pronunciation cannot be taught with text. The lesson *is* the sound. EchoCoach's core value is hearing a correct spoken model right after your mistake. Remove the spoken output and the product collapses into just another scorecard — which directly satisfies the hackathon's "removing speech makes the product materially worse" test.

**Rime's role:** primary spoken output. It voices every correction, models target words, and delivers slowed-down word-by-word coaching.

---

## 4. Target User

**Primary:** Non-native English speakers preparing for interviews, presentations, or exams (e.g., IELTS/TOEFL practice, campus placements).

**Secondary:** Anyone practicing public speaking who wants to reduce filler words ("um", "uh", "like") and improve pace.

**Prerequisites for the learner:** A microphone, a browser, and a short passage or free-speaking prompt. No account or install.

---

## 5. Learning / Product Objectives

A user session should let the learner:
1. Speak a target sentence or free-speak on a prompt.
2. See **what** they said (transcript) beside **how** they said it (per-word pronunciation score, fillers, pace).
3. **Hear** the correct pronunciation of any flagged word via Rime, at normal and slowed speed.
4. Compare their attempt against the Rime "ground-truth" model.
5. Re-attempt and watch the score change in real time.
6. Interrupt the coach mid-correction and redirect without breaking state.

---

## 6. The Hard Voice Problem (Judging Focus)

EchoCoach targets **two** of the hackathon's difficult voice problems, with one as the headline:

### Headline: Pronunciation & Controlled Delivery
- Model target words, names, and numbers correctly and consistently.
- Deliver **slowed-down**, word-by-word audio using Rime's speed control.
- Render at least two text/prompt variants, save the clips, and show which wording/punctuation changed the delivery (required evidence discipline).

### Supporting: Interruption & Recovery (barge-in)
- While the coach is speaking a correction, the user can cut in ("skip", "next word").
- Queued Rime audio stops promptly; stale corrections do not re-enter the conversation; app state stays consistent with what the user actually heard.

> Design note: full-duplex is a property of the whole app, not the TTS. The app keeps accepting mic audio while Rime is speaking.

---

## 7. System Architecture

```
                    ┌──────────────────────────────────────────┐
   User speaks →    │  Browser client (mic capture, UI, audio)  │
                    └───────────────┬──────────────────────────┘
                                    │  audio (WebRTC / stream)
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │       LiveKit Agent (server-side)         │
                    │  - VAD + turn detection                   │
                    │  - orchestration & interruption handling  │
                    └───┬───────────────┬───────────────┬──────┘
                        │               │               │
            ┌───────────▼──┐   ┌────────▼────────┐   ┌──▼───────────────┐
            │  ASR (STT)   │   │ Pronunciation    │   │ Coaching Logic   │
            │  Deepgram/   │   │ Assessment       │   │ (LLM + rules):   │
            │  OpenAI/     │   │ Azure Speech     │   │ decide what to   │
            │  Whisper     │   │ (accuracy,       │   │ correct & how    │
            │  → words +   │   │ fluency, prosody,│   │                  │
            │  timestamps  │   │ phoneme scores)  │   │                  │
            └──────┬───────┘   └────────┬─────────┘   └──────┬───────────┘
                   │                    │                     │
                   └──── "what" ────────┴──── "how" ──────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │   RIME TTS (primary spoken output)        │
                    │   - normal-speed correction               │
                    │   - slowed word-by-word (speed_alpha)     │
                    └──────────────────┬───────────────────────┘
                                       │  streamed audio
                                       ▼
                              Back to browser → user hears it
```

### Why this split
- **ASR** answers *what* was said (words + word-level timestamps).
- **Pronunciation assessment** answers *how* it was said (per-phoneme accuracy, fluency, prosody). This is the "hear how you spoke" core, and it is a separate signal from the transcript.
- **Filler / pace** is derived from ASR timestamps + a verbatim-capable model.
- **Rime** is the only spoken output and carries the teaching moment.

---

## 8. Technology Choices

| Layer | Choice | Why |
|-------|--------|-----|
| Transport / orchestration | **LiveKit Agents** | Official Rime integration; handles turn-taking, streaming, interruption. Recommended by the PS. |
| Speech-to-text | **Deepgram** or **OpenAI** (verbatim mode) | Word-level timestamps needed for pace + filler timing. |
| Pronunciation "how" signal | **Azure Speech Pronunciation Assessment** | Returns per-word + per-phoneme accuracy, fluency, completeness, and prosody scores. Supports streaming mode. Fits the "how you spoke" requirement directly. |
| Filler detection | ASR verbatim transcript + timestamp gaps (optional: CrisperWhisper for verbatim `[um]`/`[uh]`) | Localizes and classifies fillers reliably. |
| Coaching logic | **LLM** (any) | Decides which errors to correct and phrases the spoken feedback. |
| **Spoken output** | **Rime — Coda** (quality) with **Mist v3** fallback (lowest latency) | Rime is the judged primary voice. Coda for natural coaching; Mist v3 when speed is critical. |
| Slowed delivery | Rime `speed_alpha` / `inline_speed_alpha` | Word-by-word slow modeling for pronunciation practice. |

### Rime configuration (to record in README)
- **Model:** `rime/coda` (primary), `rime/mistv3` (low-latency fallback)
- **Voice:** chosen from Rime's live catalog at submission time
- **Language:** `en`
- **Endpoint:** nearest regional endpoint
- **Audio format:** streamed PCM/L16 for web; 8kHz if telephony demo added
- **Transport:** LiveKit (WebRTC)
- **Speed control:** `speed_alpha > 1.0` for slowed word-by-word coaching

---

## 9. Key Interactions (the "substrate")

1. **Preset already running.** Open with a sample sentence and a pre-scored attempt visible — no blank canvas.
2. **Truth beside estimate.** User's per-word pronunciation score sits next to the Rime "correct model" audio button. The gap is the lesson.
3. **Manipulate a real variable.** User changes the target sentence, or toggles slow-mode, or re-speaks a word, and sees/hears the consequence in under a second.
4. **Interruption demo.** User barges in during a correction; audio stops promptly and state stays consistent.

---

## 10. Scope

### In scope (v1 for hackathon)
- One language: English (`en-US`).
- Reading mode (scripted target sentence) as the primary flow — cleanest for pronunciation scoring.
- Per-word pronunciation flagging + Rime spoken correction (normal + slow).
- Filler-word count and pace (WPM) readout.
- Interruption/barge-in on corrections.

### Out of scope (state explicitly — "no hidden limits")
- Multi-language coaching (English only for v1).
- Accent selection / dialect grading.
- Long-form essay grammar rewriting (light grammar hints only).
- Telephony transport (web demo only, unless time allows).
- Offline / on-device inference.

---

## 11. Success Metrics

| Metric | Target |
|--------|--------|
| Detection-to-correction latency | ≤ 1 s from end of user's flagged word to first Rime audio byte |
| Pronunciation flag accuracy | Correctly flags ≥ 8/10 deliberately mispronounced target words |
| Interruption stop time | Queued Rime audio stops ≤ 300 ms after barge-in |
| Slow-mode intelligibility | Word-by-word slowed clip remains natural and intelligible (human check) |
| End-to-end perceived response | Feels conversational in the recorded demo |

All numbers must be measured, not claimed. Cached vs uncached runs labeled separately.

---

## 12. Deliverables (Submission Package)

- [ ] **Demo video** (4–5 min): target user + problem, normal flow, the hard voice problem, one deliberate stress/failure case (interruption or a tricky word), the measured result, and confirmation Rime is the active provider.
- [ ] **Public source repo** judges can inspect.
- [ ] **Working demo link** (no sign-in) or recording; demonstrated behavior must exist in the repo.
- [ ] **README.md** — setup, architecture, third-party services, known limitations, failure behavior, and exact Rime model ID / speaker / language / endpoint / audio format / transport.
- [ ] **RIME_EVIDENCE.md** — the hard voice claim, acceptance test, procedure, result, limitations, and a repeatable command/script/fixture.
- [ ] **Config hygiene** — `.env.example` with placeholders only; pass the organizer Rime preflight; no secrets committed anywhere.

---

## 13. 7-Day Plan

| Day | Goal |
|-----|------|
| **1** | Repo + LiveKit + Rime "hello world" voice loop working. Lock acceptance test. |
| **2** | Wire ASR (words + timestamps). Basic transcript display. |
| **3** | Integrate Azure Pronunciation Assessment. Get per-word scores flowing. |
| **4** | Coaching logic: pick errors → generate Rime correction (normal + slow speed). |
| **5** | Interruption/barge-in handling. Filler + pace readout. |
| **6** | Polish UI (preset running, truth-beside-estimate). Record fixtures, measure latency. |
| **7** | Demo video, README, RIME_EVIDENCE.md, config hygiene, preflight check. |

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Real-time pronunciation scoring adds latency | Use Azure streaming mode; run scoring async; keep Rime correction on the critical path short. |
| Rime is only used incidentally (disqualifier) | Every correction is spoken by Rime; it is the primary output, never a welcome message. |
| Interruption logic is hard | Lean on LiveKit's built-in turn detection + speech-handle interruption; fence stale results. |
| Overclaiming numbers | Measure everything; label cached vs uncached; disclose limits in RIME_EVIDENCE.md. |
| Scope creep (multi-language, telephony) | Ship English reading-mode first; add extras only if Day 6 allows. |

---

## 15. Open Questions

- Reading mode only, or add a free-speaking mode if time allows?
- Which Rime voice best fits a warm, encouraging coach persona?
- Add a visual phoneme comparison, or keep it audio-first for honesty and speed?

---

*This PRD is the single source of truth for EchoCoach. Every feature, chart, and control must serve the one claim in Section 2.*
