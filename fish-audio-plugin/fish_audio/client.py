"""Minimal Fish Audio REST client on httpx (a Hermes core dependency).

JSON bodies by default; MessagePack only when inline reference audio must travel as raw bytes.
429/5xx and transport failures retry with exponential backoff before any byte is consumed;
every other failure raises :class:`FishAudioError` carrying an actionable hint.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

DEFAULT_BASE_URL = "https://api.fish.audio"
USER_AGENT = "hermes-fish-audio/0.1"

_HINTS: Dict[int, str] = {
    400: "Fish rejected the request; a voice id may not exist. Check it with fish_voices action=get.",
    401: "The Fish Audio API key is missing or invalid. Set FISH_API_KEY (https://fish.audio/app/api-keys).",
    402: "The Fish Audio account is out of API credit. Top up at https://fish.audio/app/developers/billing/.",
    403: "This API key is not permitted to use that resource.",
    404: "Voice or model not found. Search voices with fish_voices action=search.",
    422: "A parameter is out of range or the wrong type; see the message for the field.",
    429: "Fish Audio concurrency limit reached; retry shortly.",
}
_RETRYABLE = frozenset({429, 500, 502, 503, 504})


class FishAudioError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        self.hint = _HINTS.get(status, "Fish Audio service error; retry later." if status >= 500 else "")
        super().__init__(f"Fish Audio {status}: {message}" + (f" ({self.hint})" if self.hint else ""))


def _error_from(response: httpx.Response) -> FishAudioError:
    try:
        body = json.loads(response.read() or b"null")
    except (ValueError, httpx.HTTPError):
        body = None
    if isinstance(body, dict):
        message = body.get("message") or body.get("detail") or json.dumps(body)[:300]
    elif isinstance(body, list):  # 422 validation array
        message = "; ".join(f"{'.'.join(map(str, e.get('loc', [])))}: {e.get('msg', '')}"
                            for e in body if isinstance(e, dict)) or json.dumps(body)[:300]
    else:
        message = (response.text or response.reason_phrase or "error")[:300]
    return FishAudioError(response.status_code, str(message))


def pack_msgpack(payload: Dict[str, Any]) -> bytes:
    try:
        import msgpack
    except ImportError as exc:  # declared in plugin.yaml python_dependencies
        raise FishAudioError(0, "inline reference audio needs the 'msgpack' package; reinstall the "
                                "fish-audio plugin (hermes plugins install) to add it") from exc
    return msgpack.packb(payload, use_bin_type=True)


class FishClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, *, timeout: float = 120.0,
                 max_retries: int = 3, backoff: float = 0.5):
        if not api_key:
            raise FishAudioError(401, "no API key configured")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries, self.backoff = max_retries, backoff
        self._http = httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(timeout, connect=15.0),
                                  headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT})

    def close(self) -> None:
        self._http.close()

    # --- transport ------------------------------------------------------------------------------
    def _open(self, method: str, path: str, *, model: Optional[str] = None, **kwargs: Any) -> httpx.Response:
        """Send and return an open streaming response with a 2xx status (caller closes it)."""
        headers = dict(kwargs.pop("headers", None) or {})
        if model:
            headers["model"] = model
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.send(self._http.build_request(method, path, headers=headers, **kwargs),
                                           stream=True)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise FishAudioError(0, f"network error talking to {self.base_url}: {exc}") from exc
            else:
                if response.is_success:
                    return response
                error = _error_from(response)
                response.close()
                if response.status_code not in _RETRYABLE or attempt >= self.max_retries:
                    raise error
            time.sleep(self.backoff * (2 ** attempt))
        raise AssertionError("unreachable")

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._open(method, path, **kwargs)
        try:
            raw = response.read()
            return json.loads(raw) if raw.strip() else {}
        finally:
            response.close()

    @staticmethod
    def _tts_body(body: Dict[str, Any]) -> Dict[str, Any]:
        if body.get("references"):
            return {"content": pack_msgpack(body), "headers": {"Content-Type": "application/msgpack"}}
        return {"json": body}

    # --- text to speech -------------------------------------------------------------------------
    def tts_stream(self, body: Dict[str, Any], model: str) -> Iterator[bytes]:
        """Audio bytes as Fish generates them (chunked ``POST /v1/tts``)."""
        response = self._open("POST", "/v1/tts", model=model, **self._tts_body(body))
        try:
            for chunk in response.iter_bytes():
                if chunk:
                    yield chunk
        finally:
            response.close()

    def tts_to_file(self, body: Dict[str, Any], model: str, path: str) -> int:
        written = 0
        with open(path, "wb") as fh:
            for chunk in self.tts_stream(body, model):
                fh.write(chunk)
                written += len(chunk)
        if not written:
            raise FishAudioError(0, "Fish Audio returned no audio")
        return written

    def tts_with_timestamps(self, body: Dict[str, Any], model: str, path: str) -> List[Dict[str, Any]]:
        """``POST /v1/tts/stream/with-timestamp`` (SSE): writes audio, returns absolute word timings."""
        response = self._open("POST", "/v1/tts/stream/with-timestamp", model=model, **self._tts_body(body))
        alignments: Dict[int, Tuple[float, List[Dict[str, Any]]]] = {}
        written = 0
        try:
            with open(path, "wb") as fh:
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    audio = event.get("audio_base64")
                    if audio:
                        data = base64.b64decode(audio)
                        fh.write(data)
                        written += len(data)
                    alignment = event.get("alignment")
                    if isinstance(alignment, dict) and "chunk_seq" in event:
                        alignments[int(event["chunk_seq"])] = (
                            float(event.get("chunk_audio_offset_sec") or 0.0), alignment.get("segments") or [])
        finally:
            response.close()
        if not written:
            raise FishAudioError(0, "Fish Audio returned no audio")
        return [{"text": seg.get("text", ""), "start": round(offset + float(seg.get("start", 0)), 3),
                 "end": round(offset + float(seg.get("end", 0)), 3)}
                for _, (offset, segments) in sorted(alignments.items()) for seg in segments]

    # --- speech to text -------------------------------------------------------------------------
    def transcribe(self, audio: bytes, filename: str, *, model: str, language: Optional[str] = None,
                   timestamps: bool = False) -> Dict[str, Any]:
        data = {"ignore_timestamps": "false" if timestamps else "true"}
        if language:
            data["language"] = language
        return self._json("POST", "/v1/asr", model=model, files={"audio": (filename, audio)}, data=data)

    # --- voices ---------------------------------------------------------------------------------
    def list_voices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """``GET /model``; *params* uses Fish's query names (including ``self``)."""
        return self._json("GET", "/model", params={k: v for k, v in params.items() if v not in (None, "", [])})

    def get_voice(self, voice_id: str) -> Dict[str, Any]:
        return self._json("GET", f"/model/{voice_id}")

    def create_voice(self, *, title: str, samples: List[Tuple[str, bytes]], texts: Optional[List[str]] = None,
                     description: str = "", tags: Optional[List[str]] = None, visibility: str = "private",
                     enhance_audio_quality: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": "tts", "train_mode": "fast", "title": title, "visibility": visibility,
                                "enhance_audio_quality": "true" if enhance_audio_quality else "false",
                                "texts": list(texts or []), "tags": list(tags or [])}
        if description:
            data["description"] = description
        files = [("voices", (name, blob)) for name, blob in samples]
        return self._json("POST", "/model", data=data, files=files)

    def delete_voice(self, voice_id: str) -> None:
        self._json("DELETE", f"/model/{voice_id}")

    def design_voice(self, body: Dict[str, Any], model: str) -> Dict[str, Any]:
        return self._json("POST", "/v1/voice-design", model=model, json=body)

    def credit(self) -> Dict[str, Any]:
        return self._json("GET", "/wallet/self/api-credit")
