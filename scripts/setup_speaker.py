"""Prepare and smoke-test the optional Windows NeMo Sortformer runtime.

The isolated runtime reuses the application's verified Torch/CUDA install via
system-site-packages, while installing NeMo and its Python dependencies under
runtime/speaker. The app environment and its pinned speech/Qt packages stay
untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "speaker"
PYTHON = RUNTIME / "Scripts" / "python.exe"
MODEL_DIR = ROOT / "models" / "sortformer"
MODEL_FILE = MODEL_DIR / "diar_streaming_sortformer_4spk-v2.nemo"
MODEL_REPO = "nvidia/diar_streaming_sortformer_4spk-v2"
MODEL_SIZE = 471_367_680
MODEL_SHA256 = "b371afce2c4958186469df33d939936b9746c89f38b10a69cfd2c61254e83329"
_NEMO_ASR_PACKAGES = [
    "nemo-toolkit[asr]>=3.0,<4",
    "onnx>=1.22.0",
    "ml-dtypes",
    "aistore",
    "cuda-bindings",
    "smart-open",
    "tensorboard",
    "text-unidecode",
    "wrapt",
    "braceexpand",
    "einops",
    "kaldialign",
    "lhotse>=1.33.0",
    "sacrebleu",
    "whisper-normalizer",
    "datasets>=3.2.0",
    "pandas",
    "wandb",
    "webdataset>=0.2.86",
    "nv-one-logger-core>=2.3.1",
    "nv-one-logger-training-telemetry>=2.3.1",
    "nv-one-logger-pytorch-lightning-integration>=2.3.1",
    "strenum",
    "overrides",
    "toml",
    "intervaltree",
    "sortedcontainers",
    "cytoolz",
    "toolz",
    "python-dateutil",
    "cuda-pathfinder",
    "multiprocess",
    "dill",
    "xxhash",
    "pyarrow",
    "pytorch-lightning<=2.4.0,>2.2.1",
    "lightning<=2.4.0,>2.2.1",
    "lightning-utilities",
    "torchmetrics>=0.11.0",
]


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to prepare the isolated NeMo runtime; install uv first")
    return uv


def install_runtime() -> Path:
    """Create NeMo runtime while reusing, never replacing, app Torch/CUDA."""
    if not PYTHON.exists():
        subprocess.run(
            [_uv(), "venv", "--python", str(ROOT / ".venv" / "Scripts" / "python.exe"),
             "--system-site-packages", str(RUNTIME)],
            cwd=ROOT,
            check=True,
        )
    # A nested venv's --system-site-packages sees the base runtime, while the
    # verified speech stack lives in the app venv. Add that site-packages path
    # explicitly so the speaker process reuses its exact Torch/CUDA binaries.
    shared = ROOT / ".venv" / "Lib" / "site-packages"
    local_packages = RUNTIME / "Lib" / "site-packages"
    local_packages.mkdir(parents=True, exist_ok=True)
    (local_packages / "whisperlivekit-app-runtime.pth").write_text(
        str(shared.resolve()) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [_uv(), "pip", "install", "--no-deps", "--python", str(PYTHON),
         *_NEMO_ASR_PACKAGES],
        cwd=ROOT,
        check=True,
    )
    app_probe = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-c",
         "import json,torch; print(json.dumps({'version':torch.__version__,'cuda':torch.cuda.is_available(),'path':torch.__file__}))"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    speaker_probe = subprocess.run(
        [str(PYTHON), "-c", r'''
import importlib.metadata as metadata, json, torch
import fastapi, uvicorn, faster_whisper, nllw, torchaudio
import app.server
from nemo.collections.asr.models import SortformerEncLabelModel
from nemo.collections.asr.modules import AudioToMelSpectrogramPreprocessor
print(json.dumps({"torch": torch.__version__, "cuda": torch.cuda.is_available(), "torch_path": torch.__file__,
 "torchaudio": metadata.version("torchaudio"), "faster_whisper": metadata.version("faster-whisper"),
 "nllw": metadata.version("nllw"), "nemo_toolkit": metadata.version("nemo_toolkit"),
 "lightning": metadata.version("lightning"), "pytorch_lightning": metadata.version("pytorch-lightning"),
 "torchmetrics": metadata.version("torchmetrics"), "fastapi": metadata.version("fastapi"), "uvicorn": metadata.version("uvicorn")}))
'''],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    import json
    app_environment = json.loads(app_probe.stdout.strip())
    speaker_environment = json.loads(speaker_probe.stdout.strip().splitlines()[-1])
    if speaker_environment["torch"] != app_environment["version"]:
        raise RuntimeError(f"Isolated NeMo runtime changed Torch: {speaker_environment['torch']} != {app_environment['version']}")
    if Path(speaker_environment["torch_path"]).resolve() != Path(app_environment["path"]).resolve():
        raise RuntimeError("Isolated NeMo runtime is not importing the app's verified Torch installation")
    if speaker_environment["cuda"] != app_environment["cuda"]:
        raise RuntimeError("Isolated NeMo runtime reports a different CUDA availability than the app environment")
    (RUNTIME / "speaker-runtime-dependencies.json").write_text(
        json.dumps(speaker_environment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return PYTHON


def download_checkpoint() -> Path:
    """Download the official model checkpoint to the exact WLK local path."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    def checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(8 * 1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    if MODEL_FILE.is_file() and MODEL_FILE.stat().st_size == MODEL_SIZE:
        if checksum(MODEL_FILE) == MODEL_SHA256:
            return MODEL_FILE
        raise RuntimeError(f"Sortformer checkpoint SHA-256 mismatch: {MODEL_FILE}")
    temporary = MODEL_FILE.with_suffix(".nemo.partial")
    url = f"https://huggingface.co/{MODEL_REPO}/resolve/main/diar_streaming_sortformer_4spk-v2.nemo?download=true"
    subprocess.run(
        ["curl.exe", "--fail", "--location", "--retry", "3", "--retry-all-errors",
         "--max-time", "2400", "--show-error", "--output", str(temporary), url],
        cwd=ROOT,
        check=True,
    )
    if temporary.stat().st_size != MODEL_SIZE:
        raise RuntimeError(f"Sortformer checkpoint size mismatch: {temporary.stat().st_size} != {MODEL_SIZE}; partial retained")
    actual_hash = checksum(temporary)
    if actual_hash != MODEL_SHA256:
        raise RuntimeError(f"Sortformer checkpoint SHA-256 mismatch: {actual_hash}; partial retained")
    temporary.replace(MODEL_FILE)
    return MODEL_FILE


