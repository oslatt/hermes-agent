"""The system-prompt section: frozen into each new session, so it may read the settings of the moment."""

from __future__ import annotations

from typing import Any, Mapping

from .models import resolve_model
from .settings import Settings, VoiceBook

SECTION_ID = "fish-audio.speech"
MAX_CHARS = 1600
_MAX_ALIASES = 12


def render_section(ctx: Any, session_info: Mapping[str, Any]) -> str:
    settings = Settings.load(ctx)
    try:
        model_id, caps, _ = resolve_model(settings.model)
    except ValueError:
        model_id, caps, _ = resolve_model(None)
    syntax = ("free-form [bracket] cues, e.g. [excited], [whispering], [laughing nervously], [emphasis]"
              if caps.cue_syntax == "bracket" else "(parenthesis) tags from a fixed set; write [cues] and the "
              "plugin converts them")
    aliases = sorted(VoiceBook(ctx, settings).all())
    voice_line = (f"Saved voice aliases: {', '.join(aliases[:_MAX_ALIASES])}"
                  + (" ..." if len(aliases) > _MAX_ALIASES else "") + ".") if aliases else (
        "No saved voices yet; find one with fish_voices action=search.")
    return (
        "## Fish Audio speech\n"
        f"Speech goes through Fish Audio (default model {model_id}: {syntax}). Treat it as a voice actor you "
        "direct, not a text reader.\n"
        "- Use fish_speak when delivery matters: emotion, characters, dialogue (lines), pacing (speed), "
        "whispers/laughs/pauses, pronunciation, or a specific voice/model. text_to_speech also uses Fish and "
        "passes its instructions as direction. When fish_speak/fish_voices are not in your tool list they "
        "are loaded on demand: tool_describe(['fish_speak', 'fish_voices']) once, then call them via "
        "tool_call.\n"
        "- Emotion cue at the start of a sentence; effects and [emphasis] inline; at most 3 cues per "
        "sentence; match cues to the meaning, never decorate every line.\n"
        "- Cues belong only in text you send to speech tools, not in normal chat replies.\n"
        "- Before your first expressive performance, dialogue, or pronunciation fix in a session, load "
        "skill_view('fish-audio:voice-direction'); also fish-audio:dialogue, fish-audio:pronunciation, "
        "fish-audio:voices as needed.\n"
        f"- {voice_line}\n"
        "- Clone a voice only with the speaker's permission; never imitate a real person without it."
    )
