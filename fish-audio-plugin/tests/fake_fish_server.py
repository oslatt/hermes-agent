"""A loopback Fish Audio API that enforces the documented request contract and records every call.

The rules come from Fish's OpenAPI/AsyncAPI specs (fishaudio/docs): model header enum, multi-speaker
only on the S2 family, inline references only as MessagePack, parameter ranges, speaker tokens backed
by a voice, <=3 pronunciation dictionaries that do not mix forms. A request that breaks a rule gets
the same status Fish returns (400/401/422), so plugin bugs surface as test failures. Audio bodies
are real WAV/PCM (sine) or container-shaped stubs (MP3 ID3, Ogg ``OggS``) sized to the text.

Also runnable by hand: ``python tests/fake_fish_server.py 8765 <key>``.
"""

from __future__ import annotations

import base64
import email.parser
import email.policy
import json
import math
import re
import secrets
import struct
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

TTS_MODELS = ("s1", "s2-pro", "s2.1-pro", "s2.1-pro-free", "drama-3-preview")
MULTI_SPEAKER = {"s2-pro", "s2.1-pro", "s2.1-pro-free", "drama-3-preview"}
SPEAKER_RE = re.compile(r"<\|speaker:(\d+)\|>")
BRACKET_RE = re.compile(r"\[[^\[\]]+\]")


@dataclass
class Recorded:
    method: str
    path: str
    model: Optional[str]
    content_type: str
    body: Any
    query: Dict[str, List[str]] = field(default_factory=dict)


def sine_pcm(seconds: float, rate: int = 44100) -> bytes:
    n = max(1, int(seconds * rate))
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n))


def wav(pcm: bytes, rate: int = 44100) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm)


class FakeFishServer:
    def __init__(self, api_key: str = "fish-test-key"):
        self.api_key = api_key
        self.requests: List[Recorded] = []
        self.faults: List[Tuple[int, Any]] = []   # (status, body) served before normal handling
        self.transcript = "Hello from the fake Fish server."
        self.echo_asr = False  # ASR "hears" the words of the latest TTS request (live-harness self-test)
        self.voices: Dict[str, Dict[str, Any]] = {}
        self._server: Optional[ThreadingHTTPServer] = None
        self._lock = threading.Lock()
        for title, tags in (("Warm Narrator", ["male", "narration", "calm"]),
                            ("Bright Presenter", ["female", "young", "energetic"]),
                            ("Gravel Captain", ["male", "old", "character"])):
            self.add_voice(title, tags, owner="library")

    def add_voice(self, title: str, tags: List[str], owner: str = "self") -> str:
        vid = secrets.token_hex(16)
        self.voices[vid] = {"_id": vid, "type": "tts", "title": title, "description": f"{title} voice",
                            "tags": tags, "languages": ["en"], "state": "trained", "visibility": "public",
                            "task_count": 1000, "licensed": owner == "library", "samples": [
                                {"title": "sample", "text": f"This is {title}.", "task_id": "t", "audio": ""}],
                            "author": {"_id": owner, "nickname": owner, "avatar": ""}, "_owner": owner}
        return vid

    # lifecycle
    def __enter__(self) -> "FakeFishServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_: Any) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def tts_requests(self) -> List[Recorded]:
        return [r for r in self.requests if r.path.startswith("/v1/tts")]


def _validation(loc: str, msg: str) -> Tuple[int, Any]:
    return 422, [{"loc": ["body", loc], "type": "value_error", "msg": msg}]


def validate_tts(model: str, body: Dict[str, Any], content_type: str) -> Optional[Tuple[int, Any]]:
    text = body.get("text")
    if not isinstance(text, str):
        return _validation("text", "field required")
    ref_id, refs = body.get("reference_id"), body.get("references")
    if refs and "msgpack" not in content_type:
        return _validation("references", "inline references require application/msgpack")
    if isinstance(ref_id, list) and model not in MULTI_SPEAKER:
        return _validation("reference_id", f"multi-speaker is not available on {model}")
    speakers = {int(i) for i in SPEAKER_RE.findall(text)}
    if speakers:
        voices = len(ref_id) if isinstance(ref_id, list) else 0
        if max(speakers) >= voices:
            return 400, {"status": 400, "message": f"speaker {max(speakers)} has no reference_id"}
        if refs is not None and (not isinstance(refs, list) or any(not isinstance(r, list) for r in refs)):
            return _validation("references", "multi-speaker references must be a list per speaker")
    for key, lo, hi in (("temperature", 0, 1), ("top_p", 0, 1), ("early_stop_threshold", 0, 1)):
        if key in body and not lo <= float(body[key]) <= hi:
            return _validation(key, f"must be between {lo} and {hi}")
    if "chunk_length" in body and not 100 <= int(body["chunk_length"]) <= 300:
        return _validation("chunk_length", "must be between 100 and 300")
    speed = (body.get("prosody") or {}).get("speed")
    if speed is not None and not 0.5 <= float(speed) <= 2.0:
        return _validation("prosody.speed", "must be between 0.5 and 2.0")
    if body.get("format", "mp3") not in ("wav", "pcm", "mp3", "opus"):
        return _validation("format", "unsupported format")
    if body.get("latency", "normal") not in ("low", "normal", "balanced"):
        return _validation("latency", "unsupported latency")
    dicts = body.get("pronunciation_dictionary")
    if dicts is not None:
        if len(dicts) > 3:
            return _validation("pronunciation_dictionary", "at most 3 dictionaries")
        kinds = {"items" in d for d in dicts}
        if len(kinds) > 1:
            return _validation("pronunciation_dictionary", "cannot mix references and inline dictionaries")
        for d in dicts:
            for item in d.get("items", []):
                if "<|phoneme_" in item.get("value", "") or not item.get("key") or not item.get("value"):
                    return _validation("pronunciation_dictionary", "invalid item")
    return None


