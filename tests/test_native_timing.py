from types import SimpleNamespace

import pytest

from app.native_timing import (_END_SILENCE_CALL, _END_SILENCE_REPLACEMENT,
                               _patch_transcription_source, configure_silence_timing)


def source_for(call=_END_SILENCE_CALL):
    return f'''\
async def transcription_processor(self):
    item = self.item
    if isinstance(item, Silence):
        if item.has_ended:
            self.transcription.end_silence(item.duration, {call.removeprefix("self.transcription.end_silence(item.duration, ").removesuffix(")")})
'''


class FakeTranscription:
    def __init__(self):
        self.offset = 0.0
        self.buffer = [1.0, 2.0]
        self.words = [{"text": "recognized", "start": 13.1, "end": 13.38}]
        self.calls = []

    def end_silence(self, duration, offset):
        self.calls.append((duration, offset))
        if duration >= 5:
            self.offset = offset + duration
            self.buffer = []
        else:
            self.buffer.extend([0.0] * round(duration * 10))


class FakeProcessor:
    def __init__(self, item, transcription):
        self.item = item
        self.transcription = transcription
        self.state = SimpleNamespace(tokens=[SimpleNamespace(end=13.38)])


def compile_processor(source):
    namespace = {"Silence": object}
    exec(compile(source, "fake_audio_processor.py", "exec"), namespace)
    return namespace["transcription_processor"]


def test_long_silence_uses_sample_precise_silence_start_and_preserves_words():
    original = source_for()
    patched = _patch_transcription_source(original)
    processor = FakeProcessor(SimpleNamespace(has_ended=True, duration=106.47, start=13.53),
                              FakeTranscription())

    import asyncio
    asyncio.run(compile_processor(patched)(processor))

    assert processor.transcription.calls == [(106.47, 13.53)]
    assert processor.transcription.offset == pytest.approx(120.0)
    assert processor.transcription.words == [{"text": "recognized", "start": 13.1, "end": 13.38}]
    assert _END_SILENCE_REPLACEMENT in patched


def test_short_silence_keeps_existing_audio_padding_behavior():
    original = source_for()
    patched = _patch_transcription_source(original)
    processor = FakeProcessor(SimpleNamespace(has_ended=True, duration=0.84, start=2.74),
                              FakeTranscription())

    import asyncio
    asyncio.run(compile_processor(patched)(processor))

    assert processor.transcription.calls == [(0.84, 2.74)]
    assert processor.transcription.offset == 0.0
    assert len(processor.transcription.buffer) == 10
    assert processor.transcription.buffer[-8:] == [0.0] * 8
    assert processor.transcription.words[0]["end"] == 13.38


def test_missing_silence_start_falls_back_to_last_word_end():
    patched = _patch_transcription_source(source_for())
    processor = FakeProcessor(SimpleNamespace(has_ended=True, duration=106.47, start=None),
                              FakeTranscription())

    import asyncio
    asyncio.run(compile_processor(patched)(processor))

    assert processor.transcription.calls == [(106.47, 13.38)]
    assert processor.transcription.offset == pytest.approx(119.85)


def test_patch_changes_only_the_second_argument_of_one_call():
    original = source_for()
    patched = _patch_transcription_source(original)
    expected = original.replace(_END_SILENCE_CALL, _END_SILENCE_REPLACEMENT, 1)

    assert patched == expected


def test_unrecognized_upstream_structure_is_rejected():
    unsupported = source_for().replace(_END_SILENCE_CALL, "self.transcription.handle_silence(item)")
    with pytest.raises(RuntimeError, match="upstream.*changed"):
        _patch_transcription_source(unsupported)


def test_ambiguous_callsite_is_rejected():
    unsupported = source_for() + "\n" + source_for().split("async def transcription_processor(self):", 1)[1]
    with pytest.raises(RuntimeError, match="upstream.*changed"):
        _patch_transcription_source(unsupported)


def test_pinned_upstream_transcription_processor_matches_the_expected_single_site():
    import inspect
    import textwrap
    from whisperlivekit.audio_processor import AudioProcessor

    source = inspect.getsource(AudioProcessor.transcription_processor)
    patched = _patch_transcription_source(source)
    assert patched == textwrap.dedent(source).replace(_END_SILENCE_CALL, _END_SILENCE_REPLACEMENT, 1)


def test_runtime_patch_is_idempotent(monkeypatch):
    import app.native_timing as adapter

    class DummyAudioProcessor:
        async def transcription_processor(self):
            pass

    monkeypatch.setattr(adapter.inspect, "getsource", lambda _function: source_for())
    monkeypatch.setattr(adapter.inspect, "getsourcefile", lambda _function: "audio_processor.py")

    assert configure_silence_timing(DummyAudioProcessor) is True
    patched = DummyAudioProcessor.transcription_processor
    assert configure_silence_timing(DummyAudioProcessor) is True
    assert DummyAudioProcessor.transcription_processor is patched
