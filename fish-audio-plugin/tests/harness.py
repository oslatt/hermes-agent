"""Shared test helpers: install this plugin into a HERMES_HOME and write its config."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
API_KEY = "fish-test-key"
PLUGIN_NAME = "fish-audio"


def install_plugin(home: Path) -> Path:
    target = home / "plugins" / PLUGIN_NAME
    shutil.copytree(PLUGIN_ROOT, target, ignore=shutil.ignore_patterns("tests", "docs", "__pycache__", "*.pyc"))
    return target


def write_config(home: Path, base_url: str, settings: Dict[str, Any] | None = None, extra: str = "",
                 tts: Dict[str, Any] | None = None) -> None:
    import hermes_yaml as yaml
    config = {
        "plugins": {"enabled": [PLUGIN_NAME],
                    "entries": {PLUGIN_NAME: {"settings": {"base_url": base_url, **(settings or {})}}}},
        "tts": {"provider": PLUGIN_NAME, **(tts or {})},
        "stt": {"provider": PLUGIN_NAME},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config) + extra, encoding="utf-8")
    try:  # drop Hermes's in-process config caches so the next read sees this file
        from hermes_cli import config as hermes_config
        hermes_config._LOAD_CONFIG_CACHE.clear()
        hermes_config._RAW_CONFIG_CACHE.clear()
    except (ImportError, AttributeError):
        pass
