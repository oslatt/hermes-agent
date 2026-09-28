"""Shared synthesis pipeline for the TTS provider and the ``fish_speak`` tool.

``build_request`` turns agent intent (text with cues, voices, direction, prosody, pronunciations,
reference audio) into a valid Fish request for the chosen model; ``render`` executes it, splitting
long scripts into sentence-safe requests that each re-open the active speaker.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from . import markup
from .models import DEFAULT_MODEL, MODELS, resolve_model
from .settings import ADVANCED_FIELDS, Settings

FISH_FORMATS = ("mp3", "wav", "opus", "pcm")
LATENCIES = ("normal", "balanced", "low")
_WAV_RATE = 44100
MAX_PRONUNCIATION_KEYS = 5000


@dataclass
class SpeechRequest:
    model: str
    body: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    speakers: List[str] = field(default_factory=list)


def _multi_speaker_model(settings: Settings) -> str:
    configured = MODELS.get(settings.model)
    return settings.model if configured is not None and configured.multi_speaker else DEFAULT_MODEL


def build_request(
    settings: Settings, text: str, *, voices: Sequence[Optional[str]] = (), model: Optional[str] = None,
    direction: Optional[str] = None, speed: Optional[float] = None, volume: Optional[float] = None,
    temperature: Optional[float] = None, top_p: Optional[float] = None, latency: Optional[str] = None,
    fmt: str = "mp3", normalize: Optional[bool] = None, pronunciations: Optional[Dict[str, str]] = None,
    references: Optional[List[Dict[str, Any]]] = None, speakers: Sequence[str] = (),
) -> SpeechRequest:
    """``voices`` is one id (or ``None`` = Fish default) for single-speaker text, or one id per
    speaker index when the text carries ``<|speaker:N|>`` turns."""
    warnings: List[str] = []
    model_id, caps, note = resolve_model(model or settings.model)
    if note:
        warnings.append(note)
    text = markup.repair_control_tokens(text)
    indices = markup.speaker_indices(text)
    voice_list = [v for v in voices]
    if indices and (len(voice_list) > 1 or max(indices) > 0) and not caps.multi_speaker:
        upgraded = _multi_speaker_model(settings)
        warnings.append(f"{model_id} cannot voice dialogue; used {upgraded} instead.")
        model_id, caps, _ = resolve_model(upgraded)
    if indices and len(voice_list) <= 1 and max(indices) == 0:
        text, indices = markup.strip_speaker_tokens(text), []
    if indices:
        missing = markup.unknown_voice_indices(indices, len(voice_list))
        if missing:
            raise ValueError(f"Text uses speaker index(es) {missing} but only {len(voice_list)} voice(s) were "
                             "given. Pass one voice per speaker (lines[].speaker or speakers=[...]).")
        cloned = {i for i, refs in enumerate(references or []) if isinstance(refs, list) and refs}
        if any(v is None and i not in cloned for i, v in enumerate(voice_list[: max(indices) + 1])):
            raise ValueError("Every speaker in a dialogue needs a voice (alias or id) or reference audio.")
    text, compile_warnings = markup.compile_for_model(text, caps)
    warnings += compile_warnings
    text, direction_warnings = markup.apply_direction(text, direction, caps)
    warnings += direction_warnings
    if not text.strip():
        raise ValueError("Nothing left to speak after removing markup.")

    body: Dict[str, Any] = {"text": text, "format": fmt if fmt in FISH_FORMATS else "mp3",
                            "normalize": settings.normalize if normalize is None else bool(normalize),
                            "latency": (latency or settings.latency) if (latency or settings.latency) in LATENCIES else "normal"}
    if references:  # zero-shot: flat list (one voice) or one list per speaker index (dialogue)
        body["references"] = references
        if indices:
            body["reference_id"] = [v or f"speaker-{i}" for i, v in enumerate(voice_list[: max(indices) + 1])]
    elif indices:
        body["reference_id"] = voice_list[: max(indices) + 1]
    elif voice_list and voice_list[0]:
        body["reference_id"] = voice_list[0]
    prosody = {k: v for k, v in (("speed", speed if speed is not None else settings.speed),
                                 ("volume", volume if volume is not None else settings.volume)) if v is not None}
    if prosody:
        body["prosody"] = {"speed": max(0.5, min(2.0, float(prosody.get("speed", 1.0)))),
                           "volume": max(-20.0, min(20.0, float(prosody.get("volume", 0.0))))}
    for key, value, lo, hi in (("temperature", temperature, 0.0, 1.0), ("top_p", top_p, 0.0, 1.0)):
        chosen = value if value is not None else getattr(settings, key)
        if chosen is not None:
            body[key] = max(lo, min(hi, float(chosen)))
    body.update({k: v for k, v in settings.advanced.items() if k in ADVANCED_FIELDS})
    rules = {**settings.pronunciations, **(pronunciations or {})}
    if rules:
        items = [{"key": str(k), "value": str(v).replace("<|phoneme_start|>", "").replace("<|phoneme_end|>", "").strip(),
                  "case_sensitive": str(k) != str(k).lower()} for k, v in list(rules.items())[:MAX_PRONUNCIATION_KEYS]]
        body["pronunciation_dictionary"] = [{"items": [i for i in items if i["key"] and i["value"]]}]
        if settings.pronunciation_dictionaries:
            warnings.append("Fish cannot mix inline pronunciations with managed dictionaries in one request; "
                            "used the inline rules and skipped the managed dictionaries.")
    elif settings.pronunciation_dictionaries:
        body["pronunciation_dictionary"] = settings.pronunciation_dictionaries[:3]
    return SpeechRequest(model_id, body, warnings, list(speakers))


def wav_header(pcm_bytes: int, rate: int = _WAV_RATE, channels: int = 1, width: int = 2) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + pcm_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * width, channels * width, width * 8) +
            b"data" + struct.pack("<I", pcm_bytes))


def render(settings: Settings, request: SpeechRequest, path: str, *, timestamps: bool = False) -> Dict[str, Any]:
    """Synthesize *request* into *path*; returns ``{path, bytes, requests, timestamps?}``."""
    client = settings.client()
    chunks = markup.split_for_requests(request.body["text"], settings.max_chars_per_request)
    fmt = request.body.get("format", "mp3")
    stitch_wav = fmt == "wav" and len(chunks) > 1
    timings: List[Dict[str, Any]] = []
    total = 0
    try:
        with open(path, "wb") as out:
            if stitch_wav:
                out.write(wav_header(0))
            for chunk in chunks:
                body = {**request.body, "text": chunk}
                if stitch_wav:
                    body.update(format="pcm", sample_rate=_WAV_RATE)
                if timestamps:
                    part = path + ".part"
                    segs = client.tts_with_timestamps(body, request.model, part)
                    offset = timings[-1]["end"] if timings else 0.0
                    timings += [{**s, "start": round(s["start"] + offset, 3), "end": round(s["end"] + offset, 3)} for s in segs]
                    with open(part, "rb") as fh:
                        data = fh.read()
                    os.remove(part)
                    out.write(data)
                    total += len(data)
                else:
                    for piece in client.tts_stream(body, request.model):
                        out.write(piece)
                        total += len(piece)
            if stitch_wav:
                out.seek(0)
                out.write(wav_header(total))
    finally:
        client.close()
    if not total:
        raise RuntimeError("Fish Audio returned no audio")
    result: Dict[str, Any] = {"path": path, "bytes": total, "requests": len(chunks)}
    if timestamps:
        result["timestamps"] = timings
    return result
