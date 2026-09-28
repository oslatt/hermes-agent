"""``fish_speak`` through Hermes's real tool dispatch against the contract-checking fake server."""

import json
from pathlib import Path

import pytest

from model_tools import handle_function_call


def speak(**args):
    return json.loads(handle_function_call("fish_speak", args))


@pytest.fixture
def voices(fish):
    by_title = {v["title"]: vid for vid, v in fish.server.voices.items()}
    fish.configure({"voices": {"narrator": by_title["Warm Narrator"], "captain": by_title["Gravel Captain"],
                               "presenter": by_title["Bright Presenter"]}})
    return by_title


def test_expressive_script_reaches_fish_intact_and_returns_deliverable_audio(fish, voices, tmp_path):
    out = speak(text="[excited] We won! [laughing] Ha, ha! I [emphasis] told you.", voice="narrator",
                output_path=str(tmp_path / "win.mp3"))
    assert out["success"], out
    req = fish.server.tts_requests()[-1]
    assert req.model == "s2.1-pro"
    assert req.body["text"] == "[excited] We won! [laughing] Ha, ha! I [emphasis] told you."
    assert req.body["reference_id"] == voices["Warm Narrator"]
    assert out["media_tag"] == f"MEDIA:{tmp_path / 'win.mp3'}"
    assert (tmp_path / "win.mp3").read_bytes()[:3] == b"ID3"


def test_s1_request_carries_parenthesis_tags_only(fish, voices):
    out = speak(text="[whispering] Come closer. [laughing nervously] Heh.", model="s1")
    assert out["success"], out
    body = fish.server.tts_requests()[-1].body
    assert "[" not in body["text"] and "(whispering)" in body["text"]
    assert out["warnings"]


def test_dialogue_casts_one_voice_per_speaker_in_turn_order(fish, voices):
    out = speak(lines=[{"speaker": "Mara", "text": "[excited] You found it?"},
                       {"speaker": "captain", "text": "[whispering] Keep it down."},
                       {"speaker": "Mara", "text": "[gasping] Oh!"}],
                cast={"Mara": "presenter"})
    assert out["success"], out
    body = fish.server.tts_requests()[-1].body
    assert body["reference_id"] == [voices["Bright Presenter"], voices["Gravel Captain"]]
    assert body["text"].count("<|speaker:0|>") == 2 and body["text"].count("<|speaker:1|>") == 1
    assert out["speakers"] == {"0": "Mara", "1": "captain"}


def test_dialogue_on_s1_switches_to_a_dialogue_model(fish, voices):
    out = speak(lines=[{"speaker": "narrator", "text": "Hi."}, {"speaker": "captain", "text": "Ahoy."}], model="s1")
    assert out["success"], out
    assert fish.server.tts_requests()[-1].model == "s2.1-pro"
    assert any("cannot voice dialogue" in w for w in out["warnings"])


def test_unknown_voice_fails_before_any_request_with_a_way_forward(fish, voices):
    out = speak(text="Hello.", voice="nobody")
    assert not out["success"]
    assert "narrator" in out["error"] and "fish_voices" in out["error"]
    assert fish.server.tts_requests() == []


def test_prosody_sampling_and_pronunciation_controls_are_sent_in_range(fish, voices):
    out = speak(text="Our SQL runs on <|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|>.",
                speed=3.0, volume=-4, temperature=0.9, top_p=0.5, latency="balanced", direction="calm, precise",
                pronunciations={"SQL": "EH1 S K Y UW1 EH1 L"})
    assert out["success"], out
    body = fish.server.tts_requests()[-1].body
    assert body["prosody"] == {"speed": 2.0, "volume": -4.0}
    assert (body["temperature"], body["top_p"], body["latency"]) == (0.9, 0.5, "balanced")
    assert body["text"].startswith("[calm, precise] Our SQL")
    assert "<|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|>" in body["text"]
    assert body["pronunciation_dictionary"] == [
        {"items": [{"key": "SQL", "value": "EH1 S K Y UW1 EH1 L", "case_sensitive": True}]}]


