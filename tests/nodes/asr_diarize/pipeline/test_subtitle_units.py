import pytest

pytest.importorskip("spacy", reason="Use uv run --extra b-asr pytest")
pytest.importorskip("en_core_web_sm", reason="Use uv run --extra b-asr pytest")

import copy
import json

import spacy

from nodes.asr_diarize.node import ASROptions
from nodes.asr_diarize.pipeline.recognition import review_table
from nodes.asr_diarize.pipeline.sentence_rules import sentences_from_words, validate_sentence_table
from nodes.asr_diarize.pipeline.subtitle_units import SubtitlePolicy


@pytest.fixture(scope="module")
def nlp():
    return spacy.load("en_core_web_sm", disable=["ner"])


def aligned(text, step=.4):
    return [{"word": word, "start": i * step, "end": i * step + step * .9}
            for i, word in enumerate(text.split())]


def test_screen_overflow_example_is_split_without_losing_words(nlp):
    text = ("We made this because every day many people wanted to take a nap, "
            "but there was always noise or no comfortable way to lie down.")
    words = aligned(text)
    before = copy.deepcopy(words)
    rows, report = sentences_from_words(words, nlp)
    assert len(rows) > 1
    assert " ".join(r["en"] for r in rows) == text
    assert all(len(r["en"]) <= 42 for r in rows)
    assert all(0 < r["end_ms"] - r["start_ms"] <= 4000 for r in rows)
    assert all(len(r["en"]) * 1000 / (r["end_ms"] - r["start_ms"]) <= 20 for r in rows)
    assert all(a["end_ms"] <= b["start_ms"] for a, b in zip(rows, rows[1:]))
    assert words == before
    assert report["subtitle_layout"]["source_ranges_split"] > 0
    table = {"schema_version": "b-sentences-2", "duration_ms": 20000,
             "sentences": rows, "review": report}
    assert validate_sentence_table(table) == []
    assert "words" not in table and "first" not in json.dumps(report)


def test_spaces_and_punctuation_count_towards_limit(nlp):
    rows, _ = sentences_from_words(aligned("A, B."), nlp,
                                  subtitle_options={"max_chars": 4, "target_min_chars": 3})
    assert [r["en"] for r in rows] == ["A,", "B."]


def test_short_complete_sentence_is_not_padded_or_fragmented(nlp):
    text = "We keep each subtitle short and clear."
    rows, _ = sentences_from_words(aligned(text), nlp)
    assert len(rows) == 1 and rows[0]["en"] == text


def test_clause_boundary_is_preferred_and_names_stay_together(nlp):
    rows, _ = sentences_from_words(aligned(
        "We watch the video carefully, and then we check every subtitle."), nlp)
    assert rows[0]["en"].endswith(",")
    assert rows[1]["en"].startswith("and")
    rows, _ = sentences_from_words(aligned(
        "We asked New York researchers to check all of the subtitle boundaries carefully."), nlp)
    assert any("New York" in row["en"] for row in rows)


def test_fast_speech_is_flagged_without_inventing_display_time(nlp):
    words = [{"word": "Yes.", "start": .05, "end": .20}]
    rows, _ = sentences_from_words(words, nlp)
    assert (rows[0]["start_ms"], rows[0]["end_ms"]) == (50, 200)
    assert "subtitle_reading_speed_high" in rows[0]["review_issues"]
    assert "video_start_may_be_partial" not in rows[0]["review_issues"]


def test_possessive_and_negation_are_not_stranded_at_cut(nlp):
    rows, _ = sentences_from_words(aligned("And this is presumably your first time in Paris.", .25), nlp)
    assert all(not r["en"].endswith("your") for r in rows)
    rows, _ = sentences_from_words(aligned(
        "You must not change the settings, because they affect everyone's privacy."), nlp)
    assert any("must not" in r["en"] for r in rows)


def test_long_single_word_is_preserved_and_explicitly_flagged(nlp):
    word = "Pneumonoultramicroscopicsilicovolcanoconiosis"
    assert len(word) > 42
    rows, _ = sentences_from_words(aligned(word + " works."), nlp)
    assert word in " ".join(r["en"] for r in rows)
    assert any("subtitle_single_token_exceeds_max_chars" in r["review_issues"] for r in rows)


def test_overlapping_alignment_is_not_split_with_fake_times(nlp):
    words = [{"word": "Antidisestablishmentarianism", "start": 0., "end": 1.},
             {"word": "notwithstanding", "start": .5, "end": 1.5},
             {"word": "makes", "start": 2., "end": 2.4},
             {"word": "sense.", "start": 2.5, "end": 2.9}]
    rows, _ = sentences_from_words(words, nlp)
    assert any("subtitle_alignment_overlap_prevents_split" in r["review_issues"] for r in rows)
    assert rows[0]["start_ms"] == 0 and rows[0]["end_ms"] == 1500
    assert rows[1]["start_ms"] == 2000


def test_custom_limits_are_applied_and_survive_independent_review(nlp):
    text = "We watch the video carefully and check every subtitle."
    options = {"max_chars": 60, "max_duration_sec": 10}
    rows, report = sentences_from_words(aligned(text), nlp, subtitle_options=options)
    assert len(rows) == 1
    tight, report = sentences_from_words(aligned(text), nlp,
                                        subtitle_options={"max_chars": 30, "target_min_chars": 24})
    table = {"schema_version": "b-sentences-2", "duration_ms": 10000,
             "sentences": tight, "review": report}
    final = review_table(table)
    assert all(len(r["en"]) <= 30 for r in final["sentences"])
    assert all("possible_unfinished_sentence" not in r["review_issues"] for r in final["sentences"])
    assert final["review"]["subtitle_policy"]["max_chars"] == 30


@pytest.mark.parametrize("options", [{"max_chars": 20}, {"min_duration_sec": 5}, {"max_cps": 0}])
def test_invalid_policy_is_rejected(options):
    with pytest.raises(ValueError):
        SubtitlePolicy(**options)
    with pytest.raises(ValueError):
        ASROptions(subtitle=options)
