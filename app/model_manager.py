"""Local model catalog and safe installation/removal helpers for the app."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.settings import ROOT

MODEL_ROOT = (ROOT / "models").resolve()
NLLB_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
NLLB_REVISION = "302d78f00e6fdb50a1064059df7c392b735e9d05"
SORTFORMER_REPO = "nvidia/diar_streaming_sortformer_4spk-v2"
HUB_CACHE = MODEL_ROOT / "cache" / "hub"

_WHISPER_SIZES = (
    "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
    "large-v1", "large-v2", "large-v3", "large-v3-turbo",
)
_ASR_REPOS = {f"whisper-{size}": f"Systran/faster-whisper-{size}" for size in _WHISPER_SIZES}
_ASR_REPOS["whisper-large-v3-turbo"] = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
_CATALOG = [
    {"name": f"whisper-{size}", "kind": "asr", "repo": _ASR_REPOS[f"whisper-{size}"], "path": f"whisper-{size}", "backend": "faster-whisper"}
    for size in _WHISPER_SIZES
] + [
    {"name": f"native-whisper-{size}", "kind": "native-whisper", "path": f"native-whisper/{size}.pt", "backend": "whisper"}
    for size in _WHISPER_SIZES
] + [
    {"name": "nllb-600m-int8", "kind": "translation", "repo": NLLB_REPO, "revision": NLLB_REVISION, "path": "nllb-600m", "backend": "nllw/ctranslate2"},
    {"name": "sortformer-4spk-v2", "kind": "speaker", "repo": SORTFORMER_REPO, "path": "sortformer", "backend": "nemo-sortformer"},
    # Advanced upstream CLI-only entries stay visible in the catalog; the
    # application routes their downloads through the original `wlk pull`.
    {"name": "voxtral", "kind": "asr", "repo": "mistralai/Voxtral-Mini-4B-Realtime-2602", "managed_by": "wlk pull", "backend": "voxtral"},
    {"name": "voxtral-mlx", "kind": "asr", "repo": "mlx-community/Voxtral-Mini-4B-Realtime-6bit", "managed_by": "wlk pull", "backend": "voxtral-mlx", "platform": "darwin-arm64"},
    {"name": "qwen3-vllm:1.7b", "kind": "asr", "repo": "Qwen/Qwen3-ASR-1.7B", "managed_by": "wlk pull", "backend": "qwen3-vllm"},
    {"name": "qwen3-vllm:0.6b", "kind": "asr", "repo": "Qwen/Qwen3-ASR-0.6B", "managed_by": "wlk pull", "backend": "qwen3-vllm"},
    {"name": "qwen3-vllm-metal:1.7b", "kind": "asr", "repo": "Qwen/Qwen3-ASR-1.7B", "managed_by": "wlk pull", "backend": "qwen3-vllm-metal", "platform": "darwin-arm64"},
    {"name": "qwen3-vllm-metal:0.6b", "kind": "asr", "repo": "Qwen/Qwen3-ASR-0.6B", "managed_by": "wlk pull", "backend": "qwen3-vllm-metal", "platform": "darwin-arm64"},
]


def _faster_whisper_repo(size: str) -> str:
    """Prefer the installed Faster-Whisper package's official repo mapping."""
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(size, _ASR_REPOS[f"whisper-{size}"])
    except (ImportError, KeyError):
        return _ASR_REPOS[f"whisper-{size}"]


def _hub_repos() -> dict[str, str]:
    """Return repo paths from the app-owned Hugging Face cache only."""
    try:
        from huggingface_hub import scan_cache_dir
        return {
            repo.repo_id: str(repo.repo_path)
            for repo in scan_cache_dir(cache_dir=HUB_CACHE).repos
        }
    except Exception:
        return {}


