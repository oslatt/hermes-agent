"""Text-to-Speech Provider ABC.

Providers register via ``PluginContext.register_tts_provider()`` and service
``text_to_speech`` only when ``tts.provider`` names neither a built-in
(``BUILTIN_TTS_PROVIDERS`` in :mod:`tools.tts_tool`; the registry rejects
colliding names) nor a ``tts.providers.<name>: type: command`` entry (config is
more local than a plugin install, so it wins). :meth:`TTSProvider.synthesize`
should raise on failure — the dispatcher builds the ``{success: False}`` envelope.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, Iterator, List, Optional

from agent.provider_base import CatalogProviderBase

logger = logging.getLogger(__name__)


DEFAULT_OUTPUT_FORMAT = "mp3"
VALID_OUTPUT_FORMATS = frozenset({"mp3", "wav", "ogg", "opus", "flac"})


class TTSProvider(CatalogProviderBase):
    """Abstract base class for a text-to-speech backend.

    Subclasses must implement :attr:`name` (rejected at registration if it
    collides with a built-in TTS provider name) and :meth:`synthesize`.
    """

    def list_voices(self) -> List[Dict[str, Any]]:
        """Voice catalog entries: ``{"id"}`` required; ``display`` / ``language``
        / ``gender`` / ``preview_url`` optional. Default: empty."""
        return []

    def default_voice(self) -> Optional[str]:
        """Id of the first voice entry, or None if not applicable."""
        voices = self.list_voices()
        return voices[0].get("id") if voices else None

    @abc.abstractmethod
    def synthesize(
        self, text: str, output_path: str, *, voice: Optional[str]=None, model: Optional[str]=None,
        speed: Optional[float]=None, format: str=DEFAULT_OUTPUT_FORMAT, ** extra: Any,
    ) -> str:
        """Synthesize ``text`` into ``output_path`` and return the written path.

        ``text`` is already truncated to the provider's max length and the
        parent directory exists. ``voice`` / ``model`` fall back to
        :meth:`default_voice` / :meth:`default_model` when None; ``speed`` is a
        rate multiplier providers may ignore. If ``format`` is unsupported, pick
        the closest equivalent and make ``output_path`` carry the right
        extension. Unknown ``extra`` keys must be ignored. Raise on failure.
        """

    def stream(
        self, text: str, *, voice: Optional[str] = None, model: Optional[str] = None,
        format: str = "opus", **extra: Any,
    ) -> Iterator[bytes]:
        """Stream synthesized audio bytes (optional).

        Default raises :class:`NotImplementedError`. ``format="pcm"`` means raw
        int16 little-endian mono at ``extra["sample_rate"]``; that is the only
        form Hermes requests, and only from providers that set
        :attr:`supports_pcm_stream`.
        """
        raise NotImplementedError(
            f"TTS provider {self.name!r} does not implement streaming "
            "synthesis. Use synthesize() instead, or implement stream() "
            "if your backend supports it."
        )

    @property
    def supports_pcm_stream(self) -> bool:
        """Opt in to the low-latency speech consumers (voice mode, gateway streaming, dashboard
        speak-stream): they call :meth:`stream` with ``format="pcm"`` and ``sample_rate`` per
        sentence and play chunks as they arrive. False keeps the per-sentence :meth:`synthesize`
        path. Default False."""
        return False

    def warm(self) -> None:
        """Speech output was just turned on; pre-load so the first reply is hot.
        Called from the TTS lease path when this is the configured provider.
        Best-effort; default no-op."""

    def release(self) -> None:
        """Last speech-output lease released; free resident resources (counterpart
        of :meth:`warm`). Best-effort; default no-op."""

    @property
    def voice_compatible(self) -> bool:
        """Whether output suits voice-bubble delivery (mirrors
        ``tts.providers.<name>.voice_compatible``): True → the gateway converts
        to Opus via ffmpeg if needed; False → regular audio attachment. Default
        False (opt in).

        See #17843.
        """
        return False


def resolve_output_format(value: Optional[str]) -> str:
    """Clamp an output_format to :data:`VALID_OUTPUT_FORMATS`; invalid values
    coerce to :data:`DEFAULT_OUTPUT_FORMAT` so the tool surface forgives agent
    mistakes instead of rejecting them."""
    v = value.strip().lower() if isinstance(value, str) else None
    return v if v in VALID_OUTPUT_FORMATS else DEFAULT_OUTPUT_FORMAT
