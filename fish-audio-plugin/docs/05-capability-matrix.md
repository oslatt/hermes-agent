# 5. Capability matrix: Fish Audio features in Hermes

Legend: ✅ supported and verified against the contract-checking fake server through real Hermes
code paths · 🔒 implemented, live verification pending (needs network access to api.fish.audio and a
key; run `tests/live`) · ⚙️ config-only (not in the tool schema) · ➖ not exposed (reason given).

## Models

| Model | Status | How it is selected | Notes |
|---|---|---|---|
| `s2.1-pro` | ✅ 🔒 | default; `tts_model` setting, `tts.model`, `fish_speak model` | `[bracket]` cues, dialogue |
| `s2.1-pro-free` | ✅ 🔒 | same | default for live tests ($0) |
| `s2-pro` | ✅ 🔒 | same | |
| `drama-3-preview` | ✅ 🔒 | same | treated as S2 family (preview) |
| `s1` | ✅ 🔒 | same | cues compiled to `(tags)`, emotions hoisted to sentence start, dialogue auto-upgraded to an S2 model |
| unknown future id | ✅ | any string | sent as-is with a warning, S2 syntax assumed |
| `speech-1.5` / `speech-1.6` | ✅ | rejected locally | deprecated 2026-02-28, hint names the replacement |
| `transcribe-1` / `transcribe-1-pro` | ✅ 🔒 | `stt_model` setting or `stt.model` | pro keeps `<\|speaker:N\|>` turns and emotion cues |
| `voice-design-1` | ✅ 🔒 | `fish_voices action=design` | billed per request |

## Speech controls

| Fish feature | Hermes invocation | Status |
|---|---|---|
| Emotion cues (49 documented + free-form on S2) | `[cue]` in `fish_speak.text` / `text_to_speech.text`; `direction`; `text_to_speech.instructions` | ✅ 🔒 |
| Tone (whispering, shouting, soft tone, hurry, emphasis) | `[whispering]`, `[emphasis]` before a word | ✅ 🔒 |
| Vocal effects (laughing, sighing, gasping, ...) | `[laughing] Ha, ha!` | ✅ 🔒 |
| Pauses | `[break]`, `[long-break]`, punctuation | ✅ 🔒 |
| Intensity | modifiers (`[slightly sad]`) or the mild→intense ladder (skill) | ✅ 🔒 |
| Automatic cues for plain replies | `auto_expressive: true` (host LLM rewrite, words verified unchanged) | ✅ |
| Speed | `fish_speak.speed`, `text_to_speech.speed`, `speed` setting (clamped 0.5-2.0) | ✅ 🔒 |
| Volume (dB) | `fish_speak.volume`, `volume` setting | ✅ 🔒 |
| Loudness normalization | ⚙️ Fish default (`prosody.normalize_loudness` true on S2) | ➖ not overridable; no use case found |
| Temperature / top_p | `fish_speak.temperature/top_p`, settings | ✅ 🔒 |
| Latency tier | `fish_speak.latency`, `latency` / `stream_latency` settings | ✅ 🔒 |
| Text normalization | `normalize` setting | ⚙️ ✅ |
| repetition_penalty, chunk_length, min_chunk_length, max_new_tokens, condition_on_previous_chunks, early_stop_threshold, features (`quality-guard`) | `advanced` setting | ⚙️ ✅ |
| Output format mp3 / wav / opus | `fish_speak.format`; Hermes `output_format` (flac→wav, ogg→opus) | ✅ |
| PCM | streaming path only | ✅ |
| Sample rate, mp3/opus bitrate | `advanced` setting | ⚙️ ✅ |
| Voice-bubble delivery | automatic Opus on Telegram/WhatsApp/Signal/Matrix/Feishu | ✅ |

## Pronunciation

| Fish feature | Hermes invocation | Status |
|---|---|---|
| English phonemes (CMU Arpabet) | `<\|phoneme_start\|>…<\|phoneme_end\|>` in text (survives Hermes cleanup after core fix L3) | ✅ 🔒 |
| Chinese pinyin / Japanese romaji phonemes | same | ✅ 🔒 |
| Inline pronunciation dictionary | `fish_speak.pronunciations {word: phonemes}`; `pronunciations` setting | ✅ 🔒 |
| Managed dictionaries `{id, version}` | `pronunciation_dictionaries` setting (max 3; not mixed with inline, warned) | ⚙️ ✅ |

