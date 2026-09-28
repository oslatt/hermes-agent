"""Fish Audio model capabilities: the one table the cue compiler, tools, prompt section and docs read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class FishModel:
    id: str
    display: str
    cue_syntax: str          # "bracket" (free-form [cue]) or "paren" (fixed (tag) set)
    multi_speaker: bool
    languages: str
    note: str


MODELS: Dict[str, FishModel] = {m.id: m for m in (
    FishModel("s2.1-pro", "Fish Audio S2.1-Pro", "bracket", True, "83 languages, auto-detected",
              "Recommended for production: best quality and latency."),
    FishModel("s2.1-pro-free", "Fish Audio S2.1-Pro Free", "bracket", True, "83 languages, auto-detected",
              "Same model as s2.1-pro at $0 for development; no latency guarantees."),
    FishModel("s2-pro", "Fish Audio S2-Pro", "bracket", True, "80+ languages, auto-detected",
              "Previous S2 generation."),
    FishModel("drama-3-preview", "Fish Audio Drama 3 (preview)", "bracket", True, "not documented",
              "Preview model; behavior and availability may change."),
    FishModel("s1", "Fish Audio S1 (legacy)", "paren", False,
              "13 languages: en zh ja de fr es ko ar ru nl it pl pt",
              "Legacy: fixed (parenthesis) emotion set, no dialogue."),
)}

DEFAULT_MODEL = "s2.1-pro"
DEPRECATED_MODELS = {"speech-1.5": "s2.1-pro", "speech-1.6": "s2.1-pro"}
STT_MODELS: Tuple[str, ...] = ("transcribe-1", "transcribe-1-pro")
VOICE_DESIGN_MODEL = "voice-design-1"


def resolve_model(model_id: Optional[str], default: str = DEFAULT_MODEL) -> Tuple[str, FishModel, Optional[str]]:
    """``(id to send, capabilities, warning)``. Unknown ids are sent as-is (Fish falls back
    server-side) with S2 capabilities assumed, so a new Fish model works without a plugin release."""
    mid = (model_id or default or DEFAULT_MODEL).strip()
    if mid in DEPRECATED_MODELS:
        raise ValueError(f"Fish Audio model {mid!r} was deprecated on 2026-02-28; use "
                         f"{DEPRECATED_MODELS[mid]!r}.")
    known = MODELS.get(mid)
    if known is not None:
        return mid, known, None
    return mid, FishModel(mid, mid, "bracket", True, "unknown", "Unknown model id."), (
        f"Model {mid!r} is not in this plugin's table; sending it as-is and assuming S2 [bracket] cues.")
