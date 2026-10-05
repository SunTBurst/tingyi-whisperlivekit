"""User registry for external model directories; external files stay untouched."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.settings import ROOT

REGISTRY_PATH = ROOT / "data" / "model_registry.json"


def read_model_registry(registry_path: str | Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    path = Path(registry_path)
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("Model registry must be a JSON list")
    return [dict(row) for row in value if isinstance(row, dict)]


def register_external_model(
    path: str | Path,
    *,
    name: str,
    kind: str,
    backend: str,
    registry_path: str | Path = REGISTRY_PATH,
    model_format: str | None = None,
    size_bytes: int | None = None,
) -> dict[str, Any]:
    """Register an already existing directory without copying or changing it."""
    target = Path(path).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ValueError(f"External model path must be a directory: {target}")
    label = str(name).strip() or target.name
    if not str(kind).strip() or not str(backend).strip():
        raise ValueError("Model purpose and backend are required")
    registry_file = Path(registry_path)
    rows = read_model_registry(registry_file)
    row = {
        "id": f"external:{target}",
        "name": label,
        "kind": str(kind).strip(),
        "backend": str(backend).strip(),
        "path": str(target),
        "format": str(model_format or "unknown"),
        "size_bytes": size_bytes if size_bytes is not None else _directory_size(target),
        "source": "external",
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "files_present": True,
        "validated": False,
        "dependencies_installed": None,
        "loaded": False,
    }
    rows = [existing for existing in rows if existing.get("id") != row["id"]]
    rows.append(row)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_file.with_suffix(registry_file.suffix + ".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(registry_file)
    return dict(row)


def _directory_size(path: Path) -> int | None:
    total = 0
    try:
        for file in path.rglob("*"):
            if file.is_file():
                total += file.stat().st_size
    except OSError:
        return None
    return total


def validate_external_model(record: dict[str, Any]) -> dict[str, Any]:
    """Check the expected local file shape and report dependencies separately."""
    path = Path(str(record.get("path") or ""))
    files = [item for item in path.rglob("*") if item.is_file()] if path.is_dir() else []
    names = {item.name.lower() for item in files}
    kind = str(record.get("kind") or "")
    backend = str(record.get("backend") or "")
    if backend == "faster-whisper" or kind == "translation":
        valid = {"config.json", "model.bin"}.issubset(names)
    elif backend == "whisper" or kind == "native-whisper":
        valid = any(item.suffix.lower() in {".pt", ".pth"} for item in files)
    elif "nemo" in backend or kind == "speaker":
        valid = any(item.suffix.lower() == ".nemo" for item in files)
    else:
        valid = bool(files)
    return {
        "files_present": bool(files),
        "validated": bool(valid),
        "dependencies_installed": None,
        "loaded": False,
        "validation_message": "文件结构通过" if valid else "未识别到该用途/后端要求的模型文件",
    }
