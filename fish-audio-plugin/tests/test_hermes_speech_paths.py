"""Fish Audio behind Hermes's own speech surfaces: ``text_to_speech``, inbound transcription, streaming
voice mode, the ``hermes tools`` picker, the system prompt and skills."""

import json

from model_tools import handle_function_call


def test_text_to_speech_tool_routes_to_fish_with_cues_and_direction(fish, tmp_path):
    out = json.loads(handle_function_call("text_to_speech", {
        "text": "**Great news!** [excited] The build passed.", "instructions": "proud, upbeat",
        "output_path": str(tmp_path / "n.mp3")}))
    assert out["success"], out
    req = fish.server.tts_requests()[-1]
    assert req.body["text"] == "[proud, upbeat] Great news! [excited] The build passed."
    assert out["provider"] == "fish-audio"


def test_text_to_speech_keeps_phoneme_spans_through_hermes_cleanup(fish, tmp_path):
    out = json.loads(handle_function_call("text_to_speech", {
        "text": "Deploy <|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|> now.",
        "output_path": str(tmp_path / "p.mp3")}))
    assert out["success"], out
    assert "<|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|>" in fish.server.tts_requests()[-1].body["text"]


def test_s1_configured_for_text_to_speech_gets_parenthesis_tags(fish, tmp_path):
    fish.configure({"tts_model": "s1"})
    out = json.loads(handle_function_call("text_to_speech", {"text": "[sad] It is over.",
                                                             "output_path": str(tmp_path / "s1.mp3")}))
    assert out["success"], out
    req = fish.server.tts_requests()[-1]
    assert req.model == "s1" and req.body["text"] == "(sad) It is over."


def test_inbound_voice_notes_are_transcribed_by_fish(fish, tmp_path):
    from tools.transcription_tools import transcribe_audio
    clip = tmp_path / "note.ogg"
    clip.write_bytes(b"OggS" + bytes(2048))
    fish.configure({"stt_model": "transcribe-1-pro"})
    result = transcribe_audio(str(clip))
    assert result["success"], result
    assert result["transcript"].startswith("<|speaker:0|>Hello from the fake Fish server.")
    req = [r for r in fish.server.requests if r.path == "/v1/asr"][-1]
    assert req.model == "transcribe-1-pro" and req.body["files"]["audio"][0][0] == "note.ogg"


def test_voice_mode_streams_pcm_from_fish(fish):
    from tools.tts_streaming import resolve_streaming_provider
    streamer = resolve_streaming_provider({"provider": "fish-audio"})
    assert streamer is not None
    pcm = b"".join(streamer.stream("[warm] Hello, streaming world."))
    body = fish.server.tts_requests()[-1].body
    assert (body["format"], body["sample_rate"], body["latency"]) == ("pcm", streamer.sample_rate, "balanced")
    assert len(pcm) > 1000 and len(pcm) % 2 == 0


def test_provider_is_unavailable_without_a_key(fish, monkeypatch):
    from agent.tts_registry import get_provider
    monkeypatch.delenv("FISH_API_KEY")
    assert get_provider("fish-audio").is_available() is False
    out = json.loads(handle_function_call("fish_speak", {"text": "Hi."}))
    assert not out["success"] and "FISH_API_KEY" in out["hint"]


def test_hermes_tools_picker_lists_fish_with_its_key_prompt(fish):
    from hermes_cli.tools_config_providers import _plugin_tts_providers
    rows = [r for r in _plugin_tts_providers() if r.get("tts_provider") == "fish-audio"]
    assert rows and rows[0]["env_vars"][0]["key"] == "FISH_API_KEY"


def test_system_prompt_section_teaches_the_agent_and_names_saved_voices(fish, plugin):
    fish.configure({"voices": {"narrator": "a" * 32}})
    from hermes_cli.plugins import get_plugin_manager
    rendered = get_plugin_manager().render_system_prompt_sections({})
    text = "\n".join(s if isinstance(s, str) else str(s) for s in (rendered if isinstance(rendered, list) else [rendered]))
    assert "Fish Audio" in text and "fish_speak" in text and "fish-audio:voice-direction" in text
    assert "narrator" in text


def test_every_skill_resolves_through_skill_view(fish):
    for name in ("voice-direction", "dialogue", "pronunciation", "voices"):
        out = json.loads(handle_function_call("skill_view", {"name": f"fish-audio:{name}"}))
        assert out.get("success", True) and "## Procedure" in json.dumps(out), name
