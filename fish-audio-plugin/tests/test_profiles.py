"""One Hermes process serving two profiles (gateway multiplex): every Fish call must use the ACTIVE
profile's key, endpoint, model and voice aliases, A -> B -> A, with secrets failing closed."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from fake_fish_server import FakeFishServer
from harness import install_plugin, write_config


@pytest.fixture
def two_profiles(tmp_path, hermes):
    servers = {name: FakeFishServer(f"key-{name}").__enter__() for name in ("a", "b")}
    homes = {}
    for name, model in (("a", "s2.1-pro"), ("b", "s2-pro")):
        home = tmp_path / name / ".hermes"
        home.mkdir(parents=True)
        voice = next(iter(servers[name].voices))
        install_plugin(home)
        write_config(home, servers[name].base_url, {"tts_model": model, "voices": {"host": voice}})
        (home / ".env").write_text(f"FISH_API_KEY=key-{name}\n", encoding="utf-8")
        homes[name] = (home, voice, model)
    yield servers, homes
    for server in servers.values():
        server.__exit__()


@contextmanager
def _profile(home: Path):
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home_token = set_hermes_home_override(str(home))
    secret_token = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
    try:
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        yield
    finally:
        reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def test_each_profile_speaks_with_its_own_key_endpoint_model_and_voices(two_profiles, monkeypatch):
    from agent.secret_scope import set_multiplex_active
    from model_tools import handle_function_call
    servers, homes = two_profiles
    monkeypatch.delenv("FISH_API_KEY")  # no process-wide key to fall back on
    set_multiplex_active(True)
    try:
        for name in ("a", "b", "a"):
            home, voice, model = homes[name]
            with _profile(home):
                out = json.loads(handle_function_call("fish_speak", {"text": f"[warm] Hello from {name}.",
                                                                     "voice": "host"}))
            assert out["success"], (name, out)
            req = servers[name].tts_requests()[-1]
            assert (req.model, req.body["reference_id"]) == (model, voice)
            assert req.body["text"] == f"[warm] Hello from {name}."
        assert len(servers["a"].tts_requests()) == 2 and len(servers["b"].tts_requests()) == 1
    finally:
        set_multiplex_active(False)