def smoke_test() -> dict:
    """Construct WLK's streaming backend and infer on a short audio fixture."""
    if not PYTHON.exists():
        raise RuntimeError("NeMo runtime is missing; run setup_speaker.py --install first")
    if not MODEL_FILE.is_file():
        raise RuntimeError(f"Sortformer checkpoint is missing: {MODEL_FILE}")
    # Keep all logs within the isolated runtime and use the upstream backend's
    # own streaming preprocessor, state and diarization implementation.
    code = r'''
import asyncio, json, sys
from pathlib import Path
import numpy as np
import soundfile as sf

root = Path.cwd()
sys.path.insert(0, str(root / "upstream"))
import fastapi, uvicorn, faster_whisper, nllw, torchaudio
import app.server
from whisperlivekit.diarization.sortformer_backend import SortformerDiarization, SortformerDiarizationOnline

shared = SortformerDiarization(model_path=str(root / "models/sortformer/diar_streaming_sortformer_4spk-v2.nemo"))
online = SortformerDiarizationOnline(shared_model=shared, max_speakers=2)
fixture = root / "upstream/tests/fixtures/sortformer_2spk"
speaker_a, rate_a = sf.read(fixture / "6930-75918-0000.flac", dtype="float32")
speaker_b, rate_b = sf.read(fixture / "7902-96591-0000.flac", dtype="float32")
assert rate_a == rate_b == 16000
silence = np.zeros(8000, dtype=np.float32)
overlap = 0.5 * speaker_a[:len(speaker_b)] + 0.5 * speaker_b
signal = np.concatenate([speaker_a, silence, speaker_b, silence, speaker_a, silence, overlap])
signal = np.pad(signal, (0, (-len(signal)) % 16000))
async def run():
    segments = []
    for start in range(0, len(signal), 16000):
        online.insert_audio_chunk(signal[start:start + 16000])
        segments.extend(await online.diarize())
    return segments
segments = asyncio.run(run())
def dominant(start, end):
    duration = {}
    for segment in segments:
        overlap = max(0.0, min(end, segment.end) - max(start, segment.start))
        if overlap:
            duration[int(segment.speaker)] = duration.get(int(segment.speaker), 0.0) + overlap
    return max(duration, key=duration.get)
labels = [dominant(0.25, 3.25), dominant(4.25, 5.85), dominant(7.0, 9.85)]
assert labels == [0, 1, 0], f"two-speaker fixture labels were {labels}"
print(json.dumps({"device": str(shared.diar_model.device), "chunk_seconds": online.chunk_duration_seconds,
                  "speaker_count": len(set(int(x.speaker) for x in segments)), "speaker_order": labels,
                  "segments": [{"speaker": int(x.speaker), "start": x.start, "end": x.end} for x in segments]}))
'''
    result = subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=900,
    )
    if result.returncode:
        raise RuntimeError(f"Sortformer smoke test failed (exit {result.returncode}):\n{result.stderr[-8000:]}")
    output_lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    if not output_lines:
        raise RuntimeError(f"Sortformer smoke test emitted no result: {result.stdout[-3000:]}")
    import json
    report = json.loads(output_lines[-1])
    report["runtime_python"] = str(PYTHON)
    (RUNTIME / "speaker-runtime-ready.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Create runtime and install NeMo without replacing app Torch")
    parser.add_argument("--download", action="store_true", help="Download official local Sortformer checkpoint")
    parser.add_argument("--smoke", action="store_true", help="Construct model and run one short streaming inference")
    parser.add_argument("--all", action="store_true", help="Install, download, and run the smoke test")
    args = parser.parse_args()
    if args.all:
        args.install = args.download = args.smoke = True
    if not (args.install or args.download or args.smoke):
        parser.error("choose --install, --download, --smoke, or --all")
    if args.install:
        print(f"NeMo runtime ready: {install_runtime()}", flush=True)
    if args.download:
        print(f"Sortformer checkpoint ready: {download_checkpoint()}", flush=True)
    if args.smoke:
        print(smoke_test(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
