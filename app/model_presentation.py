"""Human-readable model labels and requested runtime location summaries."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from PyQt6.QtCore import Qt

from app.settings import ROOT


_MODEL_CHOICES = (
    ("Tiny · 轻量", "tiny"),
    ("Tiny EN", "tiny.en"),
    ("Base", "base"),
    ("Base EN", "base.en"),
    ("Small", "small"),
    ("Small EN", "small.en"),
    ("Medium", "medium"),
    ("Medium EN", "medium.en"),
    ("Large v1", "large-v1"),
    ("Large v2", "large-v2"),
    ("Large v3", "large-v3"),
    ("Large v3 Turbo", "large-v3-turbo"),
)
_LABELS = dict((code, label) for label, code in _MODEL_CHOICES)
_BACKEND_LABELS = {
    "auto": "自动选择",
    "faster-whisper": "Faster Whisper",
    "whisper": "原库 Whisper",
    "mlx-whisper": "MLX Whisper",
    "funasr": "FunASR",
    "canary": "Canary",
    "qwen3-streaming": "Qwen3 Streaming",
    "voxtral": "Voxtral",
    "voxtral-mlx": "Voxtral MLX",
    "qwen3-vllm": "Qwen3 vLLM",
    "qwen3-vllm-metal": "Qwen3 vLLM Metal",
}


def _settings_parts(settings):
    settings = settings if isinstance(settings, dict) else {}
    wlk = settings.get("wlk")
    return settings, wlk if isinstance(wlk, dict) else {}


def _local_path(value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else ROOT / path
    except (OSError, RuntimeError, ValueError):
        return None


def _model_file(size: str, settings=None) -> tuple[bool, str]:
    """Check only known, shallow local paths; never walk model directories."""
    settings, wlk = _settings_parts(settings)
    backend = str(wlk.get("backend") or "auto").strip().lower()
    families = ("native",) if backend == "whisper" else (
        ("faster",) if backend == "faster-whisper" else ("faster", "native")
    )
    configured_size = str(wlk.get("model_size") or settings.get("asr_model") or "").strip()
    is_configured_size = str(size).strip() == configured_size
    explicit_path = wlk.get("model_path") if is_configured_size else None
    if explicit_path:
        path = _local_path(explicit_path)
        if path is not None and path.is_file():
            return True, "指定模型文件"
        return False, "指定模型文件未找到"

    explicit_dir = wlk.get("model_dir") if is_configured_size else None
    if explicit_dir:
        path = _local_path(explicit_dir)
        if path is not None and path.is_dir():
            for family in families:
                if family == "faster" and (path / "model.bin").is_file():
                    return True, "指定目录中的 Faster Whisper 文件"
                if family == "native" and (path / f"{size}.pt").is_file():
                    return True, "指定目录中的原库 Whisper 文件"
        return False, "指定模型目录中未找到已识别的模型文件"

    for family in families:
        if family == "faster":
            faster_dir = ROOT / "models" / f"whisper-{size}"
            if (faster_dir / "model.bin").is_file():
                return True, "Faster Whisper model.bin"
        else:
            native_file = ROOT / "models" / "native-whisper" / f"{size}.pt"
            if native_file.is_file():
                return True, "原库 Whisper .pt"
    return False, "未发现模型文件"


def model_choice_label(size, settings=None) -> str:
    """Return a compact label; detailed readiness belongs in its tooltip."""
    code = str(size or "").strip()
    base = _LABELS.get(code, code or "未知模型")
    ready, reason = _model_file(code, settings)
    if ready:
        return f"{base} · 已发现文件"
    return f"{base} · 未安装"


def populate_model_combo(combo, settings, selected=None):
    """Populate a combo with all established model codes, installed choices first."""
    settings, wlk = _settings_parts(settings)
    current = selected
    if current is None:
        current = wlk.get("model_size") or settings.get("asr_model", "medium")
    current = str(current or "").strip()
    status_settings = {**settings, "wlk": {**wlk, "model_size": current}}

    choices = list(_MODEL_CHOICES)
    if current and current not in _LABELS:
        # Keep a previously configured non-catalog value visible and selectable.
        choices.append((f"{current} · 当前配置（本地文件状态未知）", current))

    ordered = sorted(enumerate(choices), key=lambda item: (
        not _model_file(item[1][1], status_settings)[0], item[0]
    ))
    combo.clear()
    for _, (base_label, code) in ordered:
        label = model_choice_label(code, status_settings) if code in _LABELS else base_label
        combo.addItem(label, code)
        ready, reason = _model_file(code, status_settings)
        detail = f"本地模型文件：{reason if ready else reason}。模型是否已加载未知。"
        combo.setItemData(combo.count() - 1, detail, Qt.ItemDataRole.ToolTipRole)

    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.count():
        combo.setCurrentIndex(0)


def _endpoint(value) -> tuple[str, str]:
    """Return a credential-free host:port and local/remote classification."""
    raw = str(value or "").strip()
    if not raw:
        return "", "未配置"
    try:
        parsed = urlsplit(raw if "://" in raw else "//" + raw)
        host = (parsed.hostname or "").strip().lower()
        port = parsed.port
    except (ValueError, TypeError):
        return "", "位置无法判断"
    if not host:
        return "", "位置无法判断"
    shown_host = f"[{host}]" if ":" in host else host
    authority = shown_host + (f":{port}" if port is not None else "")
    local = host in {"localhost", "localhost.localdomain"}
    if not local:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
    return authority, "本机外部服务" if local else "远程服务"


def _location_summary(value, *, configured_label):
    if not str(value or "").strip():
        return configured_label
    address, location = _endpoint(value)
    return f"{location} {address}".strip() if address else location


def runtime_summary(settings) -> str:
    """Return the short requested runtime state for compact status areas."""
    settings, wlk = _settings_parts(settings)
    size = str(wlk.get("model_size") or settings.get("asr_model") or "medium")
    backend = str(wlk.get("backend") or "auto").strip().lower()
    backend_label = _BACKEND_LABELS.get(backend, backend or "自动选择")
    asr_location = _location_summary(settings.get("server_url"), configured_label="本软件本地")
    lines = [f"请求：{_LABELS.get(size, size)} / {backend_label} · {asr_location}"]

    if str(settings.get("translation_mode", "local")).strip().lower() == "off":
        lines.append("翻译：关闭")
    else:
        provider = str(settings.get("translation_provider") or "nllb").strip().lower()
        if provider in {"lmstudio", "llm"}:
            endpoint = _location_summary(settings.get("llm_url"), configured_label="位置未知")
            lines.append(f"翻译：LM Studio（{endpoint}）")
        else:
            lines.append("翻译：NLLB（本地）")
    return "\n".join(lines)


def runtime_details(settings) -> str:
    """Return safe tooltip details, including file state and unknown load state."""
    settings, wlk = _settings_parts(settings)
    size = str(wlk.get("model_size") or settings.get("asr_model") or "medium")
    backend = str(wlk.get("backend") or "auto").strip().lower()
    backend_label = _BACKEND_LABELS.get(backend, backend or "自动选择")
    ready, reason = _model_file(size, settings)
    file_state = reason if ready else reason
    lines = [
        runtime_summary(settings),
        f"ASR 请求模型：{size} / {backend_label}。",
        f"本地文件检查：{file_state}。模型是否已加载未知。",
    ]
    if str(settings.get("translation_mode", "local")).strip().lower() != "off":
        provider = str(settings.get("translation_provider") or "nllb").strip().lower()
        if provider in {"lmstudio", "llm"}:
            lines.append("LM Studio 使用的模型：" + str(settings.get("llm_model") or "未指定") + "；加载状态未知。")
        else:
            lines.append("NLLB 请求位置：本地引擎；模型加载状态未知。")
    return "\n".join(lines)
