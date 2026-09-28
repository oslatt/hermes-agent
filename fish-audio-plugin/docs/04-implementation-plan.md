# 4. Implementation plan

Milestones run in order; tasks inside a milestone can run in parallel. Each task lists
**Objective · Files · Depends on · Implementation · Test criteria · Done when**.
Status reflects this branch (✅ done, 🔒 needs network access / a Fish key, ⏭ follow-up).

## M0: Core Hermes surface (generic, lands in `hermes-agent`)

**T0.1 ✅ Forward `instructions` to plugin TTS providers (L2)**
- Files: `tools/tts_tool_plugins.py`, `tools/tts_tool.py`. Depends: none.
- Implementation: pass `instructions=` into `_dispatch_to_plugin_provider` and on to `synthesize(**extra)` only when set.
- Test: a registered fake provider receives `instructions` from `text_to_speech_tool(..., instructions=...)`; red on base.
- Done: test green; existing TTS tests green.

**T0.2 ✅ Plugin PCM streaming adapter (L1)**
- Files: `agent/tts_provider.py` (`supports_pcm_stream` property, stream docstring), `tools/tts_streaming.py`.
- Implementation: `_try_instantiate` falls back to a registered plugin provider that opts in, wrapped in a `StreamingTTSProvider` that calls `stream(text, voice, model, format="pcm", sample_rate=24000)`. Built-ins keep precedence; plugins without the opt-in keep the per-sentence path.
- Test: opted-in plugin resolves to a streamer yielding its PCM; non-opted plugin resolves to None.
- Done: voice mode / gateway / dashboard reach plugin `stream()`.

**T0.3 ✅ Control-token-safe spoken-text cleanup (L3)**
- Files: `tools/tts_text_normalize.py`.
- Implementation: protect `<|name|>` / `<|name:arg|>` tokens across the pipeline, restore afterwards.
- Test: `<|speaker:0|>` and `<|phoneme_start|>…<|phoneme_end|>` survive `prepare_spoken_text` while table pipes still become pauses.

## M1: Marketplace compatibility

**T1.1 ✅ Manifest + packaging** · `plugin.yaml`, `__init__.py`, `README.md`, `LICENSE` · Depends: none ·
Manifest v2 with `provides_tools`, `config_schema`, `requires_env` (rich), `python_dependencies`
with upper bounds · Test: loads through real `PluginManager` discovery from a temp `HERMES_HOME` ·
Done: tools, providers, skills, prompt section registered.

**T1.2 🔒 Catalog entry** · `plugin-catalog/fish-audio.yaml` (draft in `docs/catalog-entry.yaml`) ·
Depends: T1.1 published at a SHA in Fish's repo · `tier: official`, `category: voice`, capabilities
matching registration · Test: `hermes plugins validate` at the pinned SHA · Done: entry merged by a maintainer.

## M2: Fish Audio API client

**T2.1 ✅ HTTP client** · `fish_audio/client.py` · Implementation: TTS to file + chunked iterator, SSE
timestamps, ASR multipart, `/model` CRUD, voice design, credit; JSON by default, MessagePack only for
inline references; retry 429/5xx; typed errors · Test: mock server contract tests for every endpoint,
error mapping, retry · Done: all endpoints exercised.

**T2.2 ✅ Model table** · `fish_audio/models.py` · Test: every model has syntax + multi-speaker flags;
unknown ids pass through with a warning.

## M3: TTS integration

**T3.1 ✅ `FishTTSProvider.synthesize`** · `fish_audio/providers.py` · Depends: T2.1, T4.1 ·
Format mapping, voice alias resolution, settings defaults, `instructions` → cue, token repair ·
Test: `text_to_speech` via the registry writes audio and the mock sees the expected request.

**T3.2 ✅ `auto_expressive`** · host LLM rewrite of untagged text (off by default) · Test: rewrite applied
only when enabled and no cues present; failure falls back to original text.

## M4: Advanced controls (markup)

