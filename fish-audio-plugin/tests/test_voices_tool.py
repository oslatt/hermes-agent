"""``fish_voices``: search, alias, get, clone (consent-gated), design, delete (confirm-gated), credit."""

import json

from model_tools import handle_function_call


def voices(**args):
    return json.loads(handle_function_call("fish_voices", args))


def test_search_filters_by_tag_and_alias_makes_the_voice_speakable(fish):
    found = voices(action="search", tags=["character"])
    assert found["success"] and [v["title"] for v in found["voices"]] == ["Gravel Captain"]
    vid = found["voices"][0]["id"]
    saved = voices(action="alias", voice_id=vid, alias="Captain")
    assert saved["aliases"]["captain"] == vid
    spoken = json.loads(handle_function_call("fish_speak", {"text": "Ahoy.", "voice": "captain"}))
    assert spoken["success"] and fish.server.tts_requests()[-1].body["reference_id"] == vid


def test_get_accepts_an_alias(fish):
    vid = voices(action="search", query="narrator")["voices"][0]["id"]
    voices(action="alias", voice_id=vid, alias="narr")
    got = voices(action="get", voice_id="narr")
    assert got["voice"]["id"] == vid and got["voice"]["samples"]


def test_clone_refuses_without_consent_and_uploads_every_sample_with_it(fish, tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(b"RIFF" + bytes(4000))
    refused = voices(action="clone", title="Me", audio_paths=[str(clip)])
    assert not refused["success"] and "consent" in refused["error"]
    assert not [r for r in fish.server.requests if r.path == "/model" and r.method == "POST"]
    made = voices(action="clone", title="Me", audio_paths=[str(clip)], transcripts=["Hello, this is me."],
                  consent=True)
    assert made["success"], made
    upload = [r for r in fish.server.requests if r.path == "/model" and r.method == "POST"][-1].body
    assert upload["fields"]["visibility"] == ["private"] and upload["fields"]["texts"] == ["Hello, this is me."]
    assert [name for name, _ in upload["files"]["voices"]] == ["me.wav"]
    assert voices(action="mine")["voices"][0]["id"] == made["voice"]["id"]


def test_design_writes_playable_candidates(fish):
    out = voices(action="design", instruction="Gruff old sea captain, slow and amused", preview_text="Ahoy!", n=3)
    assert out["success"] and len(out["candidates"]) == 3
    req = [r for r in fish.server.requests if r.path == "/v1/voice-design"][-1]
    assert req.model == "voice-design-1" and req.body["reference_text"] == "Ahoy!"
    for c in out["candidates"]:
        assert open(c["file_path"], "rb").read(4) == b"RIFF" and c["media_tag"] == f"MEDIA:{c['file_path']}"


def test_delete_needs_confirmation(fish, tmp_path):
    vid = fish.server.add_voice("Temp", ["tmp"], owner="self")
    assert not voices(action="delete", voice_id=vid)["success"]
    assert vid in fish.server.voices
    assert voices(action="delete", voice_id=vid, confirm=True)["success"]
    assert vid not in fish.server.voices


def test_credit_and_unknown_action(fish):
    assert voices(action="credit")["credit"] == "12.50"
    bad = voices(action="explode")
    assert not bad["success"] and "search" in bad["hint"]
