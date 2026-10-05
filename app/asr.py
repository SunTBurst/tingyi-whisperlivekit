"""WhisperLiveKit ASR setup and the local PCM streaming adapter."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from app.settings import ROOT

_engine_created = False


class LanguageAwareASR:
    """Keep Faster-Whisper's detection metadata alongside its word segments.

    WhisperLiveKit's stock FasterWhisperASR.transcribe discards the info object
    returned by ``WhisperModel.transcribe``. Under ``lan='auto'`` this means
    downstream tokens lose the detected language. This adapter makes the same
    model call with the backend's standard options and tags extracted tokens.
    """

    def __init__(self, backend_asr: Any):
        object.__setattr__(self, "_backend_asr", backend_asr)
        object.__setattr__(self, "_detected_language", None)

    @property
    def original_language(self) -> Optional[str]:
        return self._backend_asr.original_language

    @original_language.setter
    def original_language(self, value: Optional[str]) -> None:
        self._backend_asr.original_language = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend_asr, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_backend_asr", "_detected_language"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._backend_asr, name, value)

    def transcribe(self, audio: Any, init_prompt: str = "") -> list[Any]:
        backend = self._backend_asr
        segments, info = backend.model.transcribe(
            audio,
            language=backend.original_language,
            initial_prompt=init_prompt,
            beam_size=5,
            word_timestamps=True,
            condition_on_previous_text=True,
            **backend.transcribe_kargs,
        )
        object.__setattr__(
            self,
            "_detected_language",
            getattr(info, "language", None) if info is not None else None,
        )
        return list(segments)

    def ts_words(self, result: Any) -> list[Any]:
        tokens = self._backend_asr.ts_words(result)
        detected_language = self._detected_language
        for token in tokens:
            token.detected_language = detected_language
        return tokens


def create_engine(model_size: str = "small") -> Any:
    """Load the process-wide Faster-Whisper engine for one application run.

    WhisperLiveKit's ``TranscriptionEngine`` is a process singleton. Change
    models by starting a fresh application process and calling this once.
    """
    global _engine_created
    if _engine_created:
        raise RuntimeError(
            "create_engine() may be called only once per process; restart the application to change models"
        )

    from whisperlivekit.config import WhisperLiveKitConfig
    from whisperlivekit.core import TranscriptionEngine

    model_dir = ROOT / "models" / f"whisper-{model_size}"
    config = WhisperLiveKitConfig(
        model_size=model_size,
        model_dir=str(model_dir),
        backend="faster-whisper",
        backend_policy="localagreement",
        lan="auto",
        target_language="",
        pcm_input=True,
        vac=True,
        min_chunk_size=0.5,
        asr_coalesce_min_s=0.6,
        pause_segmentation_seconds=0.8,
        diarization=False,
        buffer_trimming="segment",
    )
    engine = TranscriptionEngine(config=config)
    engine.asr = LanguageAwareASR(engine.asr)
    _engine_created = True
    return engine


def _pcm16le_bytes(chunk: Any) -> bytes:
    """Encode a mono float32 chunk as clipped signed 16-bit little endian PCM."""
    import numpy as np

    samples = np.asarray(chunk, dtype=np.float32)
    if samples.ndim != 1:
        raise ValueError("stream_audio expects mono one-dimensional chunks")
    if samples.size == 0:
        return b""
    clipped = np.clip(samples, -1.0, 1.0)
    return np.rint(clipped * 32767.0).astype("<i2", copy=False).tobytes()


async def stream_audio(
    engine: Any,
    chunks: AsyncIterator[Any],
    language: str = "en",
    on_snapshot: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Stream 16 kHz mono float chunks through one AudioProcessor session."""
    from whisperlivekit.audio_processor import AudioProcessor

    processor = AudioProcessor(
        transcription_engine=engine,
        language=language,
        pcm_input=True,
    )
    consumer: Optional[asyncio.Task[None]] = None
    try:
        formatter = await processor.create_tasks()

        async def consume_results() -> None:
            async for snapshot in formatter:
                if on_snapshot is not None:
                    callback_result = on_snapshot(snapshot)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                if getattr(snapshot, "status", None) == "error":
                    message = getattr(snapshot, "error", "") or "WhisperLiveKit ASR processing failed"
                    raise RuntimeError(message)

        consumer = asyncio.create_task(consume_results(), name="asr-snapshot-consumer")
        async for chunk in chunks:
            if consumer.done():
                # Surface formatter failures before feeding more PCM into a
                # processor whose result side has already stopped.
                await consumer
                raise RuntimeError("WhisperLiveKit results formatter stopped before audio EOF")
            message = _pcm16le_bytes(chunk)
            if message:
                await processor.process_audio(message)

        # EOF asks AudioInput to emit any short tail and stop producers. The
        # results consumer remains alive until the formatter has drained them.
        await processor.process_audio(None)
        await consumer
    finally:
        if consumer is not None and not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        await processor.cleanup()
