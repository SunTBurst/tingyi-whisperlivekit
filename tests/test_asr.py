"""Deterministic adapter tests; model inference remains covered by smoke_asr."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np


class _Token:
    def __init__(self, text="hello"):
        self.text = text
        self.detected_language = None


class _FakeInfo:
    language = "ar"


class _FakeWhisperModel:
    """The narrow Faster-Whisper model surface used by the adapter."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append((audio, options))
        return iter(["segment"]), _FakeInfo()


class _FakeFasterWhisperASR:
    def __init__(self):
        self.model = _FakeWhisperModel()
        self.original_language = None
        self.transcribe_kargs = {"vad_filter": True}
        self.sep = ""

    def ts_words(self, segments):
        self.seen_segments = list(segments)
        return [_Token()]

    def segments_end_ts(self, segments):
        return [1.0]

    def use_vad(self):
        self.transcribe_kargs["vad_filter"] = True


class ASRAdapterTests(unittest.TestCase):
    def setUp(self):
        from app.asr import LanguageAwareASR

        self.LanguageAwareASR = LanguageAwareASR

    def test_faster_whisper_language_reaches_tokens_and_session_override(self):
        base = _FakeFasterWhisperASR()
        asr = self.LanguageAwareASR(base)

        result = asr.transcribe(np.zeros(8, dtype=np.float32), init_prompt="terms")
        token = asr.ts_words(result)[0]

        audio, options = base.model.calls[0]
        self.assertEqual(options["language"], None)
        self.assertEqual(options["initial_prompt"], "terms")
        self.assertEqual(options["beam_size"], 5)
        self.assertTrue(options["word_timestamps"])
        self.assertTrue(options["condition_on_previous_text"])
        self.assertTrue(options["vad_filter"])
        self.assertIs(audio, base.model.calls[0][0])
        self.assertEqual(token.detected_language, "ar")

        asr.original_language = "zh"
        self.assertEqual(base.original_language, "zh")
        asr.original_language = None
        asr.transcribe(np.zeros(8, dtype=np.float32))
        self.assertEqual(base.model.calls[-1][1]["language"], None)

        from whisperlivekit.session_asr_proxy import SessionASRProxy

        proxy = SessionASRProxy(asr, "zh")
        proxy.transcribe(np.zeros(8, dtype=np.float32))
        self.assertEqual(base.model.calls[-1][1]["language"], "zh")
        self.assertIsNone(base.original_language)

    def test_create_engine_builds_the_local_agreement_config(self):
        from app import asr as asr_module

        seen = {}

        @dataclass
        class FakeConfig:
            values: dict

            def __init__(self, **kwargs):
                self.values = kwargs

        class FakeEngine:
            def __init__(self, config):
                seen["config"] = config
                self.asr = _FakeFasterWhisperASR()

        fake_pkg = types.ModuleType("whisperlivekit")
        fake_pkg.__path__ = []
        fake_config = types.ModuleType("whisperlivekit.config")
        fake_config.WhisperLiveKitConfig = FakeConfig
        fake_core = types.ModuleType("whisperlivekit.core")
        fake_core.TranscriptionEngine = FakeEngine
        with patch.dict(sys.modules, {
            "whisperlivekit": fake_pkg,
            "whisperlivekit.config": fake_config,
            "whisperlivekit.core": fake_core,
        }):
            engine = asr_module.create_engine("medium")

        self.assertIsInstance(engine, FakeEngine)
        self.assertIsInstance(engine.asr, self.LanguageAwareASR)
        values = seen["config"].values
        self.assertEqual(values["model_size"], "medium")
        self.assertEqual(values["backend"], "faster-whisper")
        self.assertEqual(values["backend_policy"], "localagreement")
        self.assertEqual(values["lan"], "auto")
        self.assertEqual(values["model_dir"], str(Path("models/whisper-medium").resolve()))
        self.assertEqual(values["target_language"], "")
        self.assertTrue(values["pcm_input"])
        self.assertTrue(values["vac"])
        self.assertEqual(values["min_chunk_size"], 0.5)
        self.assertEqual(values["asr_coalesce_min_s"], 0.6)
        self.assertEqual(values["pause_segmentation_seconds"], 0.8)
        self.assertFalse(values["diarization"])
        self.assertEqual(values["buffer_trimming"], "segment")
        with self.assertRaisesRegex(RuntimeError, "only once per process"):
            asr_module.create_engine("small")

    def test_stream_audio_flushes_callbacks_and_cleans_up(self):
        from app.asr import stream_audio

        class FakeFrontData:
            status = "active_transcription"
            lines = ["final line"]
            error = None

        class FakeProcessor:
            latest = None

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.messages = []
                self.cleaned = False
                self.eof = asyncio.Event()
                FakeProcessor.latest = self

            async def create_tasks(self):
                async def results():
                    yield FakeFrontData()
                    await self.eof.wait()
                    yield FakeFrontData()
                return results()

            async def process_audio(self, message):
                self.messages.append(message)
                if message is None:
                    self.eof.set()

            async def cleanup(self):
                self.cleaned = True

        processor_module = types.ModuleType("whisperlivekit.audio_processor")
        processor_module.AudioProcessor = FakeProcessor
        pkg = types.ModuleType("whisperlivekit")
        pkg.__path__ = []
        snapshots = []

        async def chunks():
            yield np.array([-1.2, -0.25, 0.25, 1.2], dtype=np.float32)

        with patch.dict(sys.modules, {
            "whisperlivekit": pkg,
            "whisperlivekit.audio_processor": processor_module,
        }):
            asyncio.run(stream_audio(object(), chunks(), language="en", on_snapshot=snapshots.append))

        processor = FakeProcessor.latest
        self.assertTrue(processor.cleaned)
        self.assertEqual(processor.kwargs["language"], "en")
        self.assertTrue(processor.kwargs["pcm_input"])
        self.assertEqual(len(processor.messages), 2)
        self.assertIsNone(processor.messages[-1])
        np.testing.assert_array_equal(
            np.frombuffer(processor.messages[0], dtype="<i2"),
            [-32767, -8192, 8192, 32767],
        )
        self.assertEqual(len(snapshots), 2)

    def test_stream_audio_cleans_up_when_audio_source_fails(self):
        from app.asr import stream_audio

        class FakeProcessor:
            latest = None

            def __init__(self, **kwargs):
                self.cleaned = False
                self.result_closed = False
                FakeProcessor.latest = self

            async def create_tasks(self):
                async def results():
                    try:
                        while True:
                            await asyncio.sleep(1)
                            yield object()
                    finally:
                        self.result_closed = True
                return results()

            async def process_audio(self, message):
                await asyncio.sleep(0)

            async def cleanup(self):
                self.cleaned = True

        async def broken_chunks():
            yield np.ones(16, dtype=np.float32)
            raise OSError("input failed")

        processor_module = types.ModuleType("whisperlivekit.audio_processor")
        processor_module.AudioProcessor = FakeProcessor
        pkg = types.ModuleType("whisperlivekit")
        pkg.__path__ = []
        with patch.dict(sys.modules, {
            "whisperlivekit": pkg,
            "whisperlivekit.audio_processor": processor_module,
        }):
            with self.assertRaisesRegex(OSError, "input failed"):
                asyncio.run(stream_audio(object(), broken_chunks()))

        self.assertTrue(FakeProcessor.latest.cleaned)
        self.assertTrue(FakeProcessor.latest.result_closed)


if __name__ == "__main__":
    unittest.main()
