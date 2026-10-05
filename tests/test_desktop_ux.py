import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.ui import MainWindow


class DesktopUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(
            settings={
                "source_mode": "system", "source_language": "auto", "target_language": "zh",
                "asr_model": "small", "translation_mode": "local", "font_size": 24,
                # Legacy values must affect the subtitle overlay only.
                "opacity": 0.72, "always_on_top": True, "save_records": True,
            },
            devices={"output": [], "input": []},
        )

    def tearDown(self):
        self.window.close()

    def test_main_window_is_opaque_and_never_stays_on_top(self):
        self.assertAlmostEqual(self.window.windowOpacity(), 1.0)
        self.assertFalse(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(self.window.subtitle_overlay.preferences()["overlay_background_opacity"], 72)
        self.assertFalse(self.window.windowIcon().isNull())
        stylesheet = self.window.styleSheet()
        self.assertIn("theme-check.svg", stylesheet)
        self.assertIn("theme-arrow-down.svg", stylesheet)
        self.assertTrue(Path("app/assets/theme-check.svg").is_file())
        self.assertTrue(Path("app/assets/theme-arrow-down.svg").is_file())

    def test_overlay_toggle_does_not_resize_or_replace_main_window(self):
        self.window.show()
        self.app.processEvents()
        original_size = self.window.size()
        original_page = self.window.stack.currentWidget()

        self.window.toggle_compact_mode()
        self.app.processEvents()

        self.assertTrue(self.window.compact_mode)
        self.assertEqual(self.window.size(), original_size)
        self.assertIs(self.window.stack.currentWidget(), original_page)
        self.assertTrue(self.window.source_mode_field.isVisible())
        self.assertTrue(self.window.settings_button.isVisible())
        self.assertTrue(self.window.subtitle_overlay.isVisible())

        self.window.toggle_compact_mode()
        self.app.processEvents()
        self.assertFalse(self.window.compact_mode)
        self.assertFalse(self.window.subtitle_overlay.isVisible())
        self.assertEqual(self.window.size(), original_size)

    def test_overlay_receives_latest_caption_and_session_state(self):
        row = {"id": "r1", "source": "hello", "translation": "你好", "start": 0, "end": 1}
        self.window.update_caption([row], draft="draft", translation_draft="译文草稿")
        self.window.set_running(True, paused=True)
        overlay = self.window.subtitle_overlay
        self.assertEqual(overlay._current_row["id"], "r1")
        self.assertEqual(overlay.source_label.text(), "hello")
        self.assertIn("draft", overlay.draft_label.text())
        self.assertIn("译文草稿", overlay.draft_label.text())
        self.assertEqual(overlay.pause_button.text(), "继续")
        self.assertTrue(overlay.pause_button.isEnabled())

    def test_stop_pending_disables_overlay_pause_until_session_stops(self):
        self.window.set_running(True)
        self.assertTrue(self.window.subtitle_overlay.pause_button.isEnabled())
        self.window._request_stop()
        self.assertFalse(self.window.subtitle_overlay.pause_button.isEnabled())

    def test_clearing_transcript_clears_overlay_drafts(self):
        self.window.update_caption([{"id": "r1", "source": "hello", "translation": "你好"}], draft="draft text")
        self.assertIn("draft text", self.window.subtitle_overlay.draft_label.text())
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        with patch("app.ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.confirm_clear()
        self.assertEqual(self.window.subtitle_overlay.draft_label.text(), "")

    def test_overlay_preferences_and_translation_requests_are_forwarded(self):
        preferences = []
        translation = []
        self.window.overlay_preferences_changed.connect(preferences.append)
        self.window.translation_enabled_requested.connect(translation.append)

        self.window.subtitle_overlay.preferences_changed.emit({"overlay_background_opacity": 80})
        self.window.subtitle_overlay.translation_enabled_changed.emit(False)

        self.assertEqual(preferences, [{"overlay_background_opacity": 80}])
        self.assertEqual(translation, [False])

    def test_closing_overlay_only_closes_caption_display(self):
        self.window.show()
        self.window.set_running(True)
        self.window.subtitle_overlay.show()
        self.window.subtitle_overlay.close()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.running)
        self.assertFalse(self.window.subtitle_overlay.isVisible())

    def test_overlay_return_control_restores_hidden_main_window(self):
        self.window.show()
        self.window.hide()
        self.window.subtitle_overlay.control_requested.emit("show_main")
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())

    def test_background_and_restore_controls_have_stable_insertion_area(self):
        self.assertIsNotNone(self.window.utility_bar)
        self.assertIsNotNone(self.window.utility_layout)
        self.assertGreaterEqual(self.window.utility_layout.indexOf(self.window.tools_button), 0)
        self.assertGreaterEqual(self.window.utility_layout.indexOf(self.window.background_button), 0)
        requested = []
        self.window.background_requested.connect(lambda: requested.append(True))
        self.window.background_button.click()
        self.assertEqual(requested, [True])


if __name__ == "__main__":
    unittest.main()
