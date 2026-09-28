"""Cue compiler contracts: the agent writes one syntax; each model receives only what it can perform."""

import pytest


@pytest.fixture
def m(plugin):
    return plugin.fish_audio.markup


@pytest.fixture
def models(plugin):
    return plugin.fish_audio.models.MODELS


def test_s2_keeps_free_form_cues_and_upgrades_known_parenthesis_tags(m, models):
    text, warnings = m.compile_for_model("(sad) I miss you. [whispers sweetly] Come home (soon).", models["s2.1-pro"])
    assert text == "[sad] I miss you. [whispers sweetly] Come home (soon)."
    assert warnings == []


def test_s1_never_receives_a_bracket_it_would_read_aloud(m, models):
    text, warnings = m.compile_for_model(
        "What a [happy] wonderful day. [laughing nervously] Ha. [slightly sad, whispering] Bye.", models["s1"])
    assert "[" not in text and "]" not in text
    assert text.startswith("(happy) What a wonderful day.")  # emotion hoisted to sentence start
    assert "(sad)" in text and "(whispering)" in text
    assert any("laughing nervously" in w for w in warnings)


@pytest.mark.parametrize("cue", ["whisper", "laugh", "sigh", "pause", "long pause", "furious"])
def test_every_s1_alias_maps_into_the_documented_tag_set(m, models, cue):
    text, _ = m.compile_for_model(f"[{cue}] Now.", models["s1"])
    tags = {t for t in m._PAREN_TAG_RE.findall(text)}
    assert tags and tags <= m.S1_TAGS


def test_dialogue_numbers_speakers_by_first_appearance(m):
    text, names = m.build_dialogue([{"speaker": "Ana", "text": "Hi."}, {"speaker": "Bo", "text": "Yo."},
                                    {"speaker": "Ana", "text": "[laughing] Ha!"}])
    assert names == ["Ana", "Bo"]
    assert m.speaker_indices(text) == [0, 1]
    assert text.endswith("<|speaker:0|>[laughing] Ha!")


def test_split_reopens_the_active_speaker_and_keeps_every_word(m):
    script = "<|speaker:0|>" + "Alpha beta gamma. " * 12 + "<|speaker:1|>" + "Delta epsilon. " * 12
    chunks = m.split_for_requests(script, 90)
    assert len(chunks) > 2
    assert all(len(c) <= 90 or m.SPEAKER_TOKEN_RE.match(c) for c in chunks)
    assert all(m.SPEAKER_TOKEN_RE.match(c) for c in chunks)
    assert m.spoken_words(" ".join(chunks)) == m.spoken_words(script)


def test_direction_becomes_a_leading_cue_after_the_first_speaker_token(m, models):
    text, _ = m.apply_direction("<|speaker:0|>Hello.", "warm, amused", models["s2-pro"])
    assert text == "<|speaker:0|>[warm, amused] Hello."


def test_tokens_mangled_by_older_hermes_cleaners_are_repaired(m):
    assert m.repair_control_tokens("<; speaker:1; >Hi <; phonemestart; >R EH1 D<; phonemeend; >") == \
        "<|speaker:1|>Hi <|phoneme_start|>R EH1 D<|phoneme_end|>"


def test_lint_flags_overloaded_sentences_and_unbalanced_phonemes(m, models):
    warnings = m.lint("[a][b][c][d] Too much. <|phoneme_start|>R EH1 D", models["s2.1-pro"])
    assert any("at most 3" in w for w in warnings)
    assert any("Unbalanced phoneme" in w for w in warnings)
