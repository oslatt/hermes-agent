"""Model-facing tools: ``fish_speak`` (directed performance) and ``fish_voices`` (voice library)."""

from __future__ import annotations

import base64
import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import markup, speech
from .client import FishAudioError
from .models import MODELS, VOICE_DESIGN_MODEL
from .settings import Settings, VoiceBook, get_api_key

TOOLSET = "fish_audio"
_VOICE_PLATFORMS = frozenset({"telegram", "matrix", "feishu", "whatsapp", "signal"})
_MAX_REFERENCE_BYTES = 20 * 1024 * 1024
_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".webm"})
_MEDIA_DIRECTIVE_RE = re.compile(r"media:", re.IGNORECASE)
_MODEL_IDS = list(MODELS)

SPEAK_SCHEMA: Dict[str, Any] = {
    "name": "fish_speak",
    "description": (
        "Perform speech with Fish Audio and return playable audio (MEDIA path). Use it when HOW something is "
        "said matters: emotion, character voices, dialogue, pacing, whispering, laughter, exact pronunciation, a "
        "specific voice or model. Direct it like a voice actor: put cues in [brackets] inside the text. Load "
        "skill_view('fish-audio:voice-direction') before your first expressive performance in a session."),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": (
                "Script to speak. Emotion cue at the START of a sentence ([excited] We won!); tone and effects "
                "anywhere ([whispering], [laughing] Ha ha!, [sighing], [break], [emphasis] right before a stressed "
                "word). S2 models accept free-form cues ([laughing nervously], [slightly sarcastic]); at most 3 per "
                "sentence. Exact pronunciation: <|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|>. "
                "Omit when using lines.")},
            "lines": {"type": "array", "description": (
                "Dialogue instead of text: ordered turns, each {speaker, text}. Every distinct speaker gets its own "
                "voice (cast[speaker], else the speaker name itself as a voice alias or id). Cues work inside each "
                "line."),
                "items": {"type": "object", "properties": {"speaker": {"type": "string"}, "text": {"type": "string"}},
                          "required": ["speaker", "text"]}},
            "cast": {"type": "object", "additionalProperties": {"type": "string"},
                     "description": "Speaker name -> voice alias or id, for lines."},
            "voice": {"type": "string", "description": "Voice alias or 32-hex voice id for single-speaker text. "
                      "Default: the configured voice."},
            "model": {"type": "string", "enum": _MODEL_IDS, "description": (
                "s2.1-pro (default, best), s2.1-pro-free (same model, free dev tier), s2-pro, drama-3-preview "
                "use [bracket] cues and support dialogue; s1 is legacy (fixed tag set, no dialogue).")},
            "direction": {"type": "string", "description": "Overall delivery direction, e.g. 'warm, unhurried, "
                          "faint smile'. Becomes a leading cue; per-sentence cues in text are more precise."},
            "speed": {"type": "number", "description": "Pace multiplier 0.5-2.0 (1.0 natural)."},
            "volume": {"type": "number", "description": "Loudness change in dB, -20 to 20."},
            "temperature": {"type": "number", "description": "0-1. Higher = more varied, animated delivery; "
                            "lower = steadier, more consistent. Default 0.7."},
            "top_p": {"type": "number", "description": "0-1 sampling diversity. Default 0.7."},
            "latency": {"type": "string", "enum": ["normal", "balanced", "low"],
                        "description": "normal = best quality (default); balanced/low = faster start."},
            "pronunciations": {"type": "object", "additionalProperties": {"type": "string"}, "description": (
                "Word -> phonemes applied everywhere in this request: English CMU Arpabet ('EH1 S K Y UW1 EH1 L'), "
                "Chinese tone-number pinyin ('chong2'), Japanese romaji with pitch digits.")},
            "reference_audio": {"type": "array", "description": (
                "Zero-shot cloning from local audio (10-30 s clean speech; WAV/MP3/FLAC) with its exact "
                "transcript. Only with the speaker's permission. For lines, set speaker to the line speaker."),
                "items": {"type": "object", "properties": {"path": {"type": "string"},
                                                           "transcript": {"type": "string"},
                                                           "speaker": {"type": "string"}},
                          "required": ["path", "transcript"]}},
            "format": {"type": "string", "enum": ["mp3", "wav", "opus"],
                       "description": "Default mp3 (opus on voice-note platforms)."},
            "timestamps": {"type": "boolean", "description": "Also write word timings (JSON) for captions."},
            "output_path": {"type": "string", "description": "Optional file path; default is the audio cache."},
        },
        "required": [],
    },
}

