"""Call-time settings for the Fish Audio plugin.

Everything is read per call (never cached at import or registration) because one Hermes process may
serve several profiles: ``ctx.get_config`` reads the active profile's
``plugins.entries.fish-audio.settings`` and ``ctx.state`` is profile-scoped.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import DEFAULT_BASE_URL, FishClient
from .models import DEFAULT_MODEL

API_KEY_ENV = "FISH_API_KEY"
_VOICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9 _.-]{0,39}$")
# Request fields a user may set under ``settings.advanced``; anything else is ignored.
ADVANCED_FIELDS = ("repetition_penalty", "chunk_length", "min_chunk_length", "max_new_tokens",
                   "condition_on_previous_chunks", "early_stop_threshold", "features", "mp3_bitrate",
                   "opus_bitrate", "sample_rate")


def get_api_key() -> str:
    """``FISH_API_KEY`` through the profile secret scope (falls back to the process env on Hermes
    builds without ``agent.secret_scope``)."""
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return os.environ.get(API_KEY_ENV, "").strip()
    return (get_secret(API_KEY_ENV) or "").strip()


def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    try:
        return None if value is None or value == "" else max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return None


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    voice: str = ""
    voices: Dict[str, str] = field(default_factory=dict)
    format: str = "mp3"
    latency: str = "normal"
    stream_latency: str = "balanced"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    speed: Optional[float] = None
    volume: Optional[float] = None
    normalize: bool = True
    pronunciations: Dict[str, str] = field(default_factory=dict)
    pronunciation_dictionaries: List[Dict[str, str]] = field(default_factory=list)
    auto_expressive: bool = False
    stt_model: str = "transcribe-1"
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 120.0
    max_chars_per_request: int = 3000
    advanced: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, ctx: Any) -> "Settings":
        get = lambda key, default=None: ctx.get_config(key, default)  # noqa: E731
        voices = get("voices") or {}
        dictionaries = get("pronunciation_dictionaries") or []
        return cls(
            model=str(get("tts_model") or DEFAULT_MODEL).strip(),
            voice=str(get("voice") or "").strip(),
            voices={str(k).strip().lower(): str(v).strip() for k, v in voices.items()} if isinstance(voices, dict) else {},
            format=str(get("format") or "mp3").lower(),
            latency=str(get("latency") or "normal").lower(),
            stream_latency=str(get("stream_latency") or "balanced").lower(),
            temperature=_num(get("temperature"), 0.0, 1.0),
            top_p=_num(get("top_p"), 0.0, 1.0),
            speed=_num(get("speed"), 0.5, 2.0),
            volume=_num(get("volume"), -20.0, 20.0),
            normalize=bool(get("normalize", True)),
            pronunciations={str(k): str(v) for k, v in (get("pronunciations") or {}).items()},
            pronunciation_dictionaries=[d for d in dictionaries if isinstance(d, dict) and d.get("id") and d.get("version")],
            auto_expressive=bool(get("auto_expressive", False)),
            stt_model=str(get("stt_model") or "transcribe-1").strip(),
            base_url=str(get("base_url") or DEFAULT_BASE_URL).strip(),
            timeout_seconds=_num(get("timeout_seconds"), 5.0, 900.0) or 120.0,
            max_chars_per_request=int(_num(get("max_chars_per_request"), 200, 20000) or 3000),
            advanced={k: v for k, v in (get("advanced") or {}).items() if k in ADVANCED_FIELDS},
        )

    def client(self) -> FishClient:
        return FishClient(get_api_key(), self.base_url, timeout=self.timeout_seconds)


class VoiceBook:
    """Alias -> Fish voice id: user aliases (``settings.voices``) win over ones the agent saved."""

    STATE_KEY = "voice_aliases"

    def __init__(self, ctx: Any, settings: Settings):
        self.ctx, self.settings = ctx, settings

    def saved(self) -> Dict[str, str]:
        try:
            data = self.ctx.state.get(self.STATE_KEY, {}) or {}
        except Exception:  # unreadable state never blocks speech
            return {}
        return {str(k).lower(): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def all(self) -> Dict[str, str]:
        return {**self.saved(), **self.settings.voices}

    def save(self, alias: str, voice_id: str) -> str:
        alias = alias.strip().lower()
        if not _ALIAS_RE.match(alias):
            raise ValueError("Alias must be 1-40 characters: letters, digits, space, '_', '.', '-'.")
        if not _VOICE_ID_RE.match(voice_id.strip()):
            raise ValueError(f"{voice_id!r} is not a Fish voice id (32 hex characters).")
        data = self.saved()
        data[alias] = voice_id.strip()
        self.ctx.state.set(self.STATE_KEY, data)
        return alias

    def resolve(self, name: Optional[str]) -> Optional[str]:
        """Alias or raw id -> id; ``None``/empty -> the default voice (``None`` = Fish's default)."""
        name = (name or self.settings.voice or "").strip()
        if not name:
            return None
        if _VOICE_ID_RE.match(name.lower()):
            return name.lower()
        book = self.all()
        found = book.get(name.lower())
        if found:
            return found
        known = ", ".join(sorted(book)) or "none yet"
        raise ValueError(f"Unknown voice {name!r}. Known aliases: {known}. Find voices with fish_voices "
                         "action=search and save one with action=alias.")
