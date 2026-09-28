# 6. Test report

Run on 2026-09-28 in a cloud container, Hermes `main` at `2e627917` plus the core commit
"feat(tts): plugin providers get instructions, PCM streaming, and intact control tokens".

## What ran here

| Suite | What it proves | Result |
|---|---|---|
| Hermes core: `tests/tools/test_tts_*`, `test_voice*`, `test_transcription*`, `tests/agent/test_tts*`, gateway/CLI voice tests, `tests/plugins/` (via `scripts/run_tests.sh`) | core fixes L1-L3 regress nothing | 2,423 passed, 42 skipped, 0 failed |
| New core invariant tests (red on base, green after) | `instructions` reach plugins; opted-in plugin `stream()` feeds the PCM consumers; control tokens survive `prepare_spoken_text` | 4 passed |
| `hermes plugins validate fish-audio-plugin` (the catalog CI gate) | manifest, config schema, loadability, declared tools == registered, no collisions, security scan | all checks passed |
| Plugin suite `tests/` (fake Fish server, real Hermes discovery and dispatch) | markup compiler, `fish_speak`, `fish_voices`, `text_to_speech`, STT, streaming adapter, picker row, prompt section, skills, errors/retries, exfiltration guard, auto-expressive, A→B→A multiplex profiles, scorer rejection cases | 65 passed (13 live tests skipped by default) |
| Agent loop (`tests/test_agent_loop.py`, real `hermes chat -q` subprocess + Hermes FakeLLMServer) | tools discoverable through Tool Search, prompt section in the real system prompt, `skill_view` returns the voice library, `tool_describe` returns the schema, `tool_call` performs, audio on disk; recovery from an unknown voice; auto-expressive through the host model | 3 passed |
| Live harness self-test (`tests/live --live --live-against-fake`) | the live scenario code is correct (echo listener, speed-scaled audio) | 12 passed |
| Behavior scenarios with the reference agent (`run_agent_scenarios.py --reference`) | the runner and scorers work end to end in real Hermes processes | 12/12 scenarios, 2 loops |
| Repetition | flakiness | 5 consecutive loops of the plugin suite and live self-test: identical results |

## Failures found by testing and fixed

| Found by | Problem | Fix |
|---|---|---|
| Core test (red on base) | plugin `stream()` never called by any consumer | `supports_pcm_stream` + adapter (L1) |
| Core test | `instructions` dropped for plugins | forwarded (L2) |
| Core test | `<\|speaker:0\|>` became `<; speaker:0; >`, `phoneme_start` lost its underscore | control-token protection (L3) + plugin-side repair for older Hermes |
| Plugin E2E | `plugins.entries.*.settings.model` is a reserved key | setting renamed `tts_model` |
| Plugin E2E | plugin root modules (`tools.py`) shadowed Hermes's `tools` package when run from the repo root | internals moved to `fish_audio/` |
| Plugin E2E | Fish's `self` query parameter collided with Python `self` | params passed as a mapping |
| Agent-loop E2E | plugin tools absent from the model's tool list | by design: Tool Search defers plugin tools; prompt section now explains `tool_describe` / `tool_call`, tests follow that path |
| Scorer rejection test | long-form scorer accepted a cue on every sentence | threshold tightened to ≤0.6 cues/sentence |
| Review | `reference_audio` / `clone` could upload any local file | Hermes read guard + audio-extension allowlist, tested with `.env` |
| Review | a leftover `tts.voice` from another engine broke Fish speech | provider path falls back to the Fish default voice with a warning |

## Not run here, and why

The container's egress policy blocks `api.fish.audio` and `docs.fish.audio`, and the session has no
LLM credentials. So:

- **Live Fish audio** (`tests/live --live`): scenario matrix for neutral narration, emotional
  delivery, whisper/laughter effects, pacing (duration ratio), pronunciation (phonemes +
  dictionary, checked by ASR), two-voice dialogue (checked by `transcribe-1-pro` speaker turns),
  long-form splitting, streaming time-to-first-audio, model switching (`s1`, `s2-pro`), timestamps,
  error envelopes, optional billed voice design. Built and self-tested; needs a run with a key.
- **Real-model behavior loops** (`run_agent_scenarios.py --from-home ~/.hermes --loops 3`): 12
  scenarios scoring whether a real model picks the right tool, cues, voices, model and
  pronunciation mechanism. Built and self-tested; needs a run with the user's model.
- **`hermes plugins install` from Git**: blocked because PM downloads a managed Python from GitHub.
  Discovery, enablement and `hermes plugins validate` were exercised instead.

Commands:

```bash
cd fish-audio-plugin
PY=/path/to/hermes-agent/.venv/bin/python; export PYTHONPATH=/path/to/hermes-agent
FISH_API_KEY=... $PY -m pytest tests/live --live                      # s2.1-pro-free, $0
FISH_API_KEY=... $PY -m pytest tests/live --live --live-model s2.1-pro
$PY tests/live/run_agent_scenarios.py --from-home ~/.hermes --loops 3 --out results.json
```

Iterate on failures by adjusting `skills/*/SKILL.md`, `fish_audio/prompt.py` and tool descriptions,
then re-run the same loops and compare `results.json` / `tests/live/out/report.md`.