**T4.1 ✅ Cue compiler** · `fish_audio/markup.py` · S2↔S1 translation, placement lint, conflict warnings,
cue count per sentence · Test: property-style table of inputs → outputs + warnings.

**T4.2 ✅ Dialogue** · `lines` → speaker tokens + voice array; carry-over across chunks; validation ·
Test: tokens/voices align; S1 upgraded with a warning.

**T4.3 ✅ Pronunciation** · inline dictionary from `pronunciations`, managed dictionaries from settings,
phoneme tags untouched · Test: request body carries dictionary, ≤3 dictionaries enforced.

## M5: STT integration

**T5.1 ✅ `FishTranscriptionProvider`** · model header, language hint, timestamps off, envelope ·
Test: `transcribe_audio` with `stt.provider: fish-audio` returns the mock transcript; errors → envelope.

## M6: Voice management

**T6.1 ✅ `fish_voices`** · search/get/mine/clone/delete/design/alias/credit · Test: each action against
the mock; consent/confirm guards; design writes playable WAV files.

## M7: Streaming

**T7.1 ✅ `FishTTSProvider.stream`** · chunked `/v1/tts` with `format: pcm` · Depends: T0.2 · Test:
`resolve_streaming_provider` returns the adapter and yields PCM bytes in order from the mock.

## M8: Skills and instructions

**T8.1 ✅ System prompt section** · `fish_audio/prompt.py` · bounded, frozen per session, lists model
syntax + aliases + skill pointers · Test: section present in the real agent's system prompt.

**T8.2 ✅ Skills** · `skills/{voice-direction,dialogue,pronunciation,voices}/SKILL.md` · Test: resolvable
through `skill_view("fish-audio:<name>")` in a real session.

## M9: Configuration and authentication

**T9.1 ✅ Settings + key** · `config_schema`, `fish_audio/settings.py` · `FISH_API_KEY` via
`get_secret` at call time (profile-aware) · Test: key read per call; missing key → availability false.

## M10: Error handling

**T10.1 ✅ Error envelopes** · every tool returns `{success:false, error, hint}`; provider raises with an
actionable message · Test: 401/402/404/422/429/500 mapping and retry counts.

## M11: Documentation

**T11.1 ✅ README + usage examples + capability matrix** · `README.md`, `docs/05-capability-matrix.md`.

## M12: Automated tests

**T12.1 ✅ Unit + contract** · `tests/test_markup.py`, `tests/test_speak_tool.py`, `tests/test_voices_tool.py`,
`tests/test_hermes_speech_paths.py`, `tests/test_profiles.py` (A→B→A multiplex), `tests/test_scenario_checks.py`,
with `tests/fake_fish_server.py` (a loopback server that validates requests against the documented
contract and records them).

## M13: End-to-end Hermes tests

**T13.1 ✅ In-process E2E** · real discovery from a temp `HERMES_HOME`, real `text_to_speech`,
`fish_speak`, `fish_voices`, STT, streaming adapter.

**T13.2 ✅ Agent-loop E2E** · `hermes chat -q` subprocess against `FakeLLMServer` scripted tool calls
+ the fake Fish server: tool schemas offered, system prompt section present, skills load, audio files
produced, requests correct.

**T13.3 🔒 Live scenario suite** (built; harness self-tested with `--live-against-fake`) · `tests/live/` gated on `FISH_API_KEY`: neutral narration, emotional
delivery, dialogue, pacing/intensity, pronunciation, conversational replies, long-form, streaming,
model switching, errors; round-trips audio through Fish ASR to check the words; writes a report.

**T13.4 🔒 Real-model behavior loop** (built; runner self-tested with `--reference`) · `tests/live/run_agent_scenarios.py` + `scenarios.py`: prompts a real Hermes model
(user's configured provider) with the scenario prompts against the fake Fish server and scores whether
the model chose the right tool, cues, voices and syntax. Run in loops; fix skills/prompt text; repeat.
