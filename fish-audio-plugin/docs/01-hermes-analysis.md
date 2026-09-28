# 1. Hermes plugin architecture and speech stack: analysis

Researched against `hermes-agent` `main` at `2e627917` (2026-09-28). File references are
repo-relative.

## 1.1 Marketplace (plugin catalog)

| Question | Answer |
|---|---|
| What is the marketplace? | `plugin-catalog/*.yaml`, one YAML per entry, merged by a maintainer via PR. It is the **only** discovery system for out-of-tree plugins (`plugins/AGENTS.md`). Published to `/docs/api/plugin-catalog.json` and rendered at `/docs/plugins/<name>`. |
| Entry schema | `name`, `repo` (https), `sha` (**mandatory 40-hex pin**), optional `subdir`, `description`, `maintainer`, `tier: official\|community`, `category: voice\|...`, `requires_hermes`, `docs_url`, `version`, `image`, `screenshots`, `platforms`, and a `capabilities:` block (`provides_tools`, `provides_hooks`, `provides_middleware`, `requires_env`). |
| Admission rules (`plugin-catalog/README.md`) | Owner-or-major-contributor submission; exact SHA pin; **no self-updating code**; SHA bumps are new PRs; declared capabilities must match what `register()` actually registers; `hermes plugins validate` (incl. security scan) runs in CI (`plugin-catalog-ci.yml`); dependency upper bounds expected. |
| Where may a vendor plugin live? | **Not in `plugins/`.** Root `AGENTS.md` and `plugins/AGENTS.md` (June 2026 rule): third-party product integrations ship as a **standalone plugin repo** and are listed in the catalog. So the official Fish Audio plugin is a standalone repo (`fish-audio-plugin/` here is laid out to be that repo root; the catalog's `subdir:` field also allows installing it straight from this tree). |
| Existing voice-category entries | `deepgram-voice`, `openrouter-voice`, `volcengine-voice`, `omnivoice`, `hermes-speech`, `hermes-talk`, `hermes-live-voice`, `gemini-live-bridge`, `voice-call-timeout`. All are community tier; most only register `TTSProvider`/`TranscriptionProvider` (no tools, no skills). |

## 1.2 Packaging conventions

- Directory plugin: `plugin.yaml` + `__init__.py` exposing `register(ctx)`.
- Manifest v2 (`website/docs/developer-guide/plugins/index.md`): `manifest_version: 2`, `api_version`,
  `python_dependencies` (consented, installed through PM, **upper bounds required**), `config_schema`
  (drives `plugins.entries.<id>.settings` validation and the Desktop settings form; `type: secret`
  stores the value in `.env`, never in `config.yaml`), `requires_env` (rich format with `url`/`secret`),
  `provides_tools`, `provides_hooks`, `license`, `homepage`, `tags`.
- A `pyproject.toml` beside `plugin.yaml` takes precedence over `python_dependencies`.
- Plugins **never touch core files**; missing capability means widening the generic plugin surface.
- Hermes's 14-day dependency quarantine does not apply to plugin deps, but floors + upper bounds are reviewed.

## 1.3 Install, discovery, configuration, invocation

1. **Install**: `hermes plugins install <catalog-name | git URL | path>` clones at the pinned SHA,
   records provenance in `.install-metadata.json`, prompts for `requires_env`, asks consent for
   `python_dependencies` and `capabilities`, then enables.
2. **Discover**: `PluginManager.discover_and_load()` (`hermes_cli/plugins.py`, `plugins_loader.py`)
   scans bundled `plugins/`, `$HERMES_HOME/plugins/`, `./.hermes/plugins/` (opt-in) and pip entry
   points (`hermes_agent.plugins`). Discovery runs as a side effect of importing `model_tools.py`;
   mid-run installs use `discover_plugins(force=True)` and new tools/prompt sections apply **next session**.
3. **Register** (`PluginContext`): `register_tool`, `register_hook`, `register_skill`,
   `register_system_prompt_section`, `register_cli_command`, `register_command` (slash),
   `register_tts_provider`, `register_transcription_provider`, `get_config/set_config`
   (`plugins.entries.<id>.settings.*`), `state` (profile-scoped JSON), `llm` (host LLM calls).
4. **Configure**: `tts.provider: <name>` / `stt.provider: <name>` route speech to a registered
   provider; plugin settings live under `plugins.entries.<id>.settings`; secrets in `.env`,
   read per profile with `agent.secret_scope.get_secret` (never raw `os.environ` in multi-profile).
5. **Invoke**: tools are called by the model through the registry (`model_tools.handle_function_call`);
   providers are called by the `text_to_speech` tool, gateway auto voice replies, CLI voice mode,
   the TUI/Desktop speech surfaces and the dashboard audio router.

## 1.4 How Hermes does TTS today

| Piece | Location | Notes |
|---|---|---|
| Model-facing tool | `tools/tts_tool.py` `text_to_speech(text, output_path?, speed?, instructions?, provider?)` | Toolset `tts`. Description says voice/provider are **user-configured, not model-selected**. |
| Built-in providers | `tools/tts_tool_providers.py`, `tts_tool_openai.py`, `tts_tool_local.py` | edge (default), elevenlabs, openai, deepinfra, minimax, xai, mistral, gemini, neutts, kittentts, piper. |
| Command providers | `tools/tts_command_provider.py` | `tts.providers.<name>: {type: command, command: ...}`. |
| Plugin providers | `agent/tts_provider.py` (ABC), `agent/tts_registry.py`, `tools/tts_tool_plugins.py` | `synthesize(text, output_path, voice, model, speed, format, **extra)`, optional `stream()`, `list_voices()`, `list_models()`, `warm()/release()`, `voice_compatible`. |
| Text cleanup | `tools/tts_text_normalize.py` `prepare_spoken_text` | Strips Markdown, emoji, think blocks, expands units; **table-pipe rule rewrites every `|` to `; `**. |
| Long text | `tools/tts_tool_delivery.py` | Split under a per-provider cap (plugins: `tts.<name>.max_text_length`, else 4000), synthesize sequentially, pack under platform upload limits. |
| Voice bubbles | `tts_tool.py` `_finalize_voice_delivery` | Opus/OGG for Telegram/WhatsApp/Signal/Matrix/Feishu; plugins opt in via `voice_compatible` (ffmpeg converts). |
| Low-latency streaming | `tools/tts_streaming.py` (`StreamingTTSProvider`, internal `@register`) | Consumed by CLI voice mode (`tts_tool_speaker.py`), gateway streaming consumer, dashboard `/speak-stream`. **Built-ins only**. |
| Expressive tags | `tts_tool_providers.py` | xAI `auto_speech_tags` and Gemini `audio_tags` rewrite text with the auxiliary LLM (task `tts_audio_tags`), trusting explicit tags. |

## 1.5 How Hermes does STT today

`tools/transcription_tools.py` → built-ins (local faster-whisper, local command, OpenAI, Groq,
Mistral, ElevenLabs, ...), command providers, then plugin `TranscriptionProvider` (`stt.provider`).
Used for inbound voice messages on every gateway platform, CLI/TUI push-to-talk and Desktop voice.
The plugin receives `model`, `language`, `prompt`.

## 1.6 How voices, tools, skills and instructions are represented

- **Voices**: a single string (`tts.voice` or `tts.<provider>.voice_id`), chosen by the user. There is
  no per-call voice parameter on `text_to_speech`, no voice library, no multi-speaker concept.
- **Models**: `tts.model`; `CatalogProviderBase.list_models()` feeds pickers only.
- **Tools**: JSON-schema functions in the registry, grouped into toolsets; plugin tools live in the
  plugin's own toolset and are sent on every call while enabled.
- **Skills**: `SKILL.md` with frontmatter. Plugin skills (`ctx.register_skill`) are namespaced
  `<plugin>:<skill>`, listed by `skills_list`, loaded by `skill_view`, and are **not** in the system
  prompt's `<available_skills>` index.
- **Agent instructions**: `ctx.register_system_prompt_section` adds a bounded section frozen into
  each **new** session's system prompt (cache-safe).

### How an agent learns what a plugin provides

1. Tool schemas (names, descriptions, parameter docs) are always visible while the plugin is enabled.
2. A system prompt section (frozen per session) can announce the capability and point at skills.
3. Plugin tools usually sit behind Tool Search (L7): the model discovers them from the `tool_search`
   listing (name + first 500 chars of the description) and calls them via `tool_call`.
4. Skills are pulled on demand with `skill_view("<plugin>:<skill>")`; the section must say so,
   because plugin skills are absent from `<available_skills>`.
5. Tool results can carry hints (warnings, next steps) that the agent reads in-loop.

## 1.7 Speech functionality Hermes already exposes

`text_to_speech` tool; auto voice replies on gateways (`/voice` modes); CLI/TUI voice mode with
streaming playback and barge-in; dashboard speak/speak-stream; STT for inbound voice notes and
push-to-talk; `hermes setup tts` / `hermes tools` pickers; `instructions` voice design (OpenAI only);
xAI/Gemini auxiliary tag rewriting.

## 1.8 Limitations relevant to an expressive provider (verified in code)

| # | Limitation | Where | Impact on Fish Audio |
|---|---|---|---|
| L1 | `TTSProvider.stream()` is **never called**. `resolve_streaming_provider` only instantiates the internal built-in `_REGISTRY`; plugins fall back to per-sentence `synthesize` + file round trip. | `tools/tts_streaming.py:172`, `tools/tts_tool_speaker.py:349`, `gateway/streaming_tts_consumer.py:40` | No low-latency streaming for any plugin provider in voice mode / gateway streaming / dashboard. |
| L2 | `instructions` from `text_to_speech` is dropped for plugin providers. | `tools/tts_tool_plugins.py:_dispatch_to_plugin_provider` | Model-written delivery direction never reaches Fish S2's natural-language cues. |
| L3 | `prepare_spoken_text` rewrites every `\|` to `; `. | `tools/tts_text_normalize.py:_MD_TABLE_PIPE_RE` | Destroys `<\|speaker:N\|>` (dialogue) and `<\|phoneme_start\|>`/`<\|phoneme_end\|>` (pronunciation) tokens on the core path. |
| L4 | The model cannot pick a voice or model per call; single-voice only. | `TTS_SCHEMA` | Casting, dialogue and model switching need plugin tools. |
| L5 | Provider-agnostic 4000-char cap and splitting are unaware of speaker tokens. | `tts_tool_delivery.py` | A split dialogue chunk loses its current speaker unless the provider carries it over. |
| L6 | No voice library/cloning/design concepts in core. | n/a | Belongs in the plugin (footprint ladder: plugin rung). |

| L7 | Plugin tools are **deferred by Tool Search** (`tools/tool_search.py`, `enabled: auto` activates whenever any plugin/MCP tool exists): the model sees them only in the `tool_search` listing and invokes them through `tool_describe` + `tool_call`, which validates arguments against the plugin's schema. | `model_tools._dispatch_bridge_tool` | Found by the agent-loop E2E test. The plugin's prompt section tells the model how to reach `fish_speak`; schemas stay strict and self-explanatory because many calls skip `tool_describe`. By design, not a defect. |
| L8 | `plugins.entries.<id>.settings` rejects the keys `model`, `plugins`, `security`, `settings`. | `hermes_cli/plugins_state.py` | The model setting is `tts_model`. |

L1 to L3 are generic defects in the plugin surface (they affect every expressive plugin, not only
Fish), so they are fixed in core as small additive changes; L4 to L6 are solved inside the plugin.

## 1.9 Architectural references

- `agent/tts_provider.py` ABC and `tools/tts_tool_plugins.py` dispatcher (the contract we implement).
- `tools/tts_tool_providers.py` xAI/Gemini tag rewrite (precedent for model-specific expressive markup
  and "explicit tags are trusted").
- `plugins/google_meet` (tools + skill + CLI in one plugin) and `plugins/memory/*` (`post_setup`).
- Catalog voice entries (`deepgram-voice`, `openrouter-voice`) for the provider-only pattern we extend.
- `steipete/sag`: Go CLI for ElevenLabs/60db. It has no Fish Audio backend, so it is not usable as a
  primitive; its `sag prompting` model-specific prompting guide is the precedent for our
  voice-direction skill.
