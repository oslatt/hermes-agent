"""Live harness: a temp HERMES_HOME with the plugin pointed at the real Fish Audio API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import PLUGIN_NAME, install_plugin, write_config  # noqa: E402


@pytest.fixture(scope="session")
def live_hermes(tmp_path_factory, request):
    fake = request.config.getoption("--live-against-fake")
    if fake:
        server = request.getfixturevalue("fish_server")
        server.echo_asr = True
        os.environ["FISH_API_KEY"] = server.api_key
    key = os.environ.get("FISH_API_KEY", "").strip()
    if not key:
        pytest.skip("FISH_API_KEY is not set")
    base_url = server.base_url if fake else "https://api.fish.audio"
    root = tmp_path_factory.mktemp("hermes-live")
    home = root / ".hermes"
    home.mkdir()
    mp = pytest.MonkeyPatch()
    mp.setenv("HERMES_HOME", str(home))
    mp.setattr(Path, "home", staticmethod(lambda: root))
    model = request.config.getoption("--live-model")
    install_plugin(home)
    base = {"tts_model": model}
    write_config(home, base_url, base)

    from hermes_cli.plugins import discover_plugins
    discover_plugins(force=True)
    from agent.tts_registry import get_provider
    provider = get_provider(PLUGIN_NAME)
    from importlib import import_module
    settings_mod = import_module(type(provider).__module__.rsplit(".", 1)[0] + ".settings")
    client = settings_mod.Settings.load(provider.ctx).client()
    try:
        voices = client.list_voices({"page_size": 10, "licensed": "true", "language": "en"}).get("items", [])
    finally:
        client.close()
    if len(voices) < 2:
        pytest.skip("could not find two licensed English library voices")

    class Live:
        pass

    live = Live()
    live.home, live.model, live.voice, live.voice2 = home, model, voices[0]["_id"], voices[1]["_id"]
    live.real = not fake
    live.configure = lambda **extra: write_config(home, base_url, {**base, **extra})
    yield live
    mp.undo()
