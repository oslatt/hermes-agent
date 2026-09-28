"""Test harness: a temp HERMES_HOME with this plugin installed, loaded through Hermes's real discovery,
talking to the contract-checking fake Fish server.

Runs against an importable Hermes checkout (``PYTHONPATH=<hermes-agent>``) and its venv:
``python -m pytest tests`` from the plugin root. Live Fish tests live in ``tests/live`` and are opt-in.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from fake_fish_server import FakeFishServer  # noqa: E402

API_KEY = "fish-test-key"
PLUGIN_NAME = "fish-audio"


def install_plugin(home: Path) -> Path:
    target = home / "plugins" / PLUGIN_NAME
    shutil.copytree(PLUGIN_ROOT, target, ignore=shutil.ignore_patterns("tests", "docs", "__pycache__", "*.pyc"))
    return target


def write_config(home: Path, base_url: str, settings: Dict[str, Any] | None = None, extra: str = "") -> None:
    import hermes_yaml as yaml
    config = {
        "plugins": {"enabled": [PLUGIN_NAME],
                    "entries": {PLUGIN_NAME: {"settings": {"base_url": base_url, **(settings or {})}}}},
        "tts": {"provider": PLUGIN_NAME},
        "stt": {"provider": PLUGIN_NAME},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config) + extra, encoding="utf-8")
    try:  # drop Hermes's in-process config caches so the next read sees this file
        from hermes_cli import config as hermes_config
        hermes_config._LOAD_CONFIG_CACHE.clear()
        hermes_config._RAW_CONFIG_CACHE.clear()
    except (ImportError, AttributeError):
        pass


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
    ns.configure = lambda settings=None, extra="": write_config(home, fish_server.base_url, settings, extra)
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