VOICES_SCHEMA: Dict[str, Any] = {
    "name": "fish_voices",
    "description": (
        "Find, save, clone and design Fish Audio voices. search/get/mine browse voices; alias saves a short name "
        "you can pass as voice; clone creates a persistent voice from audio the user owns or has permission to "
        "use; design generates candidate voices from a description; delete removes the user's voice; credit shows "
        "the API balance. See skill_view('fish-audio:voices')."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "get", "mine", "alias", "clone", "design", "delete",
                                                   "credit"]},
            "query": {"type": "string", "description": "search: words in the voice title."},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "search: tags such as male, female, narration, young, calm."},
            "language": {"type": "string", "description": "search/design: language code, e.g. en, zh, ja."},
            "licensed": {"type": "boolean", "description": "search: only voices whose rights Fish secured."},
            "sort": {"type": "string", "enum": ["score", "task_count", "created_at"]},
            "limit": {"type": "integer", "description": "search/mine: results (1-20, default 8)."},
            "voice_id": {"type": "string", "description": "get/alias/delete: the 32-hex voice id."},
            "alias": {"type": "string", "description": "alias: short name to save for voice_id."},
            "title": {"type": "string", "description": "clone: name for the new voice."},
            "description": {"type": "string", "description": "clone: optional description."},
            "audio_paths": {"type": "array", "items": {"type": "string"},
                            "description": "clone: 1-20 local audio files of ONE speaker (10-60 s total works well)."},
            "transcripts": {"type": "array", "items": {"type": "string"},
                            "description": "clone: exact transcript per file (optional, improves quality)."},
            "consent": {"type": "boolean", "description": (
                "clone: true only if the voice is the user's own, the speaker gave permission, or the audio "
                "came from design.")},
            "instruction": {"type": "string", "description": "design: voice description (age, timbre, accent, "
                            "energy, context)."},
            "preview_text": {"type": "string", "description": "design: short line (<=150 chars) each candidate reads."},
            "n": {"type": "integer", "description": "design: candidates 1-4 (default 2)."},
            "seed": {"type": "integer", "description": "design: reproducible candidates."},
            "confirm": {"type": "boolean", "description": "delete: must be true, after the user confirmed."},
        },
        "required": ["action"],
    },
}


def _ok(**data: Any) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def _fail(error: str, hint: str = "") -> str:
    return json.dumps({"success": False, "error": error, **({"hint": hint} if hint else {})}, ensure_ascii=False)


def _audio_dir() -> Path:
    try:
        from hermes_constants import get_hermes_dir
        path = Path(get_hermes_dir("cache/audio", "audio_cache"))
    except Exception:
        from hermes_constants import get_hermes_home
        path = Path(get_hermes_home()) / "cache" / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_platform() -> str:
    try:
        from gateway.session_context import get_session_env
        return str(get_session_env("HERMES_SESSION_PLATFORM", "") or "").lower()
    except Exception:
        return ""


