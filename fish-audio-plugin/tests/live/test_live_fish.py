"""Live Fish Audio scenario matrix (opt-in: ``pytest tests/live --live``; needs ``FISH_API_KEY``).

Each scenario performs speech through the plugin exactly as Hermes calls it, writes WAV to
``tests/live/out/``, then round-trips the audio through Fish ASR to check what a listener hears:
the words arrive, cues are performed rather than read aloud, pacing changes duration, phonemes land.
``report.md`` in the same folder tabulates every run so repeated loops can be compared.

Default model is ``s2.1-pro-free`` ($0); ``--live-model s2.1-pro`` exercises the paid model. Voice
design is billed ($0.01) and runs only with ``--live-design``.
"""

from __future__ import annotations

import json
import re
import time
import wave
from pathlib import Path

import pytest

from model_tools import handle_function_call

pytestmark = pytest.mark.live
OUT = Path(__file__).parent / "out"
REPORT: list = []


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9']+", re.sub(r"<\|[^|]+\|>|\[[^\]]+\]|\([^)]+\)", " ", text.lower()))


def _overlap(expected: str, heard: str) -> float:
    want, got = _words(expected), set(_words(heard))
    return sum(w in got for w in want) / max(1, len(want))


def _duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


@pytest.fixture(scope="module")
def live(live_hermes):
    OUT.mkdir(exist_ok=True)
    yield live_hermes
    lines = ["| scenario | model | seconds | word match | notes |", "|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['model']} | {r['seconds']:.2f} | {r['match']:.0%} | {r['notes']} |" for r in REPORT]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _speak(name: str, **args):
    args.setdefault("format", "wav")
    args.setdefault("output_path", str(OUT / f"{name}.wav"))
    started = time.monotonic()
    out = json.loads(handle_function_call("fish_speak", args))
    assert out["success"], out
    out["elapsed"] = time.monotonic() - started
    return out


def _hear(path: str, model: str = "transcribe-1") -> str:
    from agent.transcription_registry import get_provider
    return get_provider("fish-audio").transcribe(path, model=model)["transcript"]


def _record(name, out, heard, expected, notes=""):
    match = _overlap(expected, heard)
    REPORT.append({"name": name, "model": out["model"], "seconds": _duration(out["file_path"]), "match": match,
                   "notes": notes or heard[:60].replace("|", "/")})
    return match


def test_neutral_narration(live):
    text = "The library opens at nine in the morning and closes at six in the evening."
    out = _speak("neutral", text=text, voice=live.voice)
    assert _record("neutral", out, _hear(out["file_path"]), text) >= 0.85


def test_emotional_delivery_is_performed_not_read(live):
    text = "[excited] We actually won the championship! [sad] But our captain is leaving the team."
    out = _speak("emotional", text=text, voice=live.voice)
    heard = _hear(out["file_path"])
    assert _record("emotional", out, heard, text) >= 0.8
    assert "excited" not in _words(heard) and "sad" not in _words(heard)


def test_whisper_and_laughter_cues_stay_silent(live):
    text = "[whispering] Keep this between us. [laughing] Ha, ha! I can't believe it worked."
    out = _speak("effects", text=text, voice=live.voice)
    heard = _hear(out["file_path"]).lower()
    assert _record("effects", out, heard, text) >= 0.7
    assert "whispering" not in heard and "laughing" not in heard


def test_pacing_changes_duration(live):
    text = "Take a slow breath in, hold it for a moment, and let it go."
    slow = _speak("pace_slow", text=text, voice=live.voice, speed=0.7)
    fast = _speak("pace_fast", text=text, voice=live.voice, speed=1.4)
    ratio = _duration(slow["file_path"]) / _duration(fast["file_path"])
    _record("pace_slow", slow, _hear(slow["file_path"]), text, f"slow/fast={ratio:.2f}")
    assert ratio > 1.3


