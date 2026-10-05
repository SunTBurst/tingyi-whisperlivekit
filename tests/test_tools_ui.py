import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QWidget

from app.tools_ui import (
    ToolsDialog,
    _cli_uses_speaker_runtime,
    _parse_windows_arguments,
    _python,
)
from app.settings import ROOT
from app.ui import MainWindow


class FakeServer(QObject):
    changed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.active = False
        self.ready = False
        self.url = ""
        self.ensure_url = "http://127.0.0.1:8000"
        self.ensure_calls = []
        self.stopped = False

    def ensure(self, settings, on_ready, on_error):
        self.ensure_calls.append(settings)
        self.url = self.ensure_url
        self.active = True
        self.ready = True
        self.changed.emit("原库服务就绪：" + self.url)
        on_ready(self.url)

    def stop(self):
        self.stopped = True
        self.active = False
        self.ready = False
        self.changed.emit("原库服务已停止")


class FakeController(QObject):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.server = FakeServer()
        self.starts = []
        self.new_windows = 0
        self.original_view_action=QAction('显示原始听写',self)
        self.original_view_action.setCheckable(True)
        self.long_mode_action=QAction('长会议模式',self)
        self.long_mode_action.setCheckable(True)
        for name in ('show_glossary','show_participants','show_ai','reprocess_glossary',
                     'cancel_history_rewrite','show_saved_records','manual_save','show_recovery'):
            setattr(self,name,lambda:None)

    def start(self, *args):
        self.starts.append(args)

    def new_window(self):
        self.new_windows += 1


class ToolsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.choose_export_format=lambda:None
        self.window._config_snapshot = lambda: {"source_language": "en", "target_language": "zh", "asr_model": "medium",
                                                "wlk": {"backend": "faster-whisper", "model_size": "medium", "lan": "en"},
                                                "context": "term", "allow_downloads": False}
        self.controller = FakeController(self.window)
        self.dialog = ToolsDialog(self.controller)
        self.addCleanup(self.dialog.close)

    def test_service_buttons_connect_open_stop_and_new_window(self):
        self.dialog.start_server_button.click()
        self.assertEqual(self.controller.server.ensure_calls[0]["asr_model"], "medium")
        self.assertEqual(self.dialog.service_url.text(), "http://127.0.0.1:8000")
        self.assertFalse(self.dialog.model_remove_button.isEnabled())
        with patch("app.tools_ui.QDesktopServices.openUrl") as open_url:
            self.dialog.open_web_button.click()
            open_url.assert_called_once()
        self.dialog.new_window_button.click()
        self.assertEqual(self.controller.new_windows, 1)
        self.dialog.stop_server_button.click()
        self.assertTrue(self.controller.server.stopped)
        self.assertTrue(self.dialog.model_remove_button.isEnabled())

    def test_single_file_button_starts_non_realtime_session_and_closes_dialog(self):
        with patch("app.tools_ui.QFileDialog.getOpenFileName", return_value=(r"C:\audio files\meeting.wav", "")):
            self.dialog.import_file_button.click()
        self.assertEqual(self.controller.starts[0][1:], (r"C:\audio files\meeting.wav", False))
        self.assertEqual(self.dialog.result(), self.dialog.DialogCode.Accepted)

    def test_batch_format_list_covers_transcription_api_formats(self):
        formats = {self.dialog.batch_format.itemData(index) for index in range(self.dialog.batch_format.count())}
        self.assertEqual(formats, {"text", "json", "verbose_json", "diarized_json", "srt", "vtt"})

    def test_windows_argument_parser_preserves_quoted_backslash_paths(self):
        self.assertEqual(
            _parse_windows_arguments('--audio "C:\\Program Files\\recordings\\a.wav" --language en'),
            ["--audio", "C:\\Program Files\\recordings\\a.wav", "--language", "en"],
        )

    def test_cli_runtime_uses_isolated_nemo_python_only_for_sortformer_audio_commands(self):
        settings = {"wlk": {"diarization": True, "diarization_backend": "sortformer"}}
        self.assertTrue(_cli_uses_speaker_runtime("bench", ["--model=small"], settings))
        self.assertTrue(_cli_uses_speaker_runtime("diagnose", ["--diarization"], {}))
        self.assertFalse(_cli_uses_speaker_runtime("pull", ["sortformer-4spk-v2"], settings))
        self.assertFalse(_cli_uses_speaker_runtime("bench", ["--config={\"diarization\":true,\"diarization_backend\":\"diart\"}"], {}))
        with tempfile.TemporaryDirectory(prefix="tool-runtime-fixture-") as directory:
            root = Path(directory)
            app_python = root / ".venv" / "Scripts" / "python.exe"
            speaker_python = root / "runtime" / "speaker" / "Scripts" / "python.exe"
            for executable in (app_python, speaker_python):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("executable placeholder", encoding="utf-8")
            with patch("app.tools_ui.ROOT", root):
                self.assertEqual(Path(_python()), app_python)
                self.assertEqual(_python(speaker_runtime=True), str(speaker_python))

        with tempfile.TemporaryDirectory(prefix="tool-runtime-missing-") as directory:
            with patch("app.tools_ui.ROOT", Path(directory)):
                self.assertEqual(_python(), sys.executable)

    def test_cli_config_and_explicit_backend_control_speaker_runtime_choice(self):
        self.assertTrue(_cli_uses_speaker_runtime(
            "bench", ["--config", '{"diarization":true,"diarization_backend":"sortformer"}'], {}
        ))
        self.assertFalse(_cli_uses_speaker_runtime(
            "bench", ["--diarization", "--diarization-backend=diart"], {"wlk": {"diarization_backend": "sortformer"}}
        ))

    def test_paused_meeting_can_select_external_small_while_medium_service_remains_active(self):
        window = MainWindow(
            settings={"source_mode": "system", "source_language": "en", "target_language": "zh", "asr_model": "medium",
                      "wlk": {"backend": "faster-whisper", "model_size": "medium", "model_dir": "old-medium"}},
            devices={"input": [], "output": []},
        )
        window.running = True
        window.paused = True
        emitted = []
        window.config_changed.connect(emitted.append)
        controller = FakeController(window)
        controller.server.active = True
        controller.server.ready = True
        dialog = ToolsDialog(controller)
        self.addCleanup(dialog.close)
        self.addCleanup(window.close)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "external-small"
            path.mkdir()
            (path / "config.json").write_text("{}", encoding="utf-8")
            (path / "model.bin").write_bytes(b"fake")
            model = {"name": "whisper-small", "kind": "asr", "backend": "faster-whisper", "path": str(path),
                     "local_path": str(path), "source": "external", "installed": True, "validated": True,
                     "dependencies_installed": None}
            item = QListWidgetItem("External Small")
            item.setData(256, model)
            dialog.model_list.addItem(item)
            dialog.model_list.setCurrentItem(item)
            dialog.use_selected_model()
            self.assertEqual(window.model_combo.currentData(), "small")
            self.assertEqual(window.settings["asr_model"], "small")
            self.assertEqual(window.settings["wlk"]["model_size"], "small")
            self.assertEqual(window.settings["wlk"]["model_dir"], str(path))
            self.assertIsNone(window.settings["wlk"]["model_path"])
            self.assertEqual(emitted[-1]["asr_model"], "small")
            self.assertEqual(emitted[-1]["wlk"]["model_size"], "small")
            self.assertEqual(emitted[-1]["wlk"]["model_dir"], str(path))
            self.assertEqual(emitted[-1]["wlk"]["backend"], "faster-whisper")
            self.assertTrue(controller.server.active)

    def test_speaker_runtime_request_fails_clearly_when_runtime_is_absent(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.tools_ui.ROOT", Path(directory)):
            with self.assertRaises(FileNotFoundError):
                _python(speaker_runtime=True)

    def test_batch_ensures_stopped_remote_service_and_writes_request(self):
        self.controller.server.url = "http://stale-local-url"
        self.controller.server.ensure_url = "https://remote.example/wlk"
        self.dialog.batch_list.addItem(r"C:\meeting.wav")
        with patch.object(self.dialog, "_start_process", return_value=object()) as start_process:
            self.dialog.start_batch()
        self.assertEqual(len(self.controller.server.ensure_calls), 1)
        args, output, label = start_process.call_args.args
        self.assertEqual(args[:4], ["-u", "-m", "app.batch_job", "--request"])
        self.assertEqual(label, "批量转写")
        import json
        request_path = args[4]
        request = json.loads(open(request_path, encoding="utf-8").read())
        self.assertEqual(request["base"], "https://remote.example/wlk")
        self.assertEqual(request["paths"], [r"C:\meeting.wav"])


if __name__ == "__main__":
    unittest.main()