def _official_whisper_models() -> dict[str, str]:
    """Read vendored upstream Whisper URLs without loading any checkpoint."""
    upstream_root = str(ROOT / "upstream")
    added_path = upstream_root not in sys.path
    if added_path:
        sys.path.insert(0, upstream_root)
    try:
        from whisperlivekit.whisper import _MODELS
        return _MODELS
    finally:
        if added_path:
            try:
                sys.path.remove(upstream_root)
            except ValueError:
                pass


def catalog() -> list[dict]:
    """Return all locally managed and upstream WLK pullable model entries."""
    rows = [dict(item) for item in _CATALOG]
    native_urls = _official_whisper_models()
    for row in rows:
        if row["backend"] == "faster-whisper":
            size = row["name"].removeprefix("whisper-")
            row["repo"] = _faster_whisper_repo(size)
        elif row["kind"] == "native-whisper":
            row["source_url"] = native_urls[row["name"].removeprefix("native-whisper-")]
    return rows


def _is_model_installed(entry: dict) -> bool:
    if entry.get("managed_by") == "wlk pull":
        return entry["repo"] in _hub_repos()
    path = MODEL_ROOT / entry["path"]
    if entry["kind"] == "native-whisper":
        return path.is_file()
    if entry["name"] == "nllb-600m-int8":
        return all((path / file).is_file() for file in ("model.bin", "config.json", "tokenizer.json", "shared_vocabulary.txt"))
    if entry["name"] == "sortformer-4spk-v2":
        return (path / "diar_streaming_sortformer_4spk-v2.nemo").is_file()
    return (path / "model.bin").is_file() and (path / "config.json").is_file()


def installed_models() -> list[dict]:
    """Return managed catalog entries plus registered external model paths."""
    found = []
    for entry in _CATALOG:
        item = dict(entry)
        item["installed"] = _is_model_installed(entry)
        item["local_path"] = str(MODEL_ROOT / entry["path"]) if item.get("path") and item["installed"] else None
        item["files_present"] = item["installed"]
        item["validated"] = item["installed"]
        item["dependencies_installed"] = None
        item["loaded"] = None
        item["source"] = "managed"
        item["format"] = str(item.get("backend") or "unknown")
        item["size_bytes"] = _path_size(Path(item["local_path"])) if item["local_path"] else None
        item["files"] = _top_level_files(Path(item["local_path"])) if item["local_path"] else []
        found.append(item)
    try:
        from app import model_registry
        for record in model_registry.read_model_registry(model_registry.REGISTRY_PATH):
            item = dict(record)
            item.update(model_registry.validate_external_model(record))
            item["installed"] = bool(item["files_present"])
            item["local_path"] = item.get("path") if item["files_present"] else None
            item["source"] = "external"
            item["repo"] = None
            item["files"] = _top_level_files(Path(item["path"])) if item["files_present"] else []
            found.append(item)
    except (OSError, ValueError):
        pass
    return found


def _path_size(path: Path) -> int | None:
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
    except OSError:
        return None


def _top_level_files(path: Path) -> list[str]:
    try:
        return [item.name for item in path.iterdir() if item.is_file()][:50] if path.is_dir() else [path.name]
    except OSError:
        return []