def test_long_script_is_split_and_stitched_into_one_file(fish, voices, tmp_path):
    fish.configure({"max_chars_per_request": 200, "voices": {"narrator": voices["Warm Narrator"]}})
    script = " ".join(f"[calm] Sentence number {i} is here." for i in range(30))
    out = speak(text=script, voice="narrator", format="wav", output_path=str(tmp_path / "long.wav"))
    assert out["success"] and out["requests"] > 1, out
    import wave
    with wave.open(str(tmp_path / "long.wav")) as w:
        assert w.getnframes() * 2 == out["bytes"]
    assert all(r.body["format"] == "pcm" for r in fish.server.tts_requests())


def test_timestamps_are_written_next_to_the_audio(fish, voices, tmp_path):
    out = speak(text="[warm] Hello there friend.", timestamps=True, output_path=str(tmp_path / "t.mp3"))
    assert out["success"], out
    words = json.loads(Path(out["timestamps_path"]).read_text(encoding="utf-8"))
    assert [w["text"] for w in words] == ["Hello", "there", "friend."]
    assert words == sorted(words, key=lambda w: w["start"])


@pytest.mark.parametrize("status,needle", [(401, "FISH_API_KEY"), (402, "credit"), (422, "out of range")])
def test_api_errors_come_back_as_actionable_envelopes(fish, voices, status, needle):
    fish.server.faults.append((status, {"status": status, "message": "nope"}))
    out = speak(text="Hi.")
    assert not out["success"] and needle in (out["error"] + out.get("hint", ""))


def test_rate_limits_and_server_errors_are_retried(fish, voices):
    fish.server.faults += [(429, {"status": 429, "message": "busy"}), (503, {"status": 503, "message": "load"})]
    out = speak(text="Hi.")
    assert out["success"], out
    assert len(fish.server.tts_requests()) == 3


def test_voice_bubble_platforms_get_opus_marked_for_voice_delivery(fish, voices, monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    out = speak(text="[warm] Good night.")
    assert out["success"], out
    assert fish.server.tts_requests()[-1].body["format"] == "opus"
    assert out["file_path"].endswith(".ogg") and out["media_tag"].startswith("[[audio_as_voice]]")


def test_zero_shot_cloning_sends_reference_audio_as_msgpack(fish, voices, tmp_path):
    pytest.importorskip("msgpack")
    clip = tmp_path / "ref.wav"
    clip.write_bytes(b"RIFF" + bytes(3000))
    out = speak(text="[warm] Hello in my own voice.",
                reference_audio=[{"path": str(clip), "transcript": "This is my voice."}])
    assert out["success"], out
    req = fish.server.tts_requests()[-1]
    assert req.content_type == "application/msgpack"
    assert req.body["references"] == [{"audio": clip.read_bytes(), "text": "This is my voice."}]
    assert "reference_id" not in req.body


def test_zero_shot_dialogue_groups_references_per_speaker(fish, voices, tmp_path):
    pytest.importorskip("msgpack")
    clip = tmp_path / "guest.wav"
    clip.write_bytes(b"RIFF" + bytes(3000))
    out = speak(lines=[{"speaker": "narrator", "text": "Welcome."}, {"speaker": "Guest", "text": "Thanks!"}],
                reference_audio=[{"path": str(clip), "transcript": "Guest sample.", "speaker": "Guest"}])
    assert out["success"], out
    body = fish.server.tts_requests()[-1].body
    assert body["reference_id"] == [voices["Warm Narrator"], "speaker-1"]
    assert body["references"] == [[], [{"audio": clip.read_bytes(), "text": "Guest sample."}]]


@pytest.mark.parametrize("target", [".env", "notes.txt"])
def test_reference_audio_never_uploads_secrets_or_non_audio(fish, voices, target):
    path = fish.home / target
    path.write_text("FISH_API_KEY=secret\n")
    out = speak(text="Hi.", reference_audio=[{"path": str(path), "transcript": "x"}])
    assert not out["success"]
    assert fish.server.tts_requests() == []