def _checked_output_path(raw: str, ext: str) -> Path:
    if any(ord(c) < 32 for c in raw) or _MEDIA_DIRECTIVE_RE.search(raw):
        raise ValueError("output_path must be a plain file path.")
    path = Path(raw).expanduser()
    if ".." in path.parts:
        raise ValueError("output_path must not contain '..'.")
    try:
        from agent.file_safety import is_write_approval_required, is_write_denied
        if is_write_denied(str(path)) or is_write_approval_required(str(path)):
            raise ValueError(f"output_path {path} is a protected location; choose a normal audio folder.")
    except ImportError:
        pass
    if path.suffix.lower() != ext:
        path = path.with_suffix(ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_reference(path: str) -> bytes:
    """Local audio the user pointed at, uploaded to Fish: credential stores and non-audio files are
    refused so a prompt injection cannot exfiltrate them as "reference audio"."""
    p = Path(path).expanduser()
    try:
        from agent.file_safety import get_read_block_error
        blocked = get_read_block_error(str(p))
    except ImportError:
        blocked = None
    if blocked:
        raise ValueError(blocked)
    if p.suffix.lower() not in _AUDIO_SUFFIXES:
        raise ValueError(f"{path} is not an audio file ({', '.join(sorted(_AUDIO_SUFFIXES))}).")
    if not p.is_file():
        raise ValueError(f"reference audio not found: {path}")
    if p.stat().st_size > _MAX_REFERENCE_BYTES:
        raise ValueError(f"reference audio {path} is over 20 MB; use a 10-30 s clip.")
    return p.read_bytes()


def _speaker_voice(book: VoiceBook, name: str, has_reference: bool) -> Optional[str]:
    """A dialogue speaker's voice id; ``None`` when reference audio will clone that speaker instead."""
    try:
        return book.resolve(name)
    except ValueError:
        if has_reference:
            return None
        raise


def _media_tag(path: str, voice_bubble: bool) -> str:
    return ("[[audio_as_voice]]\n" if voice_bubble else "") + f"MEDIA:{path}"


class FishTools:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    def available(self) -> bool:
        try:
            return bool(get_api_key())
        except Exception:
            return False

    # --- fish_speak -----------------------------------------------------------------------------
    def speak(self, args: Dict[str, Any], **_: Any) -> str:
        try:
            return self._speak(args)
        except FishAudioError as exc:
            return _fail(str(exc), exc.hint)
        except ValueError as exc:
            return _fail(str(exc))
        except Exception as exc:  # the envelope is the contract; never raise into the agent loop
            return _fail(f"fish_speak failed: {exc}")

    def _speak(self, args: Dict[str, Any]) -> str:
        if not self.available():
            return _fail("Fish Audio is not configured.", "Set FISH_API_KEY in the Hermes .env "
                         "(https://fish.audio/app/api-keys).")
        settings = Settings.load(self.ctx)
        book = VoiceBook(self.ctx, settings)
        lines, text = args.get("lines"), str(args.get("text") or "").strip()
        if lines and text:
            return _fail("Pass either text or lines, not both.")
        speakers: List[str] = []
        cast = {str(k): str(v) for k, v in (args.get("cast") or {}).items()}
        if lines:
            text, speakers = markup.build_dialogue(lines)
            cloned = {str(r.get("speaker")) for r in args.get("reference_audio") or [] if isinstance(r, dict)}
            voices = [_speaker_voice(book, cast.get(name, name), name in cloned) for name in speakers]
        elif text:
            voices = [book.resolve(args.get("voice"))]
        else:
            return _fail("Nothing to say: pass text or lines.")

        references = None
        if args.get("reference_audio"):
            refs = [{"audio": _read_reference(str(r.get("path") or "")), "text": str(r.get("transcript") or ""),
                     "speaker": str(r.get("speaker") or "")} for r in args["reference_audio"] if isinstance(r, dict)]
            if speakers:
                references = [[{"audio": r["audio"], "text": r["text"]} for r in refs if r["speaker"] == name]
                              for name in speakers]
            else:
                references = [{"audio": r["audio"], "text": r["text"]} for r in refs]

        platform = _session_platform()
        fmt = str(args.get("format") or ("opus" if platform in _VOICE_PLATFORMS else settings.format))
        fmt = fmt if fmt in ("mp3", "wav", "opus") else "mp3"
        ext = {"mp3": ".mp3", "wav": ".wav", "opus": ".ogg"}[fmt]
        request = speech.build_request(
            settings, text, voices=voices, model=args.get("model"), direction=args.get("direction"),
            speed=args.get("speed"), volume=args.get("volume"), temperature=args.get("temperature"),
            top_p=args.get("top_p"), latency=args.get("latency"), fmt=fmt,
            pronunciations=args.get("pronunciations"), references=references, speakers=speakers)
        if args.get("output_path"):
            path = _checked_output_path(str(args["output_path"]), ext)
        else:
            path = _audio_dir() / f"fish_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        rendered = speech.render(settings, request, str(path), timestamps=bool(args.get("timestamps")))
        with open(path, "rb") as fh:
            voice_bubble = fmt == "opus" and platform in _VOICE_PLATFORMS and fh.read(4) == b"OggS"
        result: Dict[str, Any] = {
            "file_path": str(path), "media_tag": _media_tag(str(path), voice_bubble), "model": request.model,
            "voices": request.body.get("reference_id"), "requests": rendered["requests"], "bytes": rendered["bytes"],
            "performed_text": request.body["text"]}
        if speakers:
            result["speakers"] = {i: name for i, name in enumerate(speakers)}
        if "timestamps" in rendered:
            ts_path = path.with_suffix(".timestamps.json")
            ts_path.write_text(json.dumps(rendered["timestamps"], ensure_ascii=False, indent=1), encoding="utf-8")
            result["timestamps_path"] = str(ts_path)
            result["word_count"] = len(rendered["timestamps"])
        if request.warnings:
            result["warnings"] = request.warnings
        return _ok(**result)

    # --- fish_voices ----------------------------------------------------------------------------
    def voices(self, args: Dict[str, Any], **_: Any) -> str:
        action = str(args.get("action") or "")
        handler: Optional[Callable[[Settings, Dict[str, Any]], str]] = _VOICE_ACTIONS.get(action)
        if handler is None:
            return _fail(f"Unknown action {action!r}.", "Use one of: " + ", ".join(_VOICE_ACTIONS))
        if action != "alias" and not self.available():
            return _fail("Fish Audio is not configured.", "Set FISH_API_KEY in the Hermes .env.")
        try:
            return handler(self, Settings.load(self.ctx), args)
        except FishAudioError as exc:
            return _fail(str(exc), exc.hint)
        except ValueError as exc:
            return _fail(str(exc))
        except Exception as exc:
            return _fail(f"fish_voices {action} failed: {exc}")

    @staticmethod
    def _summary(v: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": v.get("_id"), "title": v.get("title"), "tags": v.get("tags", [])[:8],
                "languages": v.get("languages", []), "description": (v.get("description") or "")[:140],
                "uses": v.get("task_count"), "licensed": v.get("licensed", False), "state": v.get("state")}

    def _list(self, settings: Settings, args: Dict[str, Any], mine: bool) -> str:
        limit = max(1, min(20, int(args.get("limit") or 8)))
        client = settings.client()
        try:
            page = client.list_voices({"page_size": limit, "title": args.get("query"), "tag": args.get("tags"),
                                        "language": args.get("language"), "self": "true" if mine else None,
                                        "licensed": "true" if args.get("licensed") and not mine else None,
                                        "sort_by": args.get("sort")})
        finally:
            client.close()
        voices = [self._summary(v) for v in page.get("items", [])]
        return _ok(total=page.get("total", len(voices)), voices=voices,
                   hint="Pass an id as voice, or save it: fish_voices action=alias voice_id=<id> alias=<name>.")

    def _search(self, settings: Settings, args: Dict[str, Any]) -> str:
        return self._list(settings, args, mine=False)

    def _mine(self, settings: Settings, args: Dict[str, Any]) -> str:
        return self._list(settings, args, mine=True)

    def _get(self, settings: Settings, args: Dict[str, Any]) -> str:
        voice_id = VoiceBook(self.ctx, settings).resolve(str(args.get("voice_id") or "") or None)
        if not voice_id:
            raise ValueError("get needs voice_id.")
        client = settings.client()
        try:
            voice = client.get_voice(voice_id)
        finally:
            client.close()
        detail = self._summary(voice)
        detail["samples"] = [{"title": s.get("title"), "text": (s.get("text") or "")[:200]}
                             for s in voice.get("samples", [])[:3]]
        return _ok(voice=detail)

    def _alias(self, settings: Settings, args: Dict[str, Any]) -> str:
        alias = VoiceBook(self.ctx, settings).save(str(args.get("alias") or ""), str(args.get("voice_id") or ""))
        return _ok(alias=alias, voice_id=str(args.get("voice_id")).strip(), aliases=VoiceBook(self.ctx, settings).all())

    def _clone(self, settings: Settings, args: Dict[str, Any]) -> str:
        if args.get("consent") is not True:
            return _fail("Cloning needs consent=true.", "Only clone the user's own voice, a speaker who gave "
                         "permission, or a designed voice. Ask the user first.")
        paths = [str(p) for p in args.get("audio_paths") or []]
        title = str(args.get("title") or "").strip()
        if not title or not 1 <= len(paths) <= 20:
            raise ValueError("clone needs title and 1-20 audio_paths.")
        samples = [(Path(p).name, _read_reference(p)) for p in paths]
        transcripts = [str(t) for t in args.get("transcripts") or []]
        if transcripts and len(transcripts) != len(paths):
            raise ValueError("transcripts must have one entry per audio file (or be omitted).")
        client = settings.client()
        try:
            voice = client.create_voice(title=title, samples=samples, texts=transcripts,
                                        description=str(args.get("description") or ""), visibility="private")
        finally:
            client.close()
        return _ok(voice=self._summary(voice), hint="Save a short name with fish_voices action=alias, then pass "
                   "it as voice.")

    def _delete(self, settings: Settings, args: Dict[str, Any]) -> str:
        if args.get("confirm") is not True:
            return _fail("Deleting a voice is permanent; pass confirm=true after the user agreed.")
        voice_id = VoiceBook(self.ctx, settings).resolve(str(args.get("voice_id") or "") or None)
        if not voice_id:
            raise ValueError("delete needs voice_id.")
        client = settings.client()
        try:
            client.delete_voice(voice_id)
        finally:
            client.close()
        return _ok(deleted=voice_id)

    def _design(self, settings: Settings, args: Dict[str, Any]) -> str:
        instruction = str(args.get("instruction") or "").strip()
        if not 1 <= len(instruction) <= 2000:
            raise ValueError("design needs an instruction of 1-2000 characters.")
        body: Dict[str, Any] = {"instruction": instruction, "n": max(1, min(4, int(args.get("n") or 2)))}
        if args.get("preview_text"):
            body["reference_text"] = str(args["preview_text"])[:150]
        if args.get("language"):
            body["language"] = str(args["language"])
        if args.get("seed") is not None:
            body["seed"] = int(args["seed"])
        client = settings.client()
        try:
            candidates = client.design_voice(body, VOICE_DESIGN_MODEL).get("candidates", [])
        finally:
            client.close()
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = []
        for c in sorted(candidates, key=lambda c: c.get("index", 0)):
            path = _audio_dir() / f"fish_design_{stamp}_{c.get('index', len(out))}.wav"
            path.write_bytes(base64.b64decode(c.get("audio_base64") or ""))
            out.append({"index": c.get("index"), "file_path": str(path), "media_tag": _media_tag(str(path), False),
                        "duration_ms": c.get("duration_ms")})
        if not out:
            raise ValueError("Voice design returned no candidates; try a more concrete instruction.")
        return _ok(candidates=out, hint="Let the user listen. To keep one: fish_voices action=clone "
                   "audio_paths=[<file_path>] title=<name> consent=true (designed voices need no third-party "
                   "consent), then action=alias.")

    def _credit(self, settings: Settings, args: Dict[str, Any]) -> str:
        client = settings.client()
        try:
            credit = client.credit()
        finally:
            client.close()
        return _ok(credit=credit.get("credit"))


_VOICE_ACTIONS: Dict[str, Callable[..., str]] = {
    "search": FishTools._search, "mine": FishTools._mine, "get": FishTools._get, "alias": FishTools._alias,
    "clone": FishTools._clone, "delete": FishTools._delete, "design": FishTools._design,
    "credit": FishTools._credit,
}