def backend_availability() -> list[dict]:
    """Describe backend dependencies, platform limits, and install commands."""
    windows = platform.system() == "Windows"
    specs = [
        ("faster-whisper", "faster_whisper", "pip install faster-whisper", "LocalAgreement chunk streaming"),
        ("native-whisper", None, "Included with the vendored upstream WhisperLiveKit source", "OpenAI Whisper LocalAgreement streaming"),
        ("nllw/ctranslate2", "nllw", "pip install nllw ctranslate2", "Native nllw streaming translation"),
        ("funasr", "funasr", "pip install funasr", "SenseVoice LocalAgreement ASR"),
        ("canary", "nemo", "python scripts/setup_speaker.py --install", "NeMo Canary ASR in the isolated NeMo runtime"),
        ("nemo-sortformer", "nemo", "python scripts/setup_speaker.py --all", "NVIDIA streaming Sortformer in the isolated speaker runtime"),
        ("diart", "diart", 'pip install "whisperlivekit[diarization-diart]"', "Speaker diarization alternative"),
        ("qwen3-streaming", "qwen3_asr_causal", 'pip install "qwen3-asr-causal[streaming]"', "Qwen3 causal streaming ASR"),
        ("voxtral-hf", "mistral_common", 'pip install "whisperlivekit[voxtral-hf]" accelerate', "Voxtral native streaming on Transformers"),
        ("voxtral-mlx", "mlx", "pip install mlx mlx-lm", "Apple Silicon only"),
        ("qwen3-vllm", "vllm", "pip install vllm", "Linux/CUDA deployment; unavailable on Windows"),
        ("vllm", "vllm", "pip install vllm", "Upstream vLLM backend alias"),
        ("qwen3-vllm-metal", "vllm_metal", "Install vllm-metal for Apple Silicon", "Apple Silicon only"),
        ("mlx", "mlx", "pip install mlx mlx-lm", "Apple Silicon only"),
    ]
    rows = []
    for name, module, install, description in specs:
        if name == "native-whisper":
            present = (ROOT / "upstream" / "whisperlivekit" / "whisper" / "__init__.py").is_file()
        elif name == "nemo-sortformer":
            present = (
                (ROOT / "runtime" / "speaker" / "Scripts" / "python.exe").is_file()
                and (ROOT / "runtime" / "speaker" / "speaker-runtime-ready.json").is_file()
                and (MODEL_ROOT / "sortformer" / "diar_streaming_sortformer_4spk-v2.nemo").is_file()
            )
        elif name == "canary":
            present = (
                (ROOT / "runtime" / "speaker" / "Scripts" / "python.exe").is_file()
                and (ROOT / "runtime" / "speaker" / "speaker-runtime-ready.json").is_file()
            )
        elif name == "voxtral-hf":
            try:
                present = all(importlib.util.find_spec(dep) is not None for dep in ("mistral_common", "accelerate"))
            except (ImportError, ValueError, ModuleNotFoundError):
                present = False
        else:
            try:
                present = importlib.util.find_spec(module) is not None if module else False
            except (ImportError, ValueError, ModuleNotFoundError):
                present = False
        warnings = []
        if name == "mlx" and windows:
            warnings.append("MLX requires Apple Silicon macOS; unavailable on Windows.")
        if name == "voxtral-mlx" and windows:
            warnings.append("Voxtral MLX requires Apple Silicon macOS; unavailable on Windows.")
        if name == "vllm" and windows:
            warnings.append("vLLM is not supported by this Windows runtime.")
        if name in {"qwen3-vllm", "qwen3-vllm-metal"} and windows:
            warnings.append("This vLLM backend is not supported on Windows.")
        if name == "nemo-sortformer" and windows and not present:
            warnings.append("Run scripts/setup_speaker.py --all to prepare the isolated NeMo runtime and verify Sortformer.")
        rows.append({
            "name": name,
            "available": present,
            "dependencies_installed": present,
            "install": install,
            "description": description,
            "warnings": warnings,
        })
    return rows


def _progress(callback: Callable | None, name: str, stage: str, **details) -> None:
    if callback is None:
        return
    callback({"name": name, "stage": stage, **details})


