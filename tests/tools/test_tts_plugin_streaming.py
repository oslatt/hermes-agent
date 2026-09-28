"""Plugin ``TTSProvider.stream()`` reaches the chunked-PCM streaming consumers (voice mode, gateway
streaming, dashboard speak-stream) when the plugin opts in with ``supports_pcm_stream``.

Before this, ``resolve_streaming_provider`` only knew built-in streamers, so a plugin's ``stream()``
was dead surface and every plugin spoke through the per-sentence file round trip.
"""

import pytest

import tools.tts_streaming as ts


@pytest.fixture
def plugin_provider(monkeypatch):
    """Factory registering a plugin ``TTSProvider`` whose ``stream()`` records kwargs and yields fixed PCM."""
    from agent import tts_registry
    from agent.tts_provider import TTSProvider

    monkeypatch.setattr("hermes_cli.plugins._ensure_plugins_discovered", lambda force=False: None)
    tts_registry._reset_for_tests()

    def _make(*, pcm: bool):
        class _Plugin(TTSProvider):
            calls = []
            name = "fishy"
            supports_pcm_stream = pcm

            def synthesize(self, text, output_path, **kw):
                return output_path

            def stream(self, text, **kw):
                type(self).calls.append((text, kw))
                yield from (b"\x01\x00" * 4, b"\x02\x00" * 4)

        tts_registry.register_provider(_Plugin())
        return _Plugin

    yield _make
    tts_registry._reset_for_tests()


def test_opted_in_plugin_provider_streams_pcm(plugin_provider):
    plugin = plugin_provider(pcm=True)
    streamer = ts.resolve_streaming_provider({"provider": "fishy", "voice": "narrator", "model": "m1"})
    assert streamer is not None
    assert b"".join(streamer.stream("Hello.")) == b"\x01\x00" * 4 + b"\x02\x00" * 4
    text, kw = plugin.calls[-1]
    assert text == "Hello." and kw["format"] == "pcm" and kw["sample_rate"] == streamer.sample_rate
    assert kw["voice"] == "narrator" and kw["model"] == "m1"


def test_plugin_provider_without_pcm_opt_in_keeps_sentence_path(plugin_provider):
    plugin_provider(pcm=False)
    assert ts.resolve_streaming_provider({"provider": "fishy"}) is None
