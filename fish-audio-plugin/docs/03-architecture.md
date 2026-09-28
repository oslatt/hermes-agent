# 3. Integration architecture

Guiding principle: Hermes should direct Fish Audio like a voice actor, not feed it text to read.
Three layers make that possible without the model knowing Fish's API:

1. **Provider layer** (no model involvement): `tts.provider: fish-audio` / `stt.provider: fish-audio`
   make every existing Hermes speech surface (the `text_to_speech` tool, gateway voice replies, CLI/TUI
   voice mode, Desktop, dashboard, inbound voice-note transcription) speak and listen through Fish.
2. **Performance layer** (model-directed): two plugin tools, `fish_speak` and `fish_voices`, expose what
   core `text_to_speech` cannot: per-call voice and model, multi-speaker dialogue, delivery direction,
   pacing and loudness, pronunciation, zero-shot cloning, voice search/cloning/design, timestamps.
3. **Knowledge layer** (teaches the model): a short system-prompt section frozen per session, four
   on-demand skills (the `voice.md` capability library), tool descriptions, and tool-result hints.
   Hermes defers plugin tools behind Tool Search, so the section also says how to reach them
   (`tool_describe` then `tool_call`).

```
                    ┌───────────── knowledge ─────────────┐
 system prompt ────▶│ "Fish Audio is an expressive voice   │   skill_view("fish-audio:voice-direction")
 section (frozen)   │  actor; cues in [brackets]; load the │──▶ fish-audio:dialogue / :pronunciation / :voices
                    │  skills before directing speech"     │
                    └──────────────────────────────────────┘
 model ──tool call──▶ fish_speak / fish_voices ─┐
 model ──tool call──▶ text_to_speech ───────────┤        ┌─────────────┐     ┌──────────────┐
 gateway voice reply / voice mode ──────────────┼──────▶ │ markup.py   │───▶ │ client.py    │──▶ api.fish.audio
 voice note in ──▶ transcription ───────────────┘        │ cue compile │     │ HTTP, retry, │
                                                          │ dialogue    │     │ errors       │
                                                          └─────────────┘     └──────────────┘
```

## 3.1 Components (standalone repo layout; `fish-audio-plugin/` is the repo root)

| File | Responsibility |
|---|---|
| `plugin.yaml` | Manifest v2: tools, `config_schema` (settings), rich `requires_env` for `FISH_API_KEY`, `python_dependencies` (`msgpack`, only for inline reference audio). |
| `__init__.py` | `register(ctx)`: providers, tools, skills, system prompt section. Internals live in the `fish_audio/` subpackage so plugin module names never shadow Hermes packages (`tools`, `models`). |
| `fish_audio/models.py` | Model capability table: id, family, cue syntax, multi-speaker, languages, pricing tier, status. Single source for validation, prompt text and docs. |
| `fish_audio/markup.py` | Cue compiler: S2 `[cue]` ↔ S1 `(tag)` translation, placement lint, `instructions` → leading cue, dialogue assembly (`lines` → `<\|speaker:N\|>`), speaker carry-over across chunks, control-token protection/repair. Pure functions. |
| `fish_audio/client.py` | Minimal HTTP client (httpx, already a Hermes core dep): TTS (file and chunked stream), SSE timestamps, ASR, voices, voice design, credit. Typed `FishAudioError` with status, retry on 429/5xx with backoff, clear messages for 401/402/404/422. |
| `fish_audio/settings.py` | Call-time settings resolution (`plugins.entries.fish-audio.settings`, profile-aware), API-key lookup through `agent.secret_scope.get_secret`, voice alias resolution (settings aliases, then aliases saved by the agent in plugin state). |
| `fish_audio/providers.py` | `FishTTSProvider(TTSProvider)` and `FishTranscriptionProvider(TranscriptionProvider)`. |
| `fish_audio/tools.py` | `fish_speak`, `fish_voices` schemas + handlers (dict dispatch for voice actions). |
| `fish_audio/prompt.py` | Builds the system-prompt section from the current settings (model, cue syntax, voice aliases). |
| `skills/*/SKILL.md` | `voice-direction` (emotion, tone, effects, pacing, intensity, recipes), `dialogue`, `pronunciation`, `voices`. |

## 3.2 Model selection

