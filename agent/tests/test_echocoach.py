"""
Unit tests for EchoCoach core modules:
- sentences
- pronunciation data structures and audio utilities
- coaching rules and plan generation
"""

from echocoach.coaching import (
    _generate_rules_correction,
)
from echocoach.pronunciation import (
    PronunciationResult,
    WordScore,
    resample_pcm,
)
from echocoach.sentences import (
    SENTENCES,
    get_all_sentences,
    get_first_sentence,
    get_next_sentence,
    get_sentence,
)


def test_sentences_bank():
    assert len(SENTENCES) >= 10
    first = get_first_sentence()
    assert first.id == 1
    assert first.difficulty == "easy"

    # Specific ID lookup
    s3 = get_sentence(3)
    assert s3 is not None
    assert s3.id == 3

    assert get_sentence(999) is None

    # Next sentence wrapping
    next_s = get_next_sentence(SENTENCES[-1].id)
    assert next_s.id == SENTENCES[0].id

    # List all
    all_s = get_all_sentences()
    assert len(all_s) == len(SENTENCES)


def test_word_score_flagging():
    good_word = WordScore(word="hello", accuracy_score=85.0, error_type="None")
    assert not good_word.is_flagged

    poor_word = WordScore(word="world", accuracy_score=50.0, error_type="None")
    assert poor_word.is_flagged

    mispronounced_word = WordScore(word="test", accuracy_score=90.0, error_type="Mispronunciation")
    assert mispronounced_word.is_flagged

    d = poor_word.to_dict()
    assert d["word"] == "world"
    assert d["accuracyScore"] == 50.0
    assert d["isFlagged"] is True


def test_pronunciation_result():
    words = [
        WordScore(word="The", accuracy_score=95.0, error_type="None"),
        WordScore(word="quick", accuracy_score=55.0, error_type="None"),
        WordScore(word="fox", accuracy_score=90.0, error_type="None"),
    ]
    res = PronunciationResult(
        recognized_text="The quick fox",
        accuracy_score=80.0,
        fluency_score=85.0,
        completeness_score=100.0,
        prosody_score=82.0,
        words=words,
    )
    assert res.has_issues is True
    assert len(res.flagged_words) == 1
    assert res.flagged_words[0].word == "quick"

    d = res.to_dict()
    assert d["recognizedText"] == "The quick fox"
    assert len(d["flaggedWords"]) == 1
    assert d["hasIssues"] is True


def test_resample_pcm():
    # Empty bytes test
    assert resample_pcm(b"", 48000, 16000) == b""

    # Same sample rate returns identical bytes
    raw = b"\x00\x00\x10\x00\x20\x00"
    assert resample_pcm(raw, 16000, 16000) == raw

    # Resampling down from 48k to 16k (3:1 ratio)
    # 6 samples = 12 bytes at 48k -> 2 samples = 4 bytes at 16k
    six_samples = b"\x00\x00" * 6
    resampled = resample_pcm(six_samples, 48000, 16000)
    assert len(resampled) == 4


def test_rules_coaching_generation():
    # Zero flagged words
    plan_clean = _generate_rules_correction([], "The quick brown fox.")
    assert "Great job" in plan_clean.coaching_text
    assert len(plan_clean.words_to_model) == 0
    assert plan_clean.source == "rules"

    # Single flagged word
    plan_single = _generate_rules_correction(
        [{"word": "particularly"}], "This is particularly good."
    )
    assert "particularly" in plan_single.coaching_text
    assert plan_single.words_to_model == ["particularly"]

    # Two flagged words
    plan_two = _generate_rules_correction(
        [{"word": "first"}, {"word": "second"}], "First and second."
    )
    assert "first" in plan_two.coaching_text
    assert "second" in plan_two.coaching_text
    assert plan_two.words_to_model == ["first", "second"]

    # Three flagged words
    plan_three = _generate_rules_correction(
        [{"word": "alpha"}, {"word": "beta"}, {"word": "gamma"}, {"word": "delta"}],
        "Alpha beta gamma delta.",
    )
    # Top 3 only
    assert len(plan_three.words_to_model) == 3
    assert "alpha" in plan_three.words_to_model
    assert "beta" in plan_three.words_to_model
    assert "gamma" in plan_three.words_to_model


def test_mock_pronunciation_assessment():
    from echocoach.pronunciation import _mock_pronunciation_assessment

    sentence = "Communication skills are particularly important for professional development."
    result = _mock_pronunciation_assessment(sentence)

    assert result.has_issues is True
    assert len(result.flagged_words) == 1
    assert result.flagged_words[0].word == "Communication"
    assert result.flagged_words[0].accuracy_score == 52.0
    assert result.accuracy_score > 60
    assert result.fluency_score == 84.0
    assert result.words[1].accuracy_score >= 80


def test_phonetic_similarity():
    from echocoach.pronunciation import word_phonetic_similarity

    # Exact matches
    assert word_phonetic_similarity("hello", "hello") == 1.0
    assert word_phonetic_similarity("cat", "CAT") == 1.0

    # Homophones / near homophones
    homophone_score = word_phonetic_similarity("weather", "whether")
    assert homophone_score >= 0.9

    # Distant words
    diff_score = word_phonetic_similarity("quick", "elephant")
    assert diff_score < 0.4


def test_align_reference_and_recognized():
    from echocoach.pronunciation import align_reference_and_recognized

    ref = ["the", "quick", "brown", "fox"]
    # Recognized has a filler insertion and a mispronunciation
    hyp = [
        {"word": "the", "confidence": 0.98},
        {"word": "um", "confidence": 0.40},
        {"word": "quik", "confidence": 0.90},
        {"word": "brown", "confidence": 0.95},
        # fox omitted
    ]

    aligned = align_reference_and_recognized(ref, hyp)
    assert len(aligned) == 4
    # "the" -> "the"
    assert aligned[0][0] == "the"
    assert aligned[0][1]["word"] == "the"
    # "quick" -> "quik"
    assert aligned[1][0] == "quick"
    assert aligned[1][1]["word"] == "quik"
    # "brown" -> "brown"
    assert aligned[2][0] == "brown"
    assert aligned[2][1]["word"] == "brown"
    # "fox" -> None (omitted)
    assert aligned[3][0] == "fox"
    assert aligned[3][1] is None


def test_warmup_free_assessor(monkeypatch):
    import asyncio

    from echocoach.pronunciation import get_download_progress, warmup_free_assessor

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-fake-key")
    notifications = []

    def status_callback(s):
        notifications.append(s)

    asyncio.run(warmup_free_assessor(status_callback))
    assert "ready" in notifications

    prog = get_download_progress()
    assert prog["phase"] == "ready"
    assert prog["downloaded"] == 1


