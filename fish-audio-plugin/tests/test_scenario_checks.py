"""The behavior scorers in tests/live/scenarios.py must fail the wrong behavior, not only pass the right one."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "live"))
from fake_fish_server import Recorded  # noqa: E402
from scenarios import LONG_TEXT, SCENARIOS  # noqa: E402

VOICES = {"narrator": "n" * 32, "bright": "b" * 32, "gravel": "g" * 32}
BY_NAME = {s.name: s for s in SCENARIOS}


def tts(text, model="s2.1-pro", **body):
    return [Recorded("POST", "/v1/tts", model, "application/json", {"text": text, **body})]


BAD = {
    "neutral_narration": tts("[excited] Your meeting [happy] with Dana [laughing] is at 3 PM."),
    "emotional_delivery": tts("Version 2.0 just shipped."),
    "whisper": tts("[shouting] The spare key is under the blue flowerpot."),
    "character_dialogue": tts("<|speaker:0|>Hi.<|speaker:0|>Hello.", reference_id=["x" * 32]),
    "pacing": tts("Breathe in and breathe out.", prosody={"speed": 1.2}),
    "intensity_change": tts("[furious] Stop right there. [annoyed] I said STOP."),
    "pronunciation": tts("Our Kubernetes cluster runs nginx."),
    "conversational_reply": tts("[happy] " + "Great day. " * 60),
    "long_form": tts(" ".join(f"[sad] {s}." for s in LONG_TEXT.split(". "))),
    "model_switching": tts("[sad] I missed you.", model="s2.1-pro"),
    "voice_selection": tts("Ahoy!", reference_id=VOICES["narrator"]),
    "unknown_voice_recovery": [],
}


@pytest.mark.parametrize("name", sorted(BY_NAME))
def test_scorer_rejects_the_wrong_behavior(name):
    passed, detail = BY_NAME[name].check(BAD[name], BAD[name], "Here you go!", VOICES)
    assert not passed, (name, detail)


def test_every_scenario_has_a_rejection_case():
    assert set(BAD) == set(BY_NAME)