- Default `s2.1-pro` (Fish's production recommendation); `s2.1-pro-free` offered in setup for
  development. Setting `model`, `tts.model`, or a per-call `model` argument (tool) chooses; per call wins.
- The model table drives behavior: cue syntax (bracket vs parenthesis), multi-speaker allowed,
  languages. Unknown model ids pass through with a warning (Fish falls back server-side), so a new
  Fish model works without a plugin release.
- Deprecated ids (`speech-1.5`, `speech-1.6`) are rejected locally with a migration hint.

## 3.3 TTS paths

| Path | How Fish is reached | Expressive behavior |
|---|---|---|
| `text_to_speech` tool / gateway voice replies | `FishTTSProvider.synthesize` | Cues in text are compiled for the model; `instructions` become a leading cue; optional `auto_expressive` rewrites untagged text with the host LLM (xAI/Gemini precedent), never when the text already has cues. |
| `fish_speak` tool | client directly | Full control: voice/model per call, `direction`, dialogue `lines`, speed/volume/temperature/top_p/latency, `pronunciations`, `reference_audio`, `timestamps`. Returns `MEDIA:` tag + warnings. |
| Voice mode / gateway streaming / dashboard speak-stream | core adapter → `FishTTSProvider.stream(format="pcm")` | HTTP chunked PCM per sentence, `latency: balanced` by default for streaming. |

## 3.4 STT

`FishTranscriptionProvider` (`stt.provider: fish-audio`): `transcribe-1` default; `transcribe-1-pro`
via `stt.model` or settings `stt_model`. Pro output keeps `<|speaker:N|>` and emotion cues in the
transcript so the agent can hear who said what and how (documented in the voices skill). Never
raises; returns the Hermes envelope.

## 3.5 Voice management

- Aliases: `settings.voices: {narrator: <id>, ...}` (user) plus `fish_voices action=alias` (agent,
  stored in profile-scoped plugin state). Any voice argument accepts alias or raw id.
- `fish_voices` actions: `search`, `get`, `mine`, `clone` (persistent, requires `consent: true`,
  private visibility), `delete` (requires `confirm: true`), `design` (candidates saved as WAV files the
  user can listen to; keep one by cloning it), `alias`, `credit`.

## 3.6 Streaming

Core gap L1 is closed generically: `resolve_streaming_provider` adapts a plugin `TTSProvider` that
declares `supports_pcm_stream = True`, calling `stream(text, format="pcm", sample_rate=24000)`.
Fish streams `/v1/tts` with `format: pcm, sample_rate: 24000` so audio starts as it is generated.

## 3.7 Core changes (generic, additive, upstreamable)

| Gap | Change | Consumer |
|---|---|---|
| L1 | `TTSProvider.supports_pcm_stream` (default False) + adapter in `tools/tts_streaming.py` | any plugin with chunked PCM (Fish first) |
| L2 | forward `instructions` to plugin `synthesize` (ABC already requires ignoring unknown kwargs) | any expressive plugin |
| L3 | `prepare_spoken_text` preserves `<\|token\|>` control tokens | Fish dialogue/phonemes; any model using special tokens |

The plugin also repairs `<; token; >` damage itself, so it works on Hermes builds that predate L3.

## 3.8 Defaults and fallbacks

| Situation | Behavior |
|---|---|
| No API key | Provider `is_available()` false → Hermes falls back per its own rules; tools return a setup hint (`hermes plugins settings fish-audio` / `.env`). |
| 401 / 402 / 403 | Non-retryable; message names the fix (key, top up, scope). |
| 429 / 5xx | Retry with exponential backoff (3 attempts), then error. |
| 404 / 400 unknown voice | Error names the voice/alias and suggests `fish_voices search`. |
| Dialogue on `s1` | Automatically upgrades to the configured S2 model and warns (never sends an invalid request). |
| `[cue]` on `s1` | Translated to `(tag)` when in the S1 set, otherwise removed with a warning, so it is never read aloud. |
| `(tag)` on S2 | Translated to `[tag]` when it is a known cue; other parentheses are left as text. |
| Speaker token without a voice for that index | Error before the request, listing speakers and voices. |
| Long text | Chunked by Hermes (core path) or by the tool (sentence-safe, carries the active speaker). |
| Unsupported output format | `flac` → `wav`; `ogg` → Opus in Ogg. |
| `auto_expressive` rewrite fails | Original text is spoken unchanged. |
