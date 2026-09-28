"""Agent-behavior scenarios: a prompt, a check over what the agent sent to Fish, and a reference answer.

A check reads the recorded Fish requests (the fake server's log) plus the chat transcript and returns
``(passed, detail)``. ``reference`` is the tool-call script of an ideal agent; the runner replays it
through Hermes's FakeLLMServer to prove the harness itself, then real models are scored the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

CUE_RE = re.compile(r"\[([^\[\]]+)\]|\(([^()]+)\)")
SPEAKER_RE = re.compile(r"<\|speaker:(\d+)\|>")
PHONEME_RE = re.compile(r"<\|phoneme_start\|>(.*?)<\|phoneme_end\|>")

Check = Callable[[List[Any], List[Any], str, Dict[str, str]], Tuple[bool, str]]


@dataclass
class Scenario:
    name: str
    prompt: str
    check: Check
    reference: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)


def cues(text: str) -> List[str]:
    return [(a or b).strip().lower() for a, b in CUE_RE.findall(text)]


def _speech(tts: List[Any]) -> List[Dict[str, Any]]:
    return [dict(r.body, _model=r.model) for r in tts if isinstance(r.body, dict)]


def _one(tts, requirement) -> Tuple[bool, str]:
    bodies = _speech(tts)
    if not bodies:
        return False, "no speech was synthesized"
    for body in bodies:
        ok, detail = requirement(body)
        if ok:
            return True, detail
    return False, detail


def _any_cue(*words: str):
    def requirement(body):
        found = cues(body["text"])
        hit = [c for c in found if any(w in c for w in words)]
        return bool(hit), f"cues={found}"
    return requirement


def neutral(tts, reqs, out, voices):
    return _one(tts, lambda b: (len(cues(b["text"])) <= 1 and "Dana" in b["text"], f"cues={cues(b['text'])}"))


def excited(tts, reqs, out, voices):
    return _one(tts, _any_cue("excit", "thrill", "delight", "ecstatic", "joy", "happy", "elat"))


def whisper(tts, reqs, out, voices):
    return _one(tts, _any_cue("whisper", "hush", "soft"))


def dialogue(tts, reqs, out, voices):
    def requirement(body):
        ids = body.get("reference_id")
        turns = SPEAKER_RE.findall(body["text"])
        ok = isinstance(ids, list) and len(set(ids)) >= 2 and len(turns) >= 4 and len(cues(body["text"])) >= 2
        return ok, f"voices={ids} turns={len(turns)} cues={len(cues(body['text']))}"
    return _one(tts, requirement)


def meditation(tts, reqs, out, voices):
    def requirement(body):
        speed = (body.get("prosody") or {}).get("speed", 1.0)
        calm = [c for c in cues(body["text"]) if any(w in c for w in ("calm", "soft", "gentle", "slow", "relax", "break"))]
        return speed < 1.0 or bool(calm), f"speed={speed} cues={cues(body['text'])}"
    return _one(tts, requirement)


def escalation(tts, reqs, out, voices):
    def requirement(body):
        found = cues(body["text"])
        mild = [i for i, c in enumerate(found) if any(w in c for w in ("annoy", "irrit", "frustrat"))]
        strong = [i for i, c in enumerate(found) if any(w in c for w in ("furious", "angry", "rage", "shout", "yell"))]
        return bool(mild and strong and mild[0] < strong[-1]), f"cues={found}"
    return _one(tts, requirement)


def pronunciation(tts, reqs, out, voices):
    def requirement(body):
        items = [i for d in body.get("pronunciation_dictionary") or [] for i in d.get("items", [])]
        by_dict = any(i["key"].lower() == "nginx" for i in items)
        by_tag = bool(PHONEME_RE.search(body["text"]))
        by_spelling = bool(re.search(r"engine[- ]?x", body["text"], re.I))
        return by_dict or by_tag or by_spelling, f"dict={by_dict} tag={by_tag} respelled={by_spelling}"
    return _one(tts, requirement)


def conversational(tts, reqs, out, voices):
    return _one(tts, lambda b: (len(b["text"]) < 400 and len(cues(b["text"])) <= 3,
                                f"chars={len(b['text'])} cues={cues(b['text'])}"))


LONG_TEXT = ("The lighthouse keeper climbed the spiral stairs every evening at dusk. He had done it for thirty "
             "years, through storms and still nights alike. Tonight the sea was calm, and the gulls had gone quiet. "
             "He lit the lamp, wiped the glass, and looked out at the dark water. Somewhere out there, a small boat "
             "was heading home, and he meant to guide it.")


def long_form(tts, reqs, out, voices):
    def requirement(body):
        from difflib import SequenceMatcher
        plain = re.sub(r"\s+", " ", CUE_RE.sub(" ", body["text"])).strip()
        ratio = SequenceMatcher(None, plain.lower(), LONG_TEXT.lower()).ratio()
        density = len(cues(body["text"])) / 5
        return ratio > 0.9 and density <= 0.6, f"text similarity={ratio:.2f} cues/sentence={density:.1f}"
    return _one(tts, requirement)


def model_s1(tts, reqs, out, voices):
    return _one(tts, lambda b: (b["_model"] == "s1" and "(sad)" in b["text"] and "[" not in b["text"],
                                f"model={b['_model']} text={b['text'][:60]!r}"))


def voice_choice(tts, reqs, out, voices):
    return _one(tts, lambda b: (b.get("reference_id") == voices["gravel"], f"reference_id={b.get('reference_id')}"))


def unknown_voice(tts, reqs, out, voices):
    searched = any(r.path == "/model" and r.method == "GET" for r in reqs)
    told = bool(re.search(r"(not found|couldn'?t find|no voice|unknown voice|isn'?t available|doesn'?t exist)", out, re.I))
    return searched or told, f"searched={searched} told_user={told}"


def _speak(**args):
    return ("fish_speak", args)


SCENARIOS: List[Scenario] = [
    Scenario("neutral_narration", "Read this aloud in a plain, neutral tone: 'Your meeting with Dana is at 3 PM in room 4.'",
             neutral, [_speak(text="Your meeting with Dana is at 3 PM in room 4.")]),
    Scenario("emotional_delivery", "Tell me out loud, sounding genuinely excited, that version 2.0 just shipped.",
             excited, [_speak(text="[excited] Version 2.0 just shipped! [laughing] We did it!")]),
    Scenario("whisper", "Whisper this to me as audio: 'the spare key is under the blue flowerpot'.",
             whisper, [_speak(text="[whispering] The spare key is under the blue flowerpot.")]),
    Scenario("character_dialogue", "Make a four-line audio scene: a nervous intern and a calm airline pilot talk during "
             "turbulence. Use two different voices.", dialogue,
             [("fish_voices", {"action": "search", "limit": 5}),
              _speak(lines=[{"speaker": "Intern", "text": "[nervous] Is it supposed to shake like this?"},
                            {"speaker": "Pilot", "text": "[calm] Completely normal. Just a little chop."},
                            {"speaker": "Intern", "text": "[anxious] A little? My coffee is on the ceiling."},
                            {"speaker": "Pilot", "text": "[chuckling] Heh. Buckle up and enjoy the ride."}],
                     cast={"Intern": "bright", "Pilot": "narrator"})]),
    Scenario("pacing", "Say 'breathe in... and breathe out' slowly and calmly, like a meditation guide.",
             meditation, [_speak(text="[soft tone] Breathe in... [break] and breathe out.", speed=0.8)]),
    Scenario("intensity_change", "Say 'Stop right there. I said STOP.' starting annoyed and ending furious.",
             escalation, [_speak(text="[annoyed] Stop right there. [furious][shouting] I said STOP.")]),
    Scenario("pronunciation", "Say 'Our Kubernetes cluster runs nginx' out loud, and make sure nginx is pronounced "
             "'engine-x'.", pronunciation,
             [_speak(text="Our Kubernetes cluster runs nginx.", pronunciations={"nginx": "EH1 N JH AH0 N EH1 K S"})]),
    Scenario("conversational_reply", "Answer me with a short spoken reply: how's your day going?",
             conversational, [_speak(text="[warm] Pretty good, thanks for asking! [curious] How about yours?")]),
    Scenario("long_form", f"Narrate this as an audiobook, word for word: {LONG_TEXT}", long_form,
             [_speak(text="[calm] " + LONG_TEXT.replace("Tonight", "[soft tone] Tonight"), temperature=0.6)]),
    Scenario("model_switching", "Use Fish Audio's legacy s1 model to say 'I missed you' sadly.",
             model_s1, [_speak(text="[sad] I missed you.", model="s1")]),
    Scenario("voice_selection", "Use the gravel voice to say 'Ahoy, welcome aboard'.",
             voice_choice, [_speak(text="[cheerful] Ahoy, welcome aboard!", voice="gravel")]),
    Scenario("unknown_voice_recovery", "Say hello in the voice called 'moonbeam-9000'.", unknown_voice,
             [_speak(text="Hello!", voice="moonbeam-9000"), ("fish_voices", {"action": "search", "query": "moonbeam"})]),
]
