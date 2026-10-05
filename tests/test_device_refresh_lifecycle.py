import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QDialog
from unittest.mock import patch

from app.device_refresh import DeviceRefreshBridge, start_device_refresh
from app.ui import SettingsDialog


class DeviceRefreshLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def spin_until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()
        self.assertTrue(predicate(), "Qt completion signal did not arrive")

    def test_delayed_enumeration_after_dialog_destruction_is_safe_and_does_not_reach_new_dialog(self):
        old_dialog = QDialog()
        old_bridge = DeviceRefreshBridge(old_dialog)
        old_results = []
        old_bridge.completed.connect(old_results.append)
        entered = threading.Event()
        release = threading.Event()

        def delayed_devices():
            entered.set()
            release.wait(2)
            return {"output": ["old output"], "input": ["old mic"]}

        old_worker = start_device_refresh(old_bridge, delayed_devices)
        self.assertTrue(entered.wait(1))
        old_dialog.deleteLater()
        QCoreApplication.sendPostedEvents(old_dialog, QEvent.Type.DeferredDelete)
        self.app.processEvents()

        new_dialog = QDialog()
        new_bridge = DeviceRefreshBridge(new_dialog)
        new_results = []
        new_bridge.completed.connect(new_results.append)
        release.set()
        old_worker.join(1)
        self.assertFalse(old_worker.is_alive())
        self.app.processEvents()
        self.assertEqual(old_results, [])
        self.assertEqual(new_results, [])
        new_dialog.close()

    def test_success_and_failure_are_delivered_through_bridge_and_finish_signal(self):
        parent = QDialog()
        bridge = DeviceRefreshBridge(parent)
        received = []
        failures = []
        finished = []
        bridge.completed.connect(received.append)
        bridge.failed.connect(failures.append)
        bridge.finished.connect(lambda: finished.append(True))
        ok = start_device_refresh(bridge, lambda: {"output": ["Speaker"], "input": ["Mic"]})
        ok.join(1)
        self.spin_until(lambda: bool(received) and bool(finished))
        self.assertEqual(received, [{"output": ["Speaker"], "input": ["Mic"]}])

        finished.clear()

        def fail():
            raise RuntimeError("enumeration failed")

        bad = start_device_refresh(bridge, fail)
        bad.join(1)
        self.spin_until(lambda: bool(failures) and bool(finished))
        self.assertEqual(failures, ["enumeration failed"])
        parent.close()

    def test_settings_dialog_restores_button_after_success_and_failure_without_changing_selection(self):
        dialog = SettingsDialog(
            {"output_device": "Missing Speaker", "mic_device": "Existing Mic"},
            {"output": ["Existing Speaker"], "input": ["Existing Mic"]},
        )
        try:
            with patch("app.audio.list_devices", return_value={
                "output": ["New Speaker"], "input": ["New Mic"],
            }):
                dialog.refresh_devices()
                self.assertFalse(dialog.device_refresh_button.isEnabled())
                self.spin_until(lambda: dialog._device_refresh_thread is None)
            self.assertTrue(dialog.device_refresh_button.isEnabled())
            self.assertEqual(dialog.output_device.currentData(), "Missing Speaker")
            self.assertIn("未连接", dialog.output_device.currentText())
            self.assertGreaterEqual(dialog.output_device.findData("New Speaker"), 0)

            with patch("app.audio.list_devices", side_effect=RuntimeError("device scan failed")):
                dialog.refresh_devices()
                self.assertFalse(dialog.device_refresh_button.isEnabled())
                self.spin_until(lambda: dialog._device_refresh_thread is None)
            self.assertTrue(dialog.device_refresh_button.isEnabled())
            self.assertIn("device scan failed", dialog.device_refresh_status.text())
            self.assertEqual(dialog.output_device.currentData(), "Missing Speaker")
        finally:
            dialog.close()

    def test_closed_settings_dialog_cannot_apply_its_late_results_to_a_new_dialog(self):
        old_dialog = SettingsDialog({}, {"output": [], "input": []})
        entered = threading.Event()
        release = threading.Event()

        def delayed_devices():
            entered.set()
            release.wait(2)
            return {"output": ["Late Speaker"], "input": ["Late Mic"]}

        with patch("app.audio.list_devices", side_effect=delayed_devices):
            old_dialog.refresh_devices()
            worker = old_dialog._device_refresh_thread
            self.assertTrue(entered.wait(1))
            old_dialog.deleteLater()
            QCoreApplication.sendPostedEvents(old_dialog, QEvent.Type.DeferredDelete)
            self.app.processEvents()

            new_dialog = SettingsDialog({}, {"output": [], "input": []})
            release.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.app.processEvents()
            self.assertEqual(new_dialog.output_device.findData("Late Speaker"), -1)
            self.assertEqual(new_dialog.mic_device.findData("Late Mic"), -1)
            new_dialog.close()


if __name__ == "__main__":
    unittest.main()
