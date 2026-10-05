"""Original CLI commands with the desktop's model paths and environment."""
import argparse
import json
import os
import sys
from pathlib import Path
from app.settings import ROOT

# `runtime/speaker` shares the application site-packages through a .pth file,
# but Python does not process .pth files found in an added site-packages path.
# Make the vendored upstream import explicit for both runtime interpreters.
UPSTREAM_ROOT = str(ROOT / "upstream")
if UPSTREAM_ROOT not in sys.path:
    sys.path.insert(0, UPSTREAM_ROOT)

from app.wlk_config import make_config


COMMANDS={'serve','listen','run','transcribe','bench','models','pull','rm','check','diagnose'}


def _option_value(arguments, *flags):
    """Return a supplied option value for either ``--x value`` or ``--x=value``."""
    for index, item in enumerate(arguments):
        for flag in flags:
            if item == flag:
                return arguments[index + 1] if index + 1 < len(arguments) else ""
            if item.startswith(flag + "="):
                return item[len(flag) + 1:]
    return None


def _set_option(arguments, flag, value, *aliases):
    """Set an option while preserving an existing spelling/value."""
    flags = (flag, *aliases)
    for index, item in enumerate(arguments):
        for candidate in flags:
            if item == candidate:
                if index + 1 < len(arguments):
                    arguments[index + 1] = str(value)
                else:
                    arguments.append(str(value))
                return
            if item.startswith(candidate + "="):
                arguments[index] = f"{candidate}={value}"
                return
    arguments.extend((flag, str(value)))


def build_bench_arguments(arguments, config, *, config_file=None):
    """Prepare original-WLK bench arguments and a sanitized options file.

    Backend, model size, and language are CLI options in the upstream bench
    parser; the JSON file contains only additional engine settings. If the
    caller selects a different model size, a path pinned to the desktop's
    default model is removed so Faster-Whisper resolves the requested model.
    """
    import json

    args = list(arguments)
    selected_model = _option_value(args, "--model")
    if selected_model is None:
        selected_model = config.model_size
        _set_option(args, "--model", selected_model)

    selected_backend = _option_value(args, "--backend")
    if selected_backend is None:
        selected_backend = config.backend
        _set_option(args, "--backend", config.backend)
    if _option_value(args, "--languages", "--lan") is None:
        default_language = config.lan if config.lan != "auto" else "en"
        _set_option(args, "--languages", default_language)

    options = dict(config.__dict__)
    user_config = _option_value(args, "--config")
    if user_config:
        candidate = Path(user_config)
        try:
            is_config_file = candidate.is_file()
        except OSError:
            is_config_file = False
        if is_config_file:
            supplied = json.loads(candidate.read_text(encoding="utf-8"))
        else:
            supplied = json.loads(user_config)
        if not isinstance(supplied, dict):
            raise ValueError("wlk bench --config must contain a JSON object")
        options.update(supplied)

    if selected_model != config.model_size or selected_backend != config.backend:
        options.pop("model_dir", None)
        options.pop("model_path", None)
        if selected_backend in {"auto", "faster-whisper"}:
            local = ROOT / "models" / f"whisper-{selected_model}"
            if (local / "model.bin").is_file() and (local / "config.json").is_file():
                options["model_dir"] = str(local)
        elif selected_backend == "whisper":
            checkpoint = ROOT / "models" / "native-whisper" / f"{selected_model}.pt"
            if checkpoint.is_file():
                options["model_path"] = str(checkpoint)
    for key in ("backend", "model_size", "lan", "api_token"):
        options.pop(key, None)

    if config_file is None:
        config_file = ROOT / "data" / "benchmark_data" / ".native-cli-bench-config.json"
    config_file = Path(config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_option(args, "--config", str(config_file))
    return args


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--settings',required=True)
    parser.add_argument('command',choices=sorted(COMMANDS))
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    parsed=parser.parse_args()
    path=Path(parsed.settings)
    settings=json.loads(path.read_text(encoding='utf-8'))
    path.unlink(missing_ok=True)
    os.environ['PATH']=str(ROOT/'runtime/ffmpeg')+os.pathsep+str(ROOT/'.venv/Lib/site-packages/torch/lib')+os.pathsep+os.environ.get('PATH','')
    os.environ['HF_HOME']=str(ROOT/'models/cache')
    if not settings.get('allow_downloads',False) and parsed.command not in {'pull','run'}:
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['TRANSFORMERS_OFFLINE']='1'
    config=make_config(settings)
    from app.native_models import configure_local_models
    configure_local_models(config)
    arguments=list(parsed.arguments)
    if parsed.command=='bench':
        arguments=build_bench_arguments(arguments,config)
    if parsed.command in {'diagnose','transcribe','listen'}:
        # CLI's file/listen helpers do not expose the full dataclass. Supply
        # desktop defaults to their original TestHarness, with explicit CLI
        # options winning, rather than implement another file pipeline.
        import whisperlivekit.test_harness as harness
        original=harness.TestHarness
        class DesktopHarness(original):
            def __init__(self,**kwargs):
                values=dict(config.__dict__)
                if kwargs.get('model_size',values['model_size'])!=values['model_size']:
                    values['model_dir']=None
                    values['model_path']=None
                values.update(kwargs)
                super().__init__(**values)
        harness.TestHarness=DesktopHarness
    import whisperlivekit.benchmark.datasets as datasets
    datasets.CACHE_DIR=ROOT/'data/benchmark_data'
    from whisperlivekit.cli import main as native_main
    sys.argv=['wlk',parsed.command,*arguments]
    return native_main()


if __name__=='__main__':
    main()
