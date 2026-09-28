# 2. Fish Audio capability inventory

Sources (read 2026-09-28): the `fishaudio/docs` repository at `62656ef8` (OpenAPI `openapi.json`,
AsyncAPI `asyncapi.yml`, feature guides, and Fish's own agent skill `.mintlify/skills/fish-audio-api/SKILL.md`),
and the `fish-audio-sdk` 1.3.0 source from PyPI. `docs.fish.audio` and `api.fish.audio` were not
reachable from the build container, so every value below comes from those primary sources, not
from live probing (see §2.9).

## 2.1 Platform facts

| Item | Value |
|---|---|
| REST base | `https://api.fish.audio` |
| WebSocket base | `wss://api.fish.audio` |
| Auth | `Authorization: Bearer <key>`; SDK convention env var `FISH_API_KEY` |
| Model selection | `model` **HTTP header** (not a body field). Unknown or missing value falls back to `s2.1-pro` (paid). |
| Bodies | TTS: JSON or MessagePack (inline `references` need MessagePack). ASR: multipart or MessagePack. Voice design: JSON only. `/model` create: multipart. |
| Errors | JSON `{status, message}`; 400 bad params/unknown voice, 401 key, 402 credit, 403 scope, 404 voice/model, 422 validation array, 429 concurrency, 5xx. Retry only 429/5xx. |
| Concurrency | Starter 5, Elevated 15 (≥ $100 paid), High Volume 50 (≥ $1000). Limit is concurrent requests, not QPS. |
| Pricing | TTS $15 / M UTF-8 bytes (`s2.1-pro`, `s2-pro`, `s1`); `s2.1-pro-free` $0 (fair use, no TTFA/DPA guarantees); ASR $0.36 / audio hour; voice design $0.01 / successful request. |

## 2.2 Text-to-speech models

| Model ID | Intended use | Languages | Expressive syntax | Multi-speaker | Notes |
|---|---|---|---|---|---|
| `s2.1-pro` | Recommended production model; better quality/latency/throughput than S2-Pro; TTFA and DPA guarantees | 83, auto-detected | Free-form natural-language `[bracket]` cues anywhere in text | Yes | API default |
| `s2.1-pro-free` | Same model at $0 for development, prototyping, small business | 83 | Same as `s2.1-pro` | Yes | No latency/DPA guarantees; fair-use limits |
| `s2-pro` | Previous S2 generation; open weights (Qwen3-4B backbone, SGLang serving) | 80+ | `[bracket]` | Yes | ~100 ms TTFA; SDK 1.3 default |
| `s1` | Legacy, 4B params, WER 0.008 | 13 (EN, ZH, JA, DE, FR, ES, KO, AR, RU, NL, IT, PL, PT) | Fixed `(parenthesis)` tag set; emotion tags at sentence start only | **No** (array `reference_id` → 422) | `prosody.normalize_loudness` accepted, no effect |
| `drama-3-preview` | Preview model (behavior and availability may change) | not documented | treat as S2 family | Yes | Accepted on all TTS endpoints |
| `speech-1.5`, `speech-1.6` | Deprecated 2026-02-28 | | `(break)` etc. | No | Do not use |

### Request parameters (`POST /v1/tts`, same body for WebSocket `start.request`)

| Field | Range / values | Default | Category |
|---|---|---|---|
| `text` | string; may contain cues, `<\|speaker:N\|>`, `<\|phoneme_start\|>…<\|phoneme_end\|>` | required | content |
| `reference_id` | string (one voice) or array (one per speaker) | null | voice |
| `references` | `[{audio, text}]` or `[[{audio,text}], …]` (multi-speaker); **MessagePack only**; WAV/MP3/FLAC, 10–30 s clean speech | null | zero-shot cloning |
| `prosody.speed` | 0.5–2.0 | 1.0 | pacing |
| `prosody.volume` | dB, SDK range -20..20 | 0 | loudness |
| `prosody.normalize_loudness` | bool (S2 family only) | true | loudness |
| `temperature` | 0–1 | 0.7 | expressiveness vs consistency |
| `top_p` | 0–1 | 0.7 | diversity |
| `repetition_penalty` | >1 reduces repeats | 1.2 | stability |
| `max_new_tokens` | int per chunk | 1024 | length cap |
| `chunk_length` | 100–300 | 300 | server-side segmentation |
| `min_chunk_length` | 0–100 | 50 | segmentation |
| `condition_on_previous_chunks` | bool | true | voice continuity across chunks |
| `early_stop_threshold` | 0–1 | 1.0 | batch early stop |
| `normalize` | bool; expands numbers/dates for EN/ZH; phoneme tags survive it | true | text normalization |
| `latency` | `normal` (best quality, ~500 ms) / `balanced` (~300 ms) / `low` | `normal` | latency tier |
| `format` | `mp3` / `wav` / `pcm` / `opus` | mp3 | output |
| `sample_rate` | Hz; null → 44100 (48000 for opus) | null | output |
| `mp3_bitrate` | 64 / 128 / 192 kbps | 128 | output |
| `opus_bitrate` | -1000 (auto) / 24000 / 32000 / 48000 / 64000 bps | -1000 | output |
| `pronunciation_dictionary` | ≤3 dictionaries: either `[{id, version}]` (managed) or `[{items:[{key, value, case_sensitive}]}]` (inline); ≤5000 rules, key ≤256 chars, value ≤1024; unresolvable refs silently dropped | null | pronunciation |
| `features` | e.g. `["quality-guard"]` | [] | backend flags |

### Response / transports

| Transport | Endpoint | Streaming | Timestamps | Use |
|---|---|---|---|---|
| HTTP chunked | `POST /v1/tts` | Yes: audio bytes arrive as generated (`Transfer-Encoding: chunked`) | No | Files, and per-sentence streaming with `format: pcm` |
| HTTP SSE | `POST /v1/tts/stream/with-timestamp` | Yes: JSON events `{audio_base64, alignment, chunk_seq, chunk_audio_offset_sec}` | Word-level | Captions, karaoke, lip-sync |
| WebSocket | `wss:///v1/tts/live` | Yes: send `start` → `text`* → `flush`? → `stop`; receive `audio` → `finish{reason}` (all MessagePack binary frames) | No | Incremental text (LLM token streams) |
| WebSocket | `wss:///v1/tts/live/with-timestamp` | Same + `alignment` | Word-level | Live captions |

## 2.3 Expressive control

### S2 family (`s2.1-pro`, `s2.1-pro-free`, `s2-pro`, `drama-3-preview`): `[bracket]` cues

Cues are ordinary text learned from data, so any concise description works (`[whispers sweetly]`,
`[laughing nervously]`, `[slightly sarcastic, rising tone]`). Documented reference vocabulary:

- **Basic emotions (24):** happy, sad, angry, excited, calm, nervous, confident, surprised, satisfied,
  delighted, scared, worried, upset, frustrated, depressed, empathetic, embarrassed, disgusted, moved,
  proud, relaxed, grateful, curious, sarcastic.
- **Advanced emotions (25):** disdainful, unhappy, anxious, hysterical, indifferent, uncertain, doubtful,
  confused, disappointed, regretful, guilty, ashamed, jealous, envious, hopeful, optimistic, pessimistic,
  nostalgic, lonely, bored, contemptuous, sympathetic, compassionate, determined, resigned.
- **Tone (6):** in a hurry tone, shouting, screaming, whispering, soft tone, emphasis.
- **Vocal effects (11):** laughing, chuckling, sobbing, crying loudly, sighing, groaning, panting,
  gasping, yawning, snoring, clear throat (pair with text: "Ha, ha", "sigh", "ahem").
- **Special (5):** audience laughing, background laughter, crowd laughing, break, long-break.
- Common short forms: `[whisper] [laugh] [emphasis] [sigh] [gasp] [pause] [inhale] [exhale]`.

Placement: sentence-level emotion at the start of the sentence; tone, emphasis and effects anywhere;
`[emphasis]` immediately before the stressed word. Intensity via modifiers (`[slightly sad]`,
`[very excited]`) or the mild→intense ladders (satisfied→happy→delighted, frustrated→angry→furious,
nervous→scared→terrified, interested→excited→ecstatic, disappointed→sad→depressed). Stack at most 3 cues
per sentence; do not mix conflicting emotions; cues are free (not billed as tokens, no added latency).

### S1: `(parenthesis)` tags, fixed set

Same 24 + 25 emotion names, tones (`in a hurry tone`, `shouting`, `screaming`, `whispering`, `soft tone`),
effects (`laughing`, `chuckling`, `sobbing`, `crying loudly`, `sighing`, `groaning`, `panting`, `gasping`,
`yawning`, `snoring`), special (`audience laughing`, `background laughter`, `crowd laughing`, `break`,
`long-break`). Emotion tags **must** start the sentence; custom tags are not allowed; wrong syntax is read aloud.

### Paralanguage (all models)

Filler words (`um`, `uh`, `嗯`, `啊`) shape rhythm. Legacy V1.6 parenthesis effects `(break)`,
`(long-break)`, `(breath)`, `(laugh)`, `(cough)`, `(lip-smacking)`, `(sigh)` are experimental.

## 2.4 Pronunciation

| Mechanism | Syntax | Scope |
|---|---|---|
| English phonemes | `<\|phoneme_start\|>K UW2 B ER0 N EH1 T IY0 Z<\|phoneme_end\|>` (CMU Arpabet, stress digits 0/1/2, one word per tag, punctuation outside; IPA unsupported) | per occurrence |
| Chinese phonemes | tone-number pinyin, one syllable per tag: `<\|phoneme_start\|>chong2<\|phoneme_end\|>` | per occurrence |
| Japanese phonemes | OpenJTalk romaji with pitch digits: `<\|phoneme_start\|>ha0shi1ga0<\|phoneme_end\|>` | short phrase |
| Inline dictionary | `pronunciation_dictionary: [{items:[{key:"SQL", value:"EH1 S K Y UW1 EH1 L", case_sensitive:true}]}]` (no marker tokens in values; leftmost-longest substring match) | per request |
| Managed dictionary | `[{id, version}]` from the web app (explicit version required) | reusable |
| Text normalization | `normalize: true` expands numbers/dates (EN/ZH); set false to keep exact surface text | per request |

## 2.5 Multi-speaker dialogue (S2 family and `drama-3-preview`)

`reference_id: ["id-a", "id-b"]` plus `<|speaker:0|>Hello!<|speaker:1|>Hi there!` in `text`; for
zero-shot, `references` becomes an array of arrays (one per speaker) with MessagePack. Speaker index
= position in the array. Cues combine with speakers (`<|speaker:1|>[laughing] No way!`).

## 2.6 Voices

| Capability | Endpoint | Notes |
|---|---|---|
| Library search | `GET /model` `page_size≤100, page_number, title, tag, self, author_id, language, title_language, licensed, sort_by=score\|task_count\|created_at` | Returns `ModelEntity` (`_id`, title, description, tags, languages, samples, state, visibility, task/like counts, author). `licensed=true` = rights secured by Fish. |
| Get | `GET /model/{id}` | |
| Persistent clone | `POST /model` multipart: `type=tts`, `train_mode=fast` (instant), `title`, `voices` (1–20 files), `texts` (transcripts, else ASR), `tags`, `description`, `visibility` (API downgrades public→private), `enhance_audio_quality` | Returns `_id` usable as `reference_id`; `state` created/training/trained/failed |
| Update / delete | `PATCH` / `DELETE /model/{id}` | |
| Zero-shot clone | inline `references` on TTS | No stored model |
| Voice design | `POST /v1/voice-design` header `model: voice-design-1`: `instruction` (1–2000 chars), `reference_text` (≤300; the agent skill says 150, so we cap at 150), `language`, `n` 1–4, `speed` (0,3], `num_step` 1–128, `guidance_scale`, `instruct_guidance_scale`, `seed` | Returns WAV candidates (base64). Not a stored voice: clone a chosen candidate to keep it. |
| Consent | Clone only your own voice or voices with written permission; never public figures without permission | Policy, enforced by our skill + tool text |

## 2.7 Speech-to-text

| Model | Capabilities |
|---|---|
| `transcribe-1` (default) | Transcript, `duration` (s), optional `segments[{text,start,end}]` (`ignore_timestamps=false`), `language_code`, `language` |
| `transcribe-1-pro` | Multi-speaker: inline `<\|speaker:N\|>` turn markers in `text`; inline emotion/vocal-event cues (`[laughter]`, `[高兴]`); segments exclude markers |

`language` is a hint only (auto-detect always runs). One file per request; split long recordings.

## 2.8 Account

`GET /wallet/self/api-credit` (balance), `GET /wallet/self/package`.

## 2.9 Direct parameter vs higher-level abstraction

| Feature | Exposure in the plugin | Why |
|---|---|---|
| model, speed, volume, temperature, top_p, latency, format, normalize, sample_rate/bitrates | Direct tool/config parameters | Simple scalars with clear ranges (clamped) |
| repetition_penalty, chunk_length, min_chunk_length, max_new_tokens, condition_on_previous_chunks, early_stop_threshold, features, normalize_loudness | Config-only (`advanced:` settings) | Rarely needed; keeping them out of the tool schema saves tokens on every call |
| Emotion / tone / effects | **Abstraction**: agent writes S2 `[cue]` syntax everywhere; plugin translates to S1 `(tag)`, drops non-S1 cues with a warning, and lints placement | Model-agnostic authoring; prevents cues being read aloud |
| Delivery direction (`instructions`) | **Abstraction**: becomes a leading `[direction]` cue on S2 | Maps Hermes's existing `instructions` concept |
| Multi-speaker | **Abstraction**: `lines: [{speaker, text}]` → speaker tokens + `reference_id` array; carries speaker across chunk splits | Removes index bookkeeping errors |
| Voices | **Abstraction**: human aliases (`narrator`, `alice`) → IDs in settings/state; library search | Agents should not memorize 32-hex IDs |
| Pronunciation | Direct `pronunciations: {word: phonemes}` → inline dictionary; phoneme tags pass through untouched | Simple map, reusable per call |
| Zero-shot cloning | Direct `reference_audio: [{path, transcript}]` (MessagePack) | |
| Voice design, persistent cloning | Tool actions | Multi-step workflows guided by skill |
| Word timestamps | Returned by the speak tool on request (`timestamps: true` → SSE endpoint, writes `.json` alongside) | Captions/lip-sync |
| Live WebSocket | Not used. Every Hermes streaming consumer cuts sentences first and calls `stream(sentence)`, so HTTP chunked PCM per sentence gives the same time-to-first-audio without a socket or a MessagePack dependency. Revisit if Hermes adds an incremental-text speech surface. | No consumer in Hermes today |
