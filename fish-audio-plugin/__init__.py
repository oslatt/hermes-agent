"""Official Fish Audio plugin for Hermes Agent: expressive TTS, STT, voices, and speech direction skills."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from .fish_audio.prompt import MAX_CHARS, SECTION_ID, render_section
from .fish_audio.providers import FishTranscriptionProvider, FishTTSProvider
from .fish_audio.tools import SPEAK_SCHEMA, TOOLSET, VOICES_SCHEMA, FishTools

SKILLS = {
    "voice-direction": "Direct expressive Fish Audio speech with delivery cues.",
    "dialogue": "Voice multi-speaker scenes and characters with Fish Audio.",
    "pronunciation": "Control Fish Audio pronunciation with phonemes and dictionaries.",
    "voices": "Find, save, clone and design Fish Audio voices.",
}


def register(ctx) -> None:
    ctx.register_tts_provider(FishTTSProvider(ctx))
    ctx.register_transcription_provider(FishTranscriptionProvider(ctx))
    tools = FishTools(ctx)
    ctx.register_tool("fish_speak", TOOLSET, SPEAK_SCHEMA, tools.speak, check_fn=tools.available,
                      description=SPEAK_SCHEMA["description"], emoji="🐟")
    ctx.register_tool("fish_voices", TOOLSET, VOICES_SCHEMA, tools.voices, check_fn=tools.available,
                      description=VOICES_SCHEMA["description"], emoji="🎙️")
    root = Path(__file__).parent / "skills"
    for name, description in SKILLS.items():
        ctx.register_skill(name, root / name / "SKILL.md", description=description)
    ctx.register_system_prompt_section(SECTION_ID, partial(render_section, ctx), max_chars=MAX_CHARS)