def audio_for(body: Dict[str, Any]) -> bytes:
    speed = float((body.get("prosody") or {}).get("speed", 1.0))
    seconds = max(0.2, len(BRACKET_RE.sub("", body.get("text", ""))) / 60 / speed)
    fmt = body.get("format", "mp3")
    rate = int(body.get("sample_rate") or (48000 if fmt == "opus" else 44100))
    if fmt == "pcm":
        return sine_pcm(seconds, rate)
    if fmt == "wav":
        return wav(sine_pcm(seconds, rate), rate)
    stub = b"OggS" if fmt == "opus" else b"ID3\x04\x00\x00\x00\x00\x00\x00"
    return stub + bytes(int(seconds * 4000))


def _parse_multipart(content_type: str, raw: bytes) -> Tuple[Dict[str, List[str]], Dict[str, List[Tuple[str, bytes]]]]:
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + raw)
    fields: Dict[str, List[str]] = {}
    files: Dict[str, List[Tuple[str, bytes]]] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            files.setdefault(name, []).append((filename, payload))
        else:
            fields.setdefault(name, []).append(payload.decode())
    return fields, files


def _handler(server: FakeFishServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            pass

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _chunked(self, content_type: str, pieces: List[bytes]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for piece in pieces:
                if piece:
                    self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")

        def _read(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            raw = self._read() if method in ("POST", "PATCH") else b""
            ctype = self.headers.get("Content-Type", "")
            model = self.headers.get("model")
            if ctype.startswith("application/json"):
                body: Any = json.loads(raw or b"{}")
            elif "msgpack" in ctype:
                import msgpack
                body = msgpack.unpackb(raw, raw=False)
            elif ctype.startswith("multipart/"):
                fields, files = _parse_multipart(ctype, raw)
                body = {"fields": fields, "files": {k: [(n, len(b)) for n, b in v] for k, v in files.items()}}
            else:
                body = raw
            with server._lock:
                server.requests.append(Recorded(method, url.path, model, ctype, body, parse_qs(url.query)))
                fault = server.faults.pop(0) if server.faults else None
            if self.headers.get("Authorization") != f"Bearer {server.api_key}":
                return self._send(401, {"status": 401, "message": "Invalid Token"})
            if fault:
                return self._send(fault[0], fault[1])
            route = ROUTES.get((method, url.path)) or (
                ROUTES.get((method, "/model/{id}")) if url.path.startswith("/model/") else None)
            if route is None:
                return self._send(404, {"status": 404, "message": "Not Found"})
            route(self, url, model or "s2.1-pro", ctype, body)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

    def tts(h, url, model, ctype, body):
        model = model if model in TTS_MODELS else "s2.1-pro"
        error = validate_tts(model, body, ctype)
        if error:
            return h._send(*error)
        ref = body.get("reference_id")
        for vid in ref if isinstance(ref, list) else [ref] if ref else []:
            if vid not in server.voices and not str(vid).startswith("speaker-"):
                return h._send(400, {"status": 400, "message": f"reference_id {vid} not found"})
        audio = audio_for(body)
        third = max(1, len(audio) // 3)
        h._chunked("audio/mpeg", [audio[:third], audio[third:2 * third], audio[2 * third:]])

    def tts_timestamps(h, url, model, ctype, body):
        error = validate_tts(model if model in TTS_MODELS else "s2.1-pro", body, ctype)
        if error:
            return h._send(*error)
        words = BRACKET_RE.sub(" ", SPEAKER_RE.sub(" ", body["text"])).split()
        audio = audio_for(body)
        events, t = [], 0.0
        for i, word in enumerate(words):
            seg = {"text": word, "start": round(t, 3), "end": round(t + 0.3, 3)}
            t += 0.35
            events.append({"audio_base64": base64.b64encode(audio if i == 0 else b"").decode(), "chunk_seq": 0,
                           "chunk_audio_offset_sec": 0.0,
                           "alignment": {"segments": [dict(s) for s in [seg]] if i == 0 else None}})
        # cumulative snapshot on the last event replaces earlier ones
        events[-1]["alignment"] = {"segments": [{"text": w, "start": round(i * 0.35, 3), "end": round(i * 0.35 + 0.3, 3)}
                                                for i, w in enumerate(words)]}
        h._chunked("text/event-stream", [f"data: {json.dumps(e)}\n\n".encode() for e in events])

    def asr(h, url, model, ctype, body):
        if model not in ("transcribe-1", "transcribe-1-pro"):
            return h._send(*_validation("model", "unknown asr model"))
        files = body.get("files", {}) if isinstance(body, dict) else {}
        if not files.get("audio"):
            return h._send(*_validation("audio", "field required"))
        text = server.transcript
        spoken = [r for r in server.requests if r.path.startswith("/v1/tts") and isinstance(r.body, dict)]
        if server.echo_asr and spoken:
            cue_re = re.compile(r"\([^()]+\)") if spoken[-1].model == "s1" else BRACKET_RE  # the model's native cues
            said = cue_re.sub(" ", re.sub(r"<\|phoneme_start\|>.*?<\|phoneme_end\|>", " ", spoken[-1].body["text"]))
            text = said if model == "transcribe-1-pro" else SPEAKER_RE.sub(" ", said)
        elif model == "transcribe-1-pro":
            text = f"<|speaker:0|>{text}<|speaker:1|>[laughter] Indeed."
        h._send(200, {"text": text, "duration": 1.5, "segments": [], "language_code": "en", "language": "English"})

    def list_models(h, url, model, ctype, body):
        q = parse_qs(url.query)
        items = [v for v in server.voices.values()
                 if (q.get("self") != ["true"] or v["_owner"] == "self")
                 and all(t in v["tags"] for t in q.get("tag", []))
                 and (not q.get("title") or q["title"][0].lower() in v["title"].lower())]
        size = int(q.get("page_size", ["10"])[0])
        if not 1 <= size <= 100:
            return h._send(*_validation("page_size", "must be 1-100"))
        h._send(200, {"total": len(items), "items": [{k: v for k, v in i.items() if k != "_owner"} for i in items[:size]]})

    def model_item(h, url, model, ctype, body):
        vid = url.path.rsplit("/", 1)[-1]
        voice = server.voices.get(vid)
        if voice is None:
            return h._send(404, {"status": 404, "message": "Model not found"})
        if h.command == "DELETE":
            if voice["_owner"] != "self":
                return h._send(403, {"status": 403, "message": "Not your model"})
            del server.voices[vid]
            return h._send(200, {})
        h._send(200, {k: v for k, v in voice.items() if k != "_owner"})

    def create_model(h, url, model, ctype, body):
        fields = body.get("fields", {})
        voices = body.get("files", {}).get("voices", [])
        if fields.get("type") != ["tts"] or fields.get("train_mode") != ["fast"] or not fields.get("title"):
            return h._send(*_validation("type", "type=tts, train_mode=fast and title are required"))
        if not 1 <= len(voices) <= 20:
            return h._send(*_validation("voices", "1-20 voice files required"))
        if fields.get("texts") and len(fields["texts"]) != len(voices):
            return h._send(*_validation("texts", "one transcript per voice file"))
        vid = server.add_voice(fields["title"][0], fields.get("tags", []), owner="self")
        server.voices[vid]["visibility"] = fields.get("visibility", ["private"])[0]
        h._send(201, {k: v for k, v in server.voices[vid].items() if k != "_owner"})

    def voice_design(h, url, model, ctype, body):
        if model != "voice-design-1":
            return h._send(*_validation("model", "voice-design-1 required"))
        if not ctype.startswith("application/json"):
            return h._send(*_validation("body", "JSON only"))
        if not 1 <= len(body.get("instruction", "")) <= 2000 or not 1 <= int(body.get("n", 2)) <= 4:
            return h._send(*_validation("instruction", "invalid instruction or n"))
        clip = base64.b64encode(wav(sine_pcm(0.5))).decode()
        h._send(200, {"candidates": [{"id": f"cand-{i}", "index": i, "audio_base64": clip, "sample_rate": 44100,
                                      "duration_ms": 500} for i in range(int(body.get("n", 2)))]})

    def credit(h, url, model, ctype, body):
        h._send(200, {"_id": "w", "user_id": "u", "credit": "12.50", "created_at": "", "updated_at": ""})

    ROUTES = {("POST", "/v1/tts"): tts, ("POST", "/v1/tts/stream/with-timestamp"): tts_timestamps,
              ("POST", "/v1/asr"): asr, ("GET", "/model"): list_models, ("POST", "/model"): create_model,
              ("GET", "/model/{id}"): model_item, ("DELETE", "/model/{id}"): model_item,
              ("POST", "/v1/voice-design"): voice_design, ("GET", "/wallet/self/api-credit"): credit}
    return Handler


if __name__ == "__main__":  # pragma: no cover - manual probe
    import sys
    srv = FakeFishServer(sys.argv[2] if len(sys.argv) > 2 else "fish-test-key")
    srv._server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), _handler(srv))
    print(f"fake Fish Audio on {srv.base_url}", flush=True)
    srv._server.serve_forever()
