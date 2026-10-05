"""Prepare the vendored Whisper SimulStreaming runtime and run local smoke cases.

This uses WhisperLiveKit's bundled PyTorch Whisper implementation. It does not
install the separate openai-whisper distribution or modify Torch packages.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(UPSTREAM) not in sys.path:
    sys.path.insert(0, str(UPSTREAM))

MODEL_NAME = "small"
MODEL_SHA256 = "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794"
MODEL_URL = (
    "https://openaipublic.azureedge.net/main/whisper/models/"
    f"{MODEL_SHA256}/small.pt"
)
REPORT_PATH = ROOT / "logs" / "native-simul-smoke.json"


def model_path(root: Path = ROOT) -> Path:
    """Return the single local checkpoint path used by the native backend."""
    return Path(root) / "models" / "native-whisper" / "small.pt"


def validate_checkpoint(path: Path, expected_sha256: str = MODEL_SHA256) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as checkpoint:
        for chunk in iter(lambda: checkpoint.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected_sha256.lower()


def download_checkpoint(
    root: Path = ROOT,
    *,
    url: str = MODEL_URL,
    opener: Callable = urllib.request.urlopen,
    expected_sha256: str = MODEL_SHA256,
) -> Path:
    """Download to a temporary file and publish only after SHA256 validation."""
    target = model_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if validate_checkpoint(target, expected_sha256):
        return target
    temporary = target.with_suffix(target.suffix + ".download")
    digest = hashlib.sha256()
    try:
        with opener(url, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Whisper checkpoint SHA256 mismatch: expected {expected_sha256}, got {actual}"
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def streaming_options(
    checkpoint: Path,
    *,
    source: str,
    target: str = "",
    direct_english: bool = False,
) -> dict:
    """Build explicit native SimulStreaming configuration for the given case."""
    return {
        "backend": "whisper",
        "backend_policy": "simulstreaming",
        "model_size": "small",
        "model_path": str(checkpoint),
        "lan": source,
        "target_language": target,
        "direct_english_translation": direct_english,
        "nllb_backend": "ctranslate2",
        "nllb_size": "600M",
        "disable_fast_encoder": True,
        "vac": False,
        "diarization": False,
        "pcm_input": True,
    }


def torch_versions() -> dict[str, str | None]:
    """Read installed package versions without importing or mutating Torch."""
    versions = {}
    for package in ("torch", "torchaudio"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def ensure_ffmpeg_on_path(root: Path = ROOT) -> Path:
    """Expose the app-bundled ffmpeg to upstream TestHarness audio decoding."""
    ffmpeg_dir = Path(root) / "runtime" / "ffmpeg"
    executable = ffmpeg_dir / "ffmpeg.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Bundled ffmpeg was not found: {executable}")
    normalized = os.path.normcase(str(ffmpeg_dir.resolve()))
    current = os.environ.get("PATH", "")
    if not any(os.path.normcase(str(Path(item).resolve())) == normalized
               for item in current.split(os.pathsep) if item):
        os.environ["PATH"] = str(ffmpeg_dir.resolve()) + os.pathsep + current
    return executable


def runtime_inventory() -> dict:
    import whisperlivekit.whisper as bundled_whisper

    from whisperlivekit.config import WhisperLiveKitConfig

    bundled_url = bundled_whisper._MODELS.get(MODEL_NAME)
    if not bundled_url or bundled_url.split("/")[-2] != MODEL_SHA256:
        raise RuntimeError("The vendored Whisper small checkpoint URL/hash changed; review deployment metadata.")
    try:
        standalone_whisper_version = importlib.metadata.version("openai-whisper")
    except importlib.metadata.PackageNotFoundError:
        standalone_whisper_version = None
    import torch
    versions = torch_versions()
    torch_release = (versions["torch"] or "").split("+", 1)[0].split(".")[:2]
    torchaudio_release = (versions["torchaudio"] or "").split("+", 1)[0].split(".")[:2]

    return {
        "python": sys.version.split()[0],
        "whisperlivekit_version": importlib.metadata.version("whisperlivekit"),
        "bundled_whisper": str(Path(bundled_whisper.__file__).resolve()),
        "bundled_whisper_version": bundled_whisper.__version__,
        "standalone_openai_whisper_version": standalone_whisper_version,
        "torch_versions": versions,
        "torch_torchaudio_major_minor_match": torch_release == torchaudio_release,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "config_type": f"{WhisperLiveKitConfig.__module__}.{WhisperLiveKitConfig.__name__}",
        "model_url": bundled_url,
        "model_sha256": MODEL_SHA256,
    }


def _plain_translation(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("translation") or "")
    return str(getattr(value, "text", "") or "")


async def _run_case(name: str, audio_path: Path, options: dict, *, use_local_nllb: bool) -> dict:
    from whisperlivekit.config import WhisperLiveKitConfig
    from whisperlivekit.test_harness import TestHarness

    started = time.perf_counter()
    local_hook = False
    if use_local_nllb:
        from app.native_models import configure_local_models

        config = WhisperLiveKitConfig.from_kwargs(**options)
        local_hook = configure_local_models(config)
        if not local_hook:
            raise RuntimeError("Local NLLB CTranslate2 model is incomplete or local hook did not install")
    async with TestHarness(**options) as harness:
        await harness.feed(str(audio_path), speed=0, chunk_duration=0.5)
        state = await harness.finish(timeout=600)
        lines = []
        for line in state.lines:
            lines.append({
                "start": line.get("start"),
                "end": line.get("end"),
                "speaker": line.get("speaker"),
                "text": line.get("text", ""),
                "translation": _plain_translation(line.get("translation")),
            })
        translations = [line["translation"] for line in lines if line["translation"]]
        if state.buffer_translation:
            translations.append(state.buffer_translation)
        elapsed = time.perf_counter() - started
        return {
            "name": name,
            "audio": str(audio_path.relative_to(ROOT)),
            "duration_seconds": harness.audio_position,
            "elapsed_seconds": round(elapsed, 3),
            "status": state.status,
            "transcript": state.committed_text or state.text,
            "buffer_transcription": state.buffer_transcription,
            "translations": translations,
            "translation_error": state.translation_error,
            "local_nllb_hook": local_hook,
            "lines": lines,
        }


async def run_smoke(checkpoint: Path, *, english_only=False, chinese_only=False) -> list[dict]:
    english_audio = ROOT / "logs" / "fixtures" / "sample_en.wav"
    chinese_audio = ROOT / "logs" / "fixtures" / "sample_zh.wav"
    cases = []
    if not chinese_only:
        options = streaming_options(checkpoint, source="en", target="zh")
        cases.append(await _run_case("english_to_chinese_nllb", english_audio, options, use_local_nllb=True))
    if not english_only:
        options = streaming_options(checkpoint, source="zh", direct_english=True)
        cases.append(await _run_case("chinese_to_english_whisper_translate", chinese_audio, options, use_local_nllb=False))
    for case in cases:
        if not case["transcript"]:
            raise RuntimeError(f"{case['name']} produced no recognized or translated text")
        if case["name"] == "english_to_chinese_nllb" and not case["translations"]:
            raise RuntimeError("English-to-Chinese smoke produced no NLLB translation")
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Verify the checkpoint and dependencies without audio smoke tests")
    parser.add_argument("--english-only", action="store_true", help="Run only English ASR plus NLLB Chinese translation")
    parser.add_argument("--chinese-only", action="store_true", help="Run only Whisper direct English translation on Chinese audio")
    args = parser.parse_args(argv)
    if args.english_only and args.chinese_only:
        parser.error("choose at most one of --english-only and --chinese-only")

    torch_before = torch_versions()
    inventory = runtime_inventory()
    checkpoint = download_checkpoint()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "prepared",
        "environment": inventory,
        "checkpoint": {"path": str(checkpoint), "bytes": checkpoint.stat().st_size,
                       "sha256": MODEL_SHA256, "valid": validate_checkpoint(checkpoint)},
        "cases": [],
    }
    try:
        if not args.prepare_only:
            ensure_ffmpeg_on_path()
            report["cases"] = asyncio.run(run_smoke(
                checkpoint, english_only=args.english_only, chinese_only=args.chinese_only
            ))
        torch_after = torch_versions()
        if torch_after != torch_before:
            raise RuntimeError(f"Torch package versions changed during setup: before={torch_before}, after={torch_after}")
        report["torch_versions_after"] = torch_after
        report["status"] = "passed" if report["cases"] else "prepared"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        torch_after = torch_versions()
        report["torch_versions_after"] = torch_after
        ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: checkpoint={checkpoint}; report={REPORT_PATH}")
    for case in report["cases"]:
        print(f"{case['name']}: {case['transcript']}")
        if case["translations"]:
            print("  translations: " + " | ".join(case["translations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
