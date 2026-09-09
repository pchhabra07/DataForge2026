# Fixtures Directory

This directory holds recorded audio fixtures for evidence discipline and testing.

Expected files:
- `rime_preflight.mp3` — normal greeting from preflight
- `rime_preflight_slow.mp3` — slowed greeting with timeScaleFactor 1.5
- `variant_1.json` + `variant_1_normal.mp3` + `variant_1_slow.mp3` — period variant
- `variant_2.json` + `variant_2_normal.mp3` + `variant_2_slow.mp3` — exclamation variant
- `latency_results.json` — output of measure_latency.py (regenerate, do not hand edit)

Generate with:
- `python scripts/rime_preflight.py` — preflight audio samples
- `cd agent && python ../scripts/measure_latency.py` — latency table (needs venv)

Notes:
- Variant mp3s are missing until Rime clips are generated. JSON holds null latency until measured.
- `latency_results.json` with 6 of 6 http session errors is invalid. Rerun after http_context fix.
- `fixtures/tmp/` holds local scratch and is gitignored.
