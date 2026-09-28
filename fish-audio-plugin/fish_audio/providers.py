"""Hermes speech providers backed by Fish Audio (``tts.provider`` / ``stt.provider: fish-audio``)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterator, List, Optional

from agent.transcription_provider import TranscriptionProvider
from agent.tts_provider import TTSProvider

from . import markup, speech
from .client import FishAudioError
from .models import MODELS, STT_MODELS
from .settings import Settings, VoiceBook, get_api_key

logger = logging.getLogger(__name__)

PROVIDER_NAME = "fish-audio"
# Hermes output format -> (Fish format, file extension)
_FORMATS = {"mp3": ("mp3", ".mp3"), "wav": ("wav", ".wav"), "flac": ("wav", ".wav"),
            "ogg": ("opus", ".ogg"), "opus": ("opus", ".ogg")}
_REWRITE_PROMPT = (
    "You direct a Fish Audio voice actor. Rewrite the script by inserting short delivery cues in square "
    "brackets, e.g. [warm], [excited], [whispering], [laughing], [sighing], [emphasis], [break]. Put an "
    "emotion cue at the start of a sentence whose mood differs from the one before; put [emphasis] right "
    "before a stressed word; use effects only where the words invite them. At most one cue per sentence on "
    "average, never more than three. Keep every spoken word, its order and meaning; add no new sentences. "
    "Return only the rewritten script.")


def _setup_schema() -> Dict[str, Any]:
    return {"name": "Fish Audio", "badge": "expressive",
            "tag": "S2.1-Pro: emotion cues, dialogue, cloning, 83 languages",
            "env_vars": [{"key": "FISH_API_KEY", "prompt": "Fish Audio API key",
                          "url": "https://fish.audio/app/api-keys"}]}


class FishTTSProvider(TTSProvider):
    def __init__(self, ctx: Any):
        self.ctx = ctx

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    @property
    def voice_compatible(self) -> bool:
        return True

    @property
    def supports_pcm_stream(self) -> bool:
        return True

    def get_setup_schema(self) -> Dict[str, Any]:
        return _setup_schema()

    def is_available(self) -> bool:
        try:
            return bool(get_api_key())
        except Exception:  # an unscoped secret read under multiplex means "not for this caller"
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": m.id, "display": m.display, "languages": m.languages, "note": m.note} for m in MODELS.values()]

    def default_model(self) -> Optional[str]:
        return Settings.load(self.ctx).model

    def list_voices(self) -> List[Dict[str, Any]]:
        settings = Settings.load(self.ctx)
        return [{"id": vid, "display": alias} for alias, vid in sorted(VoiceBook(self.ctx, settings).all().items())]

    def default_voice(self) -> Optional[str]:
        return Settings.load(self.ctx).voice or None

    def _expressive(self, text: str, settings: Settings) -> str:
        """Optional host-LLM cue pass for untagged text (gateway voice replies, voice mode)."""
        if not settings.auto_expressive or markup.has_cues(text):
            return text
        try:
            result = self.ctx.llm.complete(
                [{"role": "system", "content": _REWRITE_PROMPT}, {"role": "user", "content": text}],
                temperature=0.4, max_tokens=max(256, len(text)), purpose="fish-audio expressive cues")
            rewritten = (result.text or "").strip()
        except Exception as exc:  # the plain script is always a valid fallback
            logger.debug("fish-audio expressive rewrite failed: %s", exc)
            return text
        # Accept only a rewrite that kept the words (cues added, nothing spoken changed).
        keep = rewritten and markup.spoken_words(rewritten) == markup.spoken_words(text)
        return rewritten if keep else text

    def synthesize(self, text: str, output_path: str, *, voice: Optional[str] = None, model: Optional[str] = None,
                   speed: Optional[float] = None, format: str = "mp3", instructions: Optional[str] = None,
                   **extra: Any) -> str:
        settings = Settings.load(self.ctx)
        fish_format, ext = _FORMATS.get((format or "mp3").lower(), ("mp3", ".mp3"))
        root, current_ext = os.path.splitext(output_path)
        path = output_path if current_ext.lower() == ext else root + ext
        text = self._expressive(markup.repair_control_tokens(text), settings)
        if markup.speaker_indices(text):  # the core tool is single-voice; dialogue belongs to fish_speak
            text = markup.strip_speaker_tokens(text)
        request = speech.build_request(
            settings, text, voices=[VoiceBook(self.ctx, settings).resolve(voice)], model=model or None,
            direction=instructions, speed=speed, fmt=fish_format)
        for warning in request.warnings:
            logger.info("fish-audio: %s", warning)
        speech.render(settings, request, path)
        return path

    def stream(self, text: str, *, voice: Optional[str] = None, model: Optional[str] = None,
               format: str = "opus", sample_rate: Optional[int] = None, **extra: Any) -> Iterator[bytes]:
        settings = Settings.load(self.ctx)
        text = markup.strip_speaker_tokens(markup.repair_control_tokens(text))
        fish_format = format if format in speech.FISH_FORMATS else "opus"
        request = speech.build_request(settings, text, voices=[VoiceBook(self.ctx, settings).resolve(voice)],
                                       model=model or None, fmt=fish_format, latency=settings.stream_latency)
        if sample_rate:
            request.body["sample_rate"] = int(sample_rate)
        client = settings.client()
        try:
            yield from client.tts_stream(request.body, request.model)
        finally:
            client.close()


class FishTranscriptionProvider(TranscriptionProvider):
    def __init__(self, ctx: Any):
        self.ctx = ctx

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    def get_setup_schema(self) -> Dict[str, Any]:
        return _setup_schema()

    def is_available(self) -> bool:
        try:
            return bool(get_api_key())
        except Exception:
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"id": "transcribe-1", "display": "Transcribe 1"},
                {"id": "transcribe-1-pro", "display": "Transcribe 1 Pro (speakers + emotion cues)"}]

    def default_model(self) -> Optional[str]:
        return Settings.load(self.ctx).stt_model

    def transcribe(self, file_path: str, *, model: Optional[str] = None, language: Optional[str] = None,
                   **extra: Any) -> Dict[str, Any]:
        try:
            settings = Settings.load(self.ctx)
            chosen = model if model in STT_MODELS else settings.stt_model
            with open(file_path, "rb") as fh:
                audio = fh.read()
            client = settings.client()
            try:
                result = client.transcribe(audio, os.path.basename(file_path), model=chosen, language=language)
            finally:
                client.close()
            return {"success": True, "transcript": str(result.get("text") or "").strip(), "provider": PROVIDER_NAME}
        except (FishAudioError, OSError, ValueError) as exc:
            return {"success": False, "transcript": "", "provider": PROVIDER_NAME, "error": str(exc)}
