"""Sample-accurate long-silence offsets for the pinned WLK LocalAgreement path."""
import inspect
import textwrap


_PATCH_MARKER = "_desktop_sample_accurate_silence_offset"
_END_SILENCE_CALL = (
    "self.transcription.end_silence(item.duration, "
    "self.state.tokens[-1].end if self.state.tokens else 0)"
)
_END_SILENCE_REPLACEMENT = (
    "self.transcription.end_silence(item.duration, "
    "item.start if item.start is not None else "
    "(self.state.tokens[-1].end if self.state.tokens else 0))"
)


def _patch_transcription_source(source: str) -> str:
    """Replace only the known end_silence offset expression or reject the source."""
    source = textwrap.dedent(source)
    required = {
        "one Silence branch": "if isinstance(item, Silence):",
        "one completed-silence guard": "if item.has_ended:",
        "one legacy end_silence call": _END_SILENCE_CALL,
    }
    counts = {description: source.count(snippet) for description, snippet in required.items()}
    if any(count != 1 for count in counts.values()):
        details = ", ".join(f"{name}={count}" for name, count in counts.items())
        raise RuntimeError(
            "upstream AudioProcessor silence handling changed; refusing timing patch (" + details + ")"
        )
    return source.replace(_END_SILENCE_CALL, _END_SILENCE_REPLACEMENT, 1)


def configure_silence_timing(audio_processor_class=None) -> bool:
    """Install the narrow call-site adapter on upstream's AudioProcessor class.

    Call only for the LocalAgreement backend. A long-silence reset should start
    at the sample-aligned silence boundary, not at the last recognized word.
    """
    if audio_processor_class is None:
        from whisperlivekit.audio_processor import AudioProcessor
        audio_processor_class = AudioProcessor

    current = audio_processor_class.transcription_processor
    if getattr(current, _PATCH_MARKER, False):
        return True

    source = textwrap.dedent(inspect.getsource(current))
    patched_source = _patch_transcription_source(source)
    namespace = dict(current.__globals__)
    filename = inspect.getsourcefile(current) or "whisperlivekit/audio_processor.py"
    exec(compile(patched_source, filename, "exec"), namespace)
    patched = namespace[current.__name__]
    setattr(patched, _PATCH_MARKER, True)
    audio_processor_class.transcription_processor = patched
    return True
