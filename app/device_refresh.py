"""Qt signal bridge for safe, non-blocking device enumeration."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal


class DeviceRefreshBridge(QObject):
    """Deliver enumeration results on the GUI thread while owned by its dialog."""

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


def _safe_emit(bridge: DeviceRefreshBridge, signal_name: str, value: Any = None) -> None:
    try:
        signal = getattr(bridge, signal_name)
        if signal_name == "finished":
            signal.emit()
        else:
            signal.emit(value)
    except RuntimeError:
        # The owning dialog may have closed while device enumeration was blocked.
        # Qt disconnects its slots when the bridge is destroyed; ignore the late result.
        return


def start_device_refresh(
    bridge: DeviceRefreshBridge,
    enumerate_devices: Callable[[], dict[str, list[str]]],
) -> threading.Thread:
    """Enumerate candidates on a daemon thread and relay only through ``bridge``."""

    def run() -> None:
        try:
            devices = enumerate_devices()
        except Exception as exc:
            _safe_emit(bridge, "failed", str(exc))
        else:
            _safe_emit(bridge, "completed", devices)
        finally:
            _safe_emit(bridge, "finished")

    worker = threading.Thread(target=run, name="DeviceRefresh", daemon=True)
    worker.start()
    return worker
