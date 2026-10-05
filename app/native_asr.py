"""Compatibility fix for upstream per-session SimulStreaming language tokens."""
import inspect
import textwrap


def configure_session_tokenizers():
    from whisperlivekit.simul_whisper.backend import SimulStreamingOnlineProcessor
    configure_median_fallback()
    current=SimulStreamingOnlineProcessor.__init__
    if getattr(current,'_desktop_session_tokenizer',False): return
    source=textwrap.dedent(inspect.getsource(current))
    guard='if asr.tokenizer:'
    if source.count(guard)!=1:
        raise RuntimeError('原库 SimulStreaming tokenizer 初始化已改变，请检查会话语言兼容补丁。')
    # AlignAtt already builds the right tokenizer from SessionASRProxy.cfg.
    # The shared ASR tokenizer must only override it for a non-session decoder.
    source=source.replace(guard,'if asr.tokenizer and getattr(asr, "_session_cfg", None) is None:',1)
    namespace=dict(current.__globals__)
    exec(compile(source,inspect.getsourcefile(current),'exec'),namespace)
    patched=namespace['__init__']
    patched._desktop_session_tokenizer=True
    SimulStreamingOnlineProcessor.__init__=patched


def configure_median_fallback():
    """Keep upstream's Torch fallback when an optional Triton import races."""
    from whisperlivekit.whisper import timing
    from whisperlivekit.simul_whisper import simul_whisper
    current=timing.median_filter
    if getattr(current,'_desktop_import_fallback',False): return
    source=textwrap.dedent(inspect.getsource(current))
    guard='except (RuntimeError, subprocess.CalledProcessError):'
    if source.count(guard)!=1:
        raise RuntimeError('原库 median_filter 实现已改变，请检查 Windows 加速兼容补丁。')
    source=source.replace(guard,'except (ImportError, RuntimeError, subprocess.CalledProcessError):',1)
    namespace=dict(current.__globals__)
    exec(compile(source,inspect.getsourcefile(current),'exec'),namespace)
    patched=namespace['median_filter']
    patched._desktop_import_fallback=True
    timing.median_filter=patched
    simul_whisper.median_filter=patched
