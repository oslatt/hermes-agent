"""A real ``hermes chat -q`` process: scripted model turns (Hermes's FakeLLMServer) drive the plugin's
knowledge layer and tools end to end, and the fake Fish server records what was synthesized.

Proves what unit tests cannot: the tools reach the model's tool list, the system prompt section is in
the real prompt, ``skill_view`` returns the voice library to the model, ``fish_speak`` output flows
back as a tool result, and the audio file exists on disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import API_KEY, PLUGIN_NAME, install_plugin

fake_llm = pytest.importorskip("tests.fakes.fake_llm_provider", reason="needs the Hermes checkout's test fakes")


def _run_chat(root: Path, prompt: str, timeout: float = 180.0) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(("_API_KEY", "_TOKEN")) and k not in ("HERMES_HOME", "HTTP_PROXY", "HTTPS_PROXY",
                                                                 "http_proxy", "https_proxy", "ALL_PROXY")}
    env.update(HOME=str(root), HERMES_HOME=str(root / ".hermes"), NO_COLOR="1", TERM="dumb",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", HERMES_STATE_DB_GUARD_BYPASS="1",
               XDG_STATE_HOME=str(root / ".local" / "state"))
    return subprocess.run([sys.executable, "-m", "hermes_cli.main", "chat", "-q", prompt], cwd=str(root), env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def agent_home(tmp_path, fish_server):
    home = tmp_path / ".hermes"
    narrator = next(vid for vid, v in fish_server.voices.items() if v["title"] == "Warm Narrator")
    plugin_cfg = {"plugins": {"enabled": [PLUGIN_NAME], "entries": {PLUGIN_NAME: {"settings": {
        "base_url": fish_server.base_url, "voices": {"narrator": narrator}}}}},
        "tts": {"provider": PLUGIN_NAME}}
    import hermes_yaml as yaml

    def start(llm_url: str) -> Path:
        fake_llm.write_hermes_home(home, llm_url, extra_config=yaml.safe_dump(plugin_cfg))
        with open(home / ".env", "a", encoding="utf-8") as fh:
            fh.write(f"FISH_API_KEY={API_KEY}\n")
        install_plugin(home)
        return tmp_path

    fish_server.requests.clear()
    return start, narrator


def _tool_message(request: dict) -> dict:
    return next(m for m in reversed(request["messages"]) if m.get("role") == "tool")


def _bridged(name: str, args: dict) -> "fake_llm.ToolCall":
    """Hermes defers plugin tools behind tool_search; the model invokes them through tool_call."""
    return fake_llm.ToolCall("tool_call", {"calls": [{"name": name, "arguments": args}]})


def _payload(request: dict) -> dict:
    """tool_call re-dispatches as the real tool, so the tool message is the plugin's own JSON."""
    return json.loads(_tool_message(request)["content"])


def _visible_tools(request: dict) -> dict:
    return {t["function"]["name"]: t["function"] for t in request["tools"]}


def test_agent_loads_the_voice_library_then_performs_with_fish(agent_home, fish_server):
    start, narrator = agent_home
    script = "[mysterious][whispering] The house stood silent. [break] [scared] Is anyone there?"
    turns = [fake_llm.ToolCall("skill_view", {"name": "fish-audio:voice-direction"}),
             fake_llm.ToolCall("tool_describe", {"names": ["fish_speak"]}),
             _bridged("fish_speak", {"text": script, "voice": "narrator", "temperature": 0.8}),
             fake_llm.Text("Here is your spooky line.")]
    with fake_llm.FakeLLMServer(turns, aux=lambda _req: fake_llm.Text("Spooky line")) as llm:
        root = start(llm.base_url)
        proc = _run_chat(root, "Read me one spooky line in a whisper.")
        assert proc.returncode == 0, proc.stderr[-3000:]
        first, second, third, fourth = llm.main_requests()[:4]

    tools = _visible_tools(first)
    assert "text_to_speech" in tools and "skill_view" in tools
    listing = json.dumps(tools.get("tool_search", {})) + json.dumps(tools.get("fish_speak", {}))
    assert "fish_speak" in listing and "fish_voices" in listing  # discoverable directly or via the bridge
    system = first["messages"][0]["content"]
    system = system if isinstance(system, str) else json.dumps(system)
    assert "## Fish Audio speech" in system and "narrator" in system

    skill_result = _tool_message(second)["content"]
    assert "Voice Direction" in skill_result and "## Procedure" in skill_result
    assert "[emphasis]" in _tool_message(third)["content"]  # full fish_speak schema reached the model

    spoken = _payload(fourth)
    assert spoken["success"] and Path(spoken["file_path"]).is_file()
    assert spoken["media_tag"].startswith("MEDIA:")
    req = fish_server.tts_requests()[-1]
    assert req.body["text"] == script and req.body["reference_id"] == narrator and req.body["temperature"] == 0.8
    assert "Here is your spooky line." in proc.stdout


def test_agent_recovers_from_an_unknown_voice_by_searching_and_saving_one(agent_home, fish_server):
    start, _ = agent_home
    captain = next(vid for vid, v in fish_server.voices.items() if v["title"] == "Gravel Captain")
    turns = [_bridged("fish_speak", {"text": "Ahoy!", "voice": "pirate"}),
             _bridged("fish_voices", {"action": "search", "tags": ["character"]}),
             _bridged("fish_voices", {"action": "alias", "voice_id": captain, "alias": "pirate"}),
             _bridged("fish_speak", {"text": "[laughing] Ahoy!", "voice": "pirate"}),
             fake_llm.Text("Done.")]
    with fake_llm.FakeLLMServer(turns, aux=lambda _req: fake_llm.Text("Pirate")) as llm:
        root = start(llm.base_url)
        proc = _run_chat(root, "Say ahoy like a pirate.")
        assert proc.returncode == 0, proc.stderr[-3000:]
        requests = llm.main_requests()

    failed = _payload(requests[1])
    assert not failed["success"] and "fish_voices" in failed["error"]
    searched = _payload(requests[2])
    assert searched["voices"][0]["id"] == captain
    final = _payload(requests[4])
    assert final["success"] and fish_server.tts_requests()[-1].body["reference_id"] == captain
