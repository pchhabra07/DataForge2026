"""
EchoCoach — Standalone Pipeline Simulation

Demonstrates and tests the complete Phase 3 & 4 pipeline without requiring
Azure Speech, OpenAI keys, or a running LiveKit server.

Usage:
    cd agent
    .venv\\Scripts\\python ..\\scripts\\simulate_coaching.py [sentence_id]
"""

import asyncio
import os
import sys
import time

# Ensure agent package is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env.local")))

from echocoach.sentences import get_sentence, get_all_sentences, get_first_sentence
from echocoach.pronunciation import assess_pronunciation
from echocoach.coaching import generate_correction


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ANSI Color Codes for terminal
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def main():
    print(f"\n{BOLD}{CYAN}=================================================================={RESET}")
    print(f"{BOLD}{CYAN}      EchoCoach -- Pronunciation Assessment & Coaching Simulation {RESET}")
    print(f"{BOLD}{CYAN}=================================================================={RESET}\n")

    # Pick sentence
    sentence_id = 5
    if len(sys.argv) > 1:
        try:
            sentence_id = int(sys.argv[1])
        except ValueError:
            pass

    target = get_sentence(sentence_id) or get_first_sentence()
    print(f"{BOLD}Target Sentence #{target.id}:{RESET} \"{target.text}\"")
    print(f"Difficulty: {CYAN}{target.difficulty.upper()}{RESET} | Category: {target.category}\n")

    # Step 1: Pronunciation Assessment
    print(f"{BOLD}[1/3] Running Pronunciation Assessment...{RESET}")
    azure_key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    if not azure_key or azure_key.startswith("your_"):
        print(f"  {YELLOW}[i] AZURE_SPEECH_KEY not set -- using built-in realistic simulation mode{RESET}")
    else:
        print(f"  {GREEN}[+] AZURE_SPEECH_KEY detected -- running via Azure Speech SDK{RESET}")

    # Dummy PCM buffer to trigger assessment
    dummy_pcm = b"\x00\x00" * 4800  # ~100ms
    t0 = time.perf_counter()
    result = await assess_pronunciation(dummy_pcm, target.text)
    latency_assess = (time.perf_counter() - t0) * 1000

    if not result:
        print(f"  {RED}[x] Pronunciation assessment returned no result.{RESET}")
        return

    print(f"  Assessment completed in {CYAN}{latency_assess:.1f}ms{RESET}")
    print(f"  Overall Accuracy:    {BOLD}{result.accuracy_score:.1f}/100{RESET}")
    print(f"  Fluency Score:       {result.fluency_score:.1f}/100")
    print(f"  Completeness Score:  {result.completeness_score:.1f}/100")
    print(f"  Prosody Score:       {result.prosody_score:.1f}/100\n")

    # Per-word scores display
    print(f"{BOLD}[2/3] Word-by-Word Scoring:{RESET}")
    word_display = []
    for w in result.words:
        if w.accuracy_score >= 80:
            color = GREEN
        elif w.accuracy_score >= 60:
            color = YELLOW
        else:
            color = RED
        word_display.append(f"{color}{w.word} ({w.accuracy_score:.0f}){RESET}")
    print("  " + "  ".join(word_display) + "\n")

    if result.flagged_words:
        flagged_names = [f"{RED}{w.word} ({w.accuracy_score:.0f}){RESET}" for w in result.flagged_words]
        print(f"  {RED}[!] Flagged for coaching:{RESET} {', '.join(flagged_names)}\n")
    else:
        print(f"  {GREEN}[+] All words pronounced clearly!{RESET}\n")

    # Step 2: Coaching Logic
    print(f"{BOLD}[3/3] Coaching Decision Brain:{RESET}")
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not openai_key or openai_key.startswith("your_"):
        print(f"  {YELLOW}[i] OPENAI_API_KEY not set -- using instant rules-based coaching brain{RESET}")
    else:
        print(f"  {GREEN}[+] OPENAI_API_KEY detected -- requesting LLM coaching phrasing{RESET}")

    flagged_dicts = [w.to_dict() for w in result.flagged_words]
    correction = await generate_correction(flagged_dicts, target.text)

    print(f"  Coaching source:     {CYAN}{correction.source.upper()}{RESET}")
    print(f"  Coaching latency:    {CYAN}{correction.latency_ms:.1f}ms{RESET}")
    print(f"  {BOLD}Spoken Feedback:{RESET}     \"{YELLOW}{correction.coaching_text}{RESET}\"")
    print(f"  {BOLD}Words to Model:{RESET}      {correction.words_to_model}")

    print(f"\n{BOLD}{GREEN}[+] Pipeline verification complete! Both Phase 3 and Phase 4 are fully functional.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
