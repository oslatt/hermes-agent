"""Test harness: a temp HERMES_HOME with this plugin installed, loaded through Hermes's real discovery,
talking to the contract-checking fake Fish server.

Runs against an importable Hermes checkout (``PYTHONPATH=<hermes-agent>``) and its venv:
``python -m pytest tests`` from the plugin root. Live Fish tests live in ``tests/live`` and are opt-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fake_fish_server import FakeFishServer  # noqa: E402
from harness import API_KEY, PLUGIN_NAME, install_plugin, write_config  # noqa: E402,F401


def pytest_addoption(parser):
    group = parser.getgroup("fish-audio live")
    group.addoption("--live", action="store_true", help="run tests/live against the real Fish Audio API")
    group.addoption("--live-model", default="s2.1-pro-free", help="TTS model for live scenarios")
    group.addoption("--live-design", action="store_true", help="also run billed voice-design scenarios")
    group.addoption("--live-against-fake", action="store_true",
                    help="self-test the live harness against the fake server (echo listener, no network)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live Fish Audio test; pass --live (needs FISH_API_KEY)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def fish_server():
    with FakeFishServer(API_KEY) as server:
        yield server


@pytest.fixture(scope="session")
def hermes(tmp_path_factory, fish_server):
    """Session-wide Hermes home with the plugin discovered; yields a namespace for tests."""
    root = tmp_path_factory.mktemp("hermes-e2e")
    home = root / ".hermes"
    home.mkdir()
    mp = pytest.MonkeyPatch()
    mp.setenv("HERMES_HOME", str(home))
    mp.setenv("HOME", str(root))
    mp.setattr(Path, "home", staticmethod(lambda: root))
    mp.setenv(API_KEY_ENV := "FISH_API_KEY", API_KEY)
    for var in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "HERMES_SESSION_PLATFORM"):
        mp.delenv(var, raising=False)
    install_plugin(home)
    write_config(home, fish_server.base_url)
    (home / ".env").write_text(f"{API_KEY_ENV}={API_KEY}\n", encoding="utf-8")

    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins(force=True)
    manager = get_plugin_manager()
    loaded = {p["name"]: p for p in manager.list_plugins()}
    package = next((m for name, m in sys.modules.items()
                    if name.startswith("hermes_plugins.") and name.count(".") == 1
                    and str(getattr(m, "__file__", "")).startswith(str(home / "plugins" / PLUGIN_NAME))), None)

    class NS:
        pass

    ns = NS()
    ns.home, ns.root, ns.server, ns.manager, ns.plugins, ns.package = home, root, fish_server, manager, loaded, package
    ns.configure = lambda settings=None, extra="", tts=None: write_config(home, fish_server.base_url, settings, extra, tts)
    yield ns
    mp.undo()


@pytest.fixture
def fish(hermes):
    """Per-test view: fresh request log, default settings restored afterwards."""
    hermes.server.requests.clear()
    hermes.server.faults.clear()
    yield hermes
    hermes.configure()
    hermes.server.requests.clear()
    hermes.server.faults.clear()


@pytest.fixture
def plugin(hermes):
    """The plugin package exactly as Hermes imported it."""
    assert hermes.package is not None, f"plugin not imported; loaded plugins: {sorted(hermes.plugins)}"
    return hermes.package