def test_pronunciation_controls(live):
    text = "Deploy it with <|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|> and query it with SQL."
    out = _speak("pronunciation", text=text, voice=live.voice, pronunciations={"SQL": "S IY1 K W AH0 L"})
    heard = _hear(out["file_path"]).lower()
    _record("pronunciation", out, heard, "Deploy it with kubernetes and query it with sequel")
    body_text = json.dumps(out["performed_text"])
    assert "<|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|>" in out["performed_text"], body_text
    if live.real:  # only a real listener can judge the sound
        assert "kubernetes" in heard.replace(" ", "")
        assert "sequel" in heard


def test_character_dialogue_has_two_voices(live):
    out = _speak("dialogue", lines=[
        {"speaker": "A", "text": "[curious] Did you hear that noise downstairs?"},
        {"speaker": "B", "text": "[nervous] It's probably just the cat. Probably."},
        {"speaker": "A", "text": "[whispering] We don't have a cat."}], cast={"A": live.voice, "B": live.voice2})
    heard = _hear(out["file_path"], model="transcribe-1-pro")
    speakers = set(re.findall(r"<\|speaker:(\d+)\|>", heard))
    _record("dialogue", out, heard, "Did you hear that noise downstairs? It's probably just the cat. Probably. "
            "We don't have a cat.", f"speakers heard={len(speakers)}")
    assert len(speakers) >= 2


def test_long_form_is_split_and_complete(live):
    live.configure(max_chars_per_request=400)
    text = " ".join(f"Paragraph {i}: the quick brown fox jumps over the lazy dog near the river bank." for i in range(12))
    out = _speak("long_form", text=text, voice=live.voice)
    assert out["requests"] > 1
    assert _record("long_form", out, _hear(out["file_path"]), text, f"requests={out['requests']}") >= 0.8


def test_streaming_first_audio_latency(live):
    from tools.tts_streaming import resolve_streaming_provider
    streamer = resolve_streaming_provider({"provider": "fish-audio", "voice": live.voice})
    started, first, total = time.monotonic(), None, 0
    for chunk in streamer.stream("[warm] Sure, I can help with that right away."):
        first = first or time.monotonic() - started
        total += len(chunk)
    REPORT.append({"name": "streaming", "model": live.model, "seconds": total / 2 / streamer.sample_rate,
                   "match": 1.0, "notes": f"first audio after {first:.2f}s"})
    assert total > streamer.sample_rate and first < 5.0


@pytest.mark.parametrize("model", ["s1", "s2-pro"])
def test_model_switching_keeps_cues_unspoken(live, model):
    text = "[sad] I waited all night. [sighing] Nobody came."
    out = _speak(f"model_{model}", text=text, voice=live.voice, model=model)
    heard = _hear(out["file_path"]).lower()
    assert _record(f"model_{model}", out, heard, text) >= 0.7
    assert "sighing" not in heard and "(sad)" not in heard


def test_timestamps_cover_the_words(live):
    text = "One two three four five."
    out = _speak("timestamps", text=text, voice=live.voice, timestamps=True, format="mp3",
                 output_path=str(OUT / "timestamps.mp3"))
    words = json.loads(Path(out["timestamps_path"]).read_text(encoding="utf-8"))
    assert len(words) >= 4 and words == sorted(words, key=lambda w: w["start"])


def test_error_conditions_are_actionable(live):
    bad_voice = json.loads(handle_function_call("fish_speak", {"text": "Hi.", "voice": "0" * 32}))
    assert not bad_voice["success"] and bad_voice.get("hint")


@pytest.mark.design
def test_voice_design_candidates(live, request):
    if not request.config.getoption("--live-design"):
        pytest.skip("voice design is billed; pass --live-design")
    out = json.loads(handle_function_call("fish_voices", {"action": "design", "n": 1, "preview_text": "Hello there.",
                                                           "instruction": "Calm, warm radio host in her forties"}))
    assert out["success"] and Path(out["candidates"][0]["file_path"]).stat().st_size > 1000