## Voices and dialogue

| Fish feature | Hermes invocation | Status |
|---|---|---|
| Library voice by id | `voice: <32-hex>` | ✅ 🔒 |
| Voice aliases | `voices` setting; `fish_voices action=alias` (profile-scoped state) | ✅ |
| Library search (title, tags, language, licensed, sort) | `fish_voices action=search` | ✅ 🔒 |
| Own voices | `fish_voices action=mine` | ✅ 🔒 |
| Voice details + samples | `fish_voices action=get` | ✅ 🔒 |
| Persistent clone (`POST /model`, fast train, private) | `fish_voices action=clone consent=true` | ✅ 🔒 |
| Delete voice | `fish_voices action=delete confirm=true` | ✅ 🔒 |
| Update voice metadata (`PATCH /model/{id}`) | ➖ | not exposed: no agent workflow needs it; the web app covers it |
| Zero-shot clone (inline references, MessagePack) | `fish_speak.reference_audio` | ✅ 🔒 |
| Voice design candidates | `fish_voices action=design` → WAV files | ✅ 🔒 |
| Multi-speaker dialogue (voice ids) | `fish_speak.lines` + `cast` | ✅ 🔒 |
| Multi-speaker zero-shot | `lines` + `reference_audio[].speaker` | ✅ 🔒 |
| Long dialogue | sentence-safe split, active speaker re-opened per request | ✅ |

## Transports and Hermes surfaces

| Surface | Fish transport | Status |
|---|---|---|
| `fish_speak`, `text_to_speech`, gateway voice replies | `POST /v1/tts` chunked, written to file | ✅ 🔒 |
| Word timestamps | `POST /v1/tts/stream/with-timestamp` (SSE) → `.timestamps.json` | ✅ 🔒 |
| CLI/TUI voice mode, gateway streaming, dashboard speak-stream | `POST /v1/tts` `format: pcm` per sentence (core fix L1) | ✅ 🔒 |
| WebSocket `/v1/tts/live` (+ timestamps) | ➖ | no Hermes surface feeds incremental text; sentence streaming gives the same first-audio latency |
| Inbound voice notes, push-to-talk | `POST /v1/asr` multipart | ✅ 🔒 |
| `hermes tools` / Desktop TTS picker | provider setup schema with `FISH_API_KEY` prompt | ✅ |
| Desktop plugin settings form | `config_schema` | ✅ (validated by `hermes plugins validate`) |
| API credit | `fish_voices action=credit` | ✅ 🔒 |
| Fish voice-agent platform (`/v1/agent/*`) | ➖ | a separate product (Fish-hosted agents); Hermes is the agent here |

## Knowledge layer

| Mechanism | Content | Status |
|---|---|---|
| System-prompt section (frozen per session) | model + syntax, when to use `fish_speak`, cue placement, on-demand tool loading, saved aliases, consent rule | ✅ (in real `hermes chat` prompt) |
| Skill `fish-audio:voice-direction` | cue library, intensity ladder, placement, recipes, pitfalls | ✅ (loaded via `skill_view` in real session) |
| Skill `fish-audio:dialogue` | casting, turn writing, consistency | ✅ |
| Skill `fish-audio:pronunciation` | Arpabet/pinyin/romaji, dictionaries | ✅ |
| Skill `fish-audio:voices` | search/alias/clone/design workflows, consent, STT pro | ✅ |
| Tool results | `performed_text`, `warnings`, `hint`s for every error | ✅ |

## Error handling

| Condition | Behavior | Status |
|---|---|---|
| 401 / 402 / 403 / 404 / 400 / 422 | envelope with Fish's message and a fix hint; no retry | ✅ |
| 429 / 5xx / network | 3 retries with exponential backoff, then envelope | ✅ |
| Missing key | provider unavailable; tools return a setup hint | ✅ |
| Unknown voice alias | fails before any request, lists known aliases, suggests search | ✅ (agent recovers in E2E) |
| Speaker without a voice | fails before any request | ✅ |
| Reference file is a credential store or not audio | refused, nothing uploaded | ✅ |
| Rewrite changes words or fails | original text spoken | ✅ |
