# Fish Audio for Hermes Agent

Official [Fish Audio](https://fish.audio) plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
It makes Fish Audio's expressive speech models a voice actor the agent can direct: emotion and tone
cues, character dialogue with several voices, pacing, pronunciation, cloned and designed voices,
streaming playback, and speech-to-text with speakers and emotion cues.

## Install

```bash
hermes plugins install fish-audio          # from the plugin catalog (once listed)
# or from source:
hermes plugins install https://github.com/<org>/hermes-fish-audio --enable
```

The installer asks for `FISH_API_KEY` ([get one](https://fish.audio/app/api-keys)) and consents to
one dependency (`msgpack`, used only for instant cloning from local audio). Then route Hermes speech
through Fish:

```yaml
# ~/.hermes/config.yaml
tts:
  provider: fish-audio          # text_to_speech, voice replies, voice mode, dashboard
stt:
  provider: fish-audio          # inbound voice notes, push-to-talk
plugins:
  entries:
    fish-audio:
      settings:
        tts_model: s2.1-pro     # or s2.1-pro-free for development ($0)
        voice: narrator         # default voice (alias or 32-hex id)
        voices:                 # aliases the agent can use by name
          narrator: 802e3bc2b27e49c2995d23ef70e6ac89
```

New tools, prompt text and skills apply from the next session.

## What the agent gets

| Surface | What it does |
|---|---|
| `fish_speak` tool | Performs a script: `[cue]` delivery markup, `lines` + `cast` for dialogue, `voice`, `model`, `direction`, `speed`, `volume`, `temperature`, `top_p`, `latency`, `pronunciations`, `reference_audio` (instant clone), `timestamps`, `format`, `output_path`. Returns a `MEDIA:` path Hermes delivers on every platform (voice bubble on Telegram/WhatsApp/Signal/Matrix/Feishu). |
| `fish_voices` tool | `search`, `get`, `mine`, `alias`, `clone` (needs `consent: true`), `design`, `delete` (needs `confirm: true`), `credit`. |
| TTS provider | `text_to_speech` and automatic voice replies speak through Fish; `instructions` become a delivery cue; optional `auto_expressive` adds cues to plain replies. |
| Streaming | Voice mode, gateway streaming and dashboard speak-stream play Fish PCM as it is generated. |
| STT provider | `transcribe-1`, or `transcribe-1-pro` for `<\|speaker:N\|>` turns and emotion cues. |
| Knowledge | A short system-prompt section and four skills: `fish-audio:voice-direction`, `:dialogue`, `:pronunciation`, `:voices`. |

Hermes loads plugin tools on demand (Tool Search): the model finds `fish_speak` in the
`tool_search` listing and calls it through `tool_call`. The prompt section tells it so.

## Examples

Emotional delivery:

```json
{"text": "[excited] We shipped it! [laughing] Ha, ha! [calm] Release notes are in your inbox."}
```

Dialogue with two voices:

```json
{"lines": [{"speaker": "Mara", "text": "[nervous] Is it supposed to shake like this?"},
           {"speaker": "Pilot", "text": "[calm] Completely normal. Buckle up."}],
 "cast": {"Mara": "bright", "Pilot": "narrator"}}
```

Pacing and direction:

```json
{"text": "Breathe in... [break] and let it go.", "direction": "soft, unhurried", "speed": 0.8}
```

Pronunciation:

```json
{"text": "Our SQL runs on Kubernetes.", "pronunciations": {"SQL": "EH1 S K Y UW1 EH1 L"}}
```

Legacy model: the same `[cue]` script works on `s1`; the plugin converts it to `(tags)`, removes cues
`s1` cannot perform, and reports what changed in `warnings`.

## Settings

All under `plugins.entries.fish-audio.settings` (also editable in the Desktop Plugins tab):

| Key | Default | Meaning |
|---|---|---|
| `tts_model` | `s2.1-pro` | `s2.1-pro`, `s2.1-pro-free`, `s2-pro`, `drama-3-preview`, `s1` |
| `voice` / `voices` | Fish default / `{}` | default voice; alias map |
| `format` | `mp3` | `fish_speak` default (`opus` automatically on voice-note platforms) |
| `latency` / `stream_latency` | `normal` / `balanced` | quality vs time to first audio |
| `temperature`, `top_p`, `speed`, `volume` | Fish defaults | request defaults |
| `normalize` | `true` | expand numbers and dates |
| `pronunciations` | `{}` | word -> phonemes on every request |
| `pronunciation_dictionaries` | `[]` | managed `[{id, version}]` from the Fish web app |
| `auto_expressive` | `false` | host model adds cues to untagged speech (one extra LLM call per reply) |
| `stt_model` | `transcribe-1` | `transcribe-1-pro` for speakers and emotion cues |
| `base_url` | `https://api.fish.audio` | self-hosted or proxy endpoint |
| `timeout_seconds`, `max_chars_per_request` | `120`, `3000` | per request; longer scripts split at sentences |
| `advanced` | `{}` | `repetition_penalty`, `chunk_length`, `min_chunk_length`, `max_new_tokens`, `condition_on_previous_chunks`, `early_stop_threshold`, `features`, bitrates, `sample_rate` |

## Tests

```bash
# against a Hermes checkout and its venv
PYTHONPATH=/path/to/hermes-agent /path/to/hermes-agent/.venv/bin/python -m pytest tests
# live Fish Audio scenario matrix (FISH_API_KEY; s2.1-pro-free by default)
... -m pytest tests/live --live [--live-model s2.1-pro] [--live-design]
# harness self-test without network
... -m pytest tests/live --live --live-against-fake
# how a real Hermes model directs Fish, in loops (your model config, fake Fish server)
... tests/live/run_agent_scenarios.py --from-home ~/.hermes --loops 3 [--real-fish]
```

`tests/fake_fish_server.py` enforces Fish's documented request contract (model header, multi-speaker
rules, MessagePack references, ranges, dictionary limits) and records every request.

## Docs

`docs/01-hermes-analysis.md`, `02-fish-audio-capabilities.md`, `03-architecture.md`,
`04-implementation-plan.md`, `05-capability-matrix.md`, `06-test-report.md`.

## License

MIT
