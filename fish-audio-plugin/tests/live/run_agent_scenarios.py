"""Score how a real Hermes agent uses Fish Audio, in loops.

    # the user's own model (config.yaml + .env copied from their home), fake Fish server (no Fish cost):
    python tests/live/run_agent_scenarios.py --from-home ~/.hermes --loops 3
    # same, but real Fish Audio synthesis (needs FISH_API_KEY):
    python tests/live/run_agent_scenarios.py --from-home ~/.hermes --real-fish
    # harness self-test: an ideal scripted agent through Hermes's FakeLLMServer (no network):
    python tests/live/run_agent_scenarios.py --reference

Each run is a fresh temp HERMES_HOME with this plugin installed and ``hermes chat -q <prompt>`` in a
subprocess. The score reads what actually reached Fish. Results: a table on stdout plus JSON (``--out``).
Iterate: read failures, adjust skills/prompt/tool text, run again.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import hermes_yaml as yaml  # noqa: E402
from harness import API_KEY, PLUGIN_NAME, install_plugin  # noqa: E402
from fake_fish_server import FakeFishServer  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402


def _plugin_config(base_url: str, voices: dict) -> dict:
    return {"plugins": {"enabled": [PLUGIN_NAME], "entries": {PLUGIN_NAME: {"settings": {
        "base_url": base_url, "voices": voices}}}}, "tts": {"provider": PLUGIN_NAME}}


def _merge(base: dict, overlay: dict) -> dict:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        elif key == "enabled" and isinstance(base.get(key), list):
            base[key] = sorted(set(base[key]) | set(value))
        else:
            base[key] = value
    return base


def _chat(root: Path, prompt: str, timeout: float) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME" and not k.endswith(("_API_KEY", "_TOKEN"))}
    env.update(HOME=str(root), HERMES_HOME=str(root / ".hermes"), NO_COLOR="1", TERM="dumb",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", HERMES_STATE_DB_GUARD_BYPASS="1")
    try:
        return subprocess.run([sys.executable, "-m", "hermes_cli.main", "chat", "-q", prompt], cwd=str(root), env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(exc.cmd, 124, exc.stdout or "", f"timeout after {timeout}s")


def _home(args, root: Path, fish_url: str, fish_key: str, voices: dict, llm_url: str | None) -> None:
    home = root / ".hermes"
    home.mkdir(parents=True)
    if llm_url:
        from tests.fakes.fake_llm_provider import write_hermes_home
        write_hermes_home(home, llm_url, extra_config=yaml.safe_dump(_plugin_config(fish_url, voices)))
    else:
        source = Path(args.from_home).expanduser()
        config = yaml.safe_load((source / "config.yaml").read_text(encoding="utf-8")) or {}
        (home / "config.yaml").write_text(yaml.safe_dump(_merge(config, _plugin_config(fish_url, voices))), encoding="utf-8")
        if (source / ".env").exists():
            shutil.copy(source / ".env", home / ".env")
    with open(home / ".env", "a", encoding="utf-8") as fh:
        fh.write(f"\nFISH_API_KEY={fish_key}\n")
    install_plugin(home)


def _reference_script(scenario):
    from tests.fakes.fake_llm_provider import Text, ToolCall
    turns = [ToolCall("skill_view", {"name": "fish-audio:voice-direction"})]
    turns += [ToolCall("tool_call", {"calls": [{"name": tool, "arguments": call}]}) for tool, call in scenario.reference]
    return turns + [Text("Done. (voice not found, so I searched the library.)")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-home", help="HERMES_HOME whose model config and .env to use")
    source.add_argument("--reference", action="store_true", help="replay the ideal scripted agent (self-test)")
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument("--only", nargs="*", help="scenario names")
    parser.add_argument("--real-fish", action="store_true", help="synthesize with the real Fish API")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", help="write JSON results here")
    args = parser.parse_args()

    chosen = [s for s in SCENARIOS if not args.only or s.name in args.only]
    results = defaultdict(list)
    with FakeFishServer(API_KEY) as fish:
        library = {v["title"]: vid for vid, v in fish.voices.items()}
        voices = {"narrator": library["Warm Narrator"], "bright": library["Bright Presenter"],
                  "gravel": library["Gravel Captain"]}
        fish_url, fish_key = fish.base_url, API_KEY
        if args.real_fish:
            fish_url, fish_key = "https://api.fish.audio", os.environ["FISH_API_KEY"]
        for loop in range(args.loops):
            for scenario in chosen:
                fish.requests.clear()
                with tempfile.TemporaryDirectory(prefix=f"fish-{scenario.name}-") as tmp:
                    root = Path(tmp)
                    if args.reference:
                        from tests.fakes.fake_llm_provider import FakeLLMServer, Text
                        with FakeLLMServer(_reference_script(scenario), aux=lambda _r: Text("t")) as llm:
                            _home(args, root, fish_url, fish_key, voices, llm.base_url)
                            proc = _chat(root, scenario.prompt, args.timeout)
                    else:
                        _home(args, root, fish_url, fish_key, voices, None)
                        proc = _chat(root, scenario.prompt, args.timeout)
                tts = [r for r in fish.requests if r.path.startswith("/v1/tts")]
                passed, detail = scenario.check(tts, list(fish.requests), proc.stdout, voices)
                if proc.returncode != 0:
                    passed, detail = False, f"hermes exited {proc.returncode}: {proc.stderr.strip()[-200:]}"
                results[scenario.name].append({"loop": loop, "passed": passed, "detail": detail,
                                               "texts": [r.body.get("text") for r in tts if isinstance(r.body, dict)]})
                print(f"[{loop}] {scenario.name:24s} {'PASS' if passed else 'FAIL'}  {detail}", flush=True)
    print("\n| scenario | pass rate | last detail |\n|---|---|---|")
    for name, runs in results.items():
        rate = sum(r["passed"] for r in runs) / len(runs)
        print(f"| {name} | {rate:.0%} ({len(runs)} runs) | {runs[-1]['detail'][:80]} |")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if all(r["passed"] for runs in results.values() for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