def download_model(name: str, progress: Callable | None = None) -> Path:
    """Download one catalog model into ROOT/models and return its local path.

    ``progress`` receives dictionaries with ``name``, ``stage`` and optional
    ``path``/``message`` fields. Hugging Face's downloader reports transfer
    progress to its own terminal progress bar; this callback reports lifecycle.
    """
    try:
        entry = next(item for item in _CATALOG if item["name"] == name)
    except StopIteration as exc:
        raise ValueError(f"Unknown model {name!r}; choose one of: {', '.join(x['name'] for x in _CATALOG)}") from exc
    if entry["backend"] == "faster-whisper":
        size = entry["name"].removeprefix("whisper-")
        entry = {**entry, "repo": _faster_whisper_repo(size)}

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    if entry.get("managed_by") == "wlk pull":
        if entry.get("platform") == "darwin-arm64" and platform.system() != "Darwin":
            raise RuntimeError(f"{name} requires Apple Silicon macOS")
        _progress(progress, name, "downloading", message="Running upstream wlk pull")
        upstream_root = ROOT / "upstream"
        sys.path.insert(0, str(upstream_root))
        old_env = {key: os.environ.get(key) for key in ("HF_HOME", "HF_HUB_CACHE")}
        os.environ["HF_HOME"] = str(MODEL_ROOT / "cache")
        os.environ["HF_HUB_CACHE"] = str(HUB_CACHE)
        constants = None
        old_hub_cache = None
        try:
            from huggingface_hub import constants as hf_constants
            constants = hf_constants
            old_hub_cache = constants.HF_HUB_CACHE
            constants.HF_HUB_CACHE = str(HUB_CACHE)
            from whisperlivekit.cli import cmd_pull
            result = cmd_pull(name)
        finally:
            if constants is not None and old_hub_cache is not None:
                constants.HF_HUB_CACHE = old_hub_cache
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            try:
                sys.path.remove(str(upstream_root))
            except ValueError:
                pass
        if result != 0 or not _is_model_installed(entry):
            raise RuntimeError(f"Upstream wlk pull did not install {name}")
        _progress(progress, name, "ready")
        return Path(_hub_repos()[entry["repo"]])

    target = MODEL_ROOT / entry["path"]
    if _is_model_installed(entry):
        _progress(progress, name, "ready", path=str(target))
        return target

    _progress(progress, name, "downloading", path=str(target))
    try:
        if entry["kind"] == "translation":
            # Reuse the repository's pinned download and SHA verification.
            import runpy
            runpy.run_path(str(ROOT / "scripts" / "download_nllb.py"), run_name="__main__")
        elif entry["kind"] == "speaker":
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "setup_speaker.py"), "--download"],
                cwd=ROOT,
                check=True,
            )
        elif entry["kind"] == "native-whisper":
            target.parent.mkdir(parents=True, exist_ok=True)
            models = _official_whisper_models()
            size = name.removeprefix("native-whisper-")
            upstream_root = str(ROOT / "upstream")
            added_path = upstream_root not in sys.path
            if added_path:
                sys.path.insert(0, upstream_root)
            try:
                from whisperlivekit.whisper import _download
                downloaded = Path(_download(models[size], str(target.parent), in_memory=False))
            finally:
                if added_path:
                    try:
                        sys.path.remove(upstream_root)
                    except ValueError:
                        pass
            if downloaded.resolve() != target.resolve():
                raise RuntimeError(f"Official Whisper downloader returned unexpected path: {downloaded}")
        else:
            from huggingface_hub import snapshot_download

            target.mkdir(parents=True, exist_ok=True)
            kwargs = {"repo_id": entry["repo"], "local_dir": str(target)}
            if entry.get("revision"):
                kwargs["revision"] = entry["revision"]
            snapshot_download(**kwargs)
            if not _is_model_installed(entry):
                raise RuntimeError(f"Download finished but expected model files are missing in {target}")
    except Exception as exc:
        _progress(progress, name, "failed", path=str(target), message=str(exc))
        raise

    _progress(progress, name, "ready", path=str(target))
    return target


def remove_model(path: str | os.PathLike) -> Path:
    """Delete an explicitly selected path strictly contained by ROOT/models."""
    raw = Path(path).expanduser()
    target = (raw if raw.is_absolute() else MODEL_ROOT / raw).resolve(strict=False)
    try:
        relative = target.relative_to(MODEL_ROOT)
    except ValueError as exc:
        raise ValueError(f"Refusing to remove a path outside {MODEL_ROOT}: {target}") from exc
    if not relative.parts:
        raise ValueError("Refusing to remove the models root itself")
    if not target.exists():
        raise FileNotFoundError(target)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return target
