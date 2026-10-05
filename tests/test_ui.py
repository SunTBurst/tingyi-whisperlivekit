import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QListWidget

from app.ui import MainWindow


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(
            settings={
                "source_mode": "system",
                "source_language": "auto",
                "target_language": "zh",
                "asr_model": "small",
                "translation_mode": "local",
                "output_device": None,
                "mic_device": None,
                "font_size": 24,
                "opacity": 0.94,
                "always_on_top": False,
                "save_records": True,
            },
            devices={"output": ["扬声器 A"], "input": ["麦克风 A"]},
        )

    def tearDown(self):
        self.window.close()

    def test_source_auto_cannot_become_translation_target(self):
        before = self.window.target_language.currentData()
        self.window.swap_languages()
        self.assertEqual(self.window.source_language.currentData(), "auto")
        self.assertEqual(self.window.target_language.currentData(), before)
        self.assertIn("先选择识别语言", self.window.toast_label.text())

    def test_caption_rows_update_by_id_without_duplicates(self):
        self.window.update_caption(
            [{"id": "row-1", "source": "hello", "translation": "你好", "start": 0, "end": 1, "language": "en"}]
        )
        self.window.update_caption(
            [{"id": "row-1", "source": "hello everyone", "translation": "大家好", "start": 0, "end": 2, "language": "en"}]
        )
        self.assertEqual(len(self.window.caption_rows), 1)
        self.assertEqual(self.window.caption_rows["row-1"]["translation"], "大家好")
        self.assertEqual(self.window.caption_list.count(), 1)

    def test_full_caption_snapshot_reuses_unchanged_cards_and_history_items(self):
        row = {"id": "row-1", "source": "hello", "translation": "你好", "start": 0, "end": 1, "language": "en"}
        self.window.update_caption([row], draft="work in progress")
        card = self.window.caption_cards["row-1"]
        history_item = self.window.history_items["row-1"]
        self.window.update_caption([dict(row)], draft="new draft")
        self.assertIs(self.window.caption_cards["row-1"], card)
        self.assertIs(self.window.history_items["row-1"], history_item)
        self.assertEqual(self.window.draft_label.text(), "草稿  ·  new draft")
        changed_row = dict(row, source="hello again", translation="再次问好")
        self.window.update_caption([changed_row], draft="new draft")
        self.assertIs(self.window.caption_cards["row-1"], card)
        self.assertIs(self.window.history_items["row-1"], history_item)
        self.assertEqual(card.source_text.text(), "hello again")
        self.assertIn("hello again", history_item.text())
        self.assertNotIn("再次问好", history_item.text())
        self.assertIn("再次问好", history_item.toolTip())
        self.window.apply_live_settings(font_size=32)
        self.assertIs(self.window.caption_cards["row-1"], card)

    def test_empty_full_snapshot_removes_caption_widgets_and_history_items(self):
        self.window.update_caption(
            [{"id": "row-1", "source": "hello", "translation": "你好", "start": 0, "end": 1, "language": "en"}]
        )
        self.window.update_caption([])
        self.assertEqual(self.window.caption_rows, {})
        self.assertEqual(self.window.caption_cards, {})
        self.assertEqual(self.window.history_items, {})
        self.assertEqual(self.window.history_list.count(), 0)
        self.assertEqual(self.window.compact_cards, {})

    def test_caption_text_is_plain_text_not_auto_formatted(self):
        self.window.update_caption(
            [{"id": "row-1", "source": "<b>literal</b>", "translation": "<i>译文</i>", "start": 0, "end": 1, "language": "en"}]
        )
        card = self.window.caption_cards["row-1"]
        self.assertEqual(card.source_text.textFormat().name, "PlainText")
        self.assertEqual(card.translation_text.textFormat().name, "PlainText")
        self.assertEqual(card.source_text.text(), "<b>literal</b>")

    def test_toast_uses_layout_and_dismisses_on_timer(self):
        self.window.show()
        self.window.toast("请先选择识别语言")
        self.app.processEvents()
        self.assertGreaterEqual(self.window.centralWidget().layout().indexOf(self.window.toast_label), 0)
        self.assertTrue(self.window.toast_timer.isActive())
        self.assertTrue(self.window.toast_label.isVisible())

    def test_committed_language_name_starts_at_left_edge(self):
        for picker, expected_prefix in ((self.window.source_language, "自动"),
                                        (self.window.target_language, "中文")):
            self.assertTrue(picker.lineEdit().text().startswith(expected_prefix))
            self.assertEqual(picker.lineEdit().cursorPosition(), 0)

    def test_meeting_history_wraps_long_text_without_horizontal_scrollbar(self):
        self.window.update_caption([{
            "id": "long-history", "source": "Commissioning schedule and testing responsibilities " * 8,
            "translation": "调试计划与测试责任分工" * 18, "start": 0, "end": 3, "language": "en",
        }])
        self.assertTrue(self.window.history_list.wordWrap())
        self.assertEqual(self.window.history_list.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_settings_buttons_are_explicitly_chinese_and_mlx_backends_are_disabled(self):
        from app.ui import SettingsDialog
        from PyQt6.QtWidgets import QDialogButtonBox
        dialog = SettingsDialog({}, {"output": [], "input": []})
        self.addCleanup(dialog.close)
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Save).text(), "保存")
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Cancel).text(), "取消")
        for backend in ("mlx-whisper", "voxtral-mlx", "qwen3-vllm-metal"):
            index = dialog.backend_combo.findData(backend)
            self.assertGreaterEqual(index, 0)
            if sys.platform == "darwin":
                self.assertNotIn("仅 macOS", dialog.backend_combo.itemText(index))
                self.assertTrue(dialog.backend_combo.model().item(index).isEnabled())
            else:
                self.assertIn("仅 macOS", dialog.backend_combo.itemText(index))
                self.assertFalse(dialog.backend_combo.model().item(index).isEnabled())

    def test_running_keeps_languages_live_but_freezes_model_and_source_controls(self):
        self.window.set_running(True)
        self.assertTrue(self.window.source_language.isEnabled())
        self.assertTrue(self.window.target_language.isEnabled())
        self.assertTrue(self.window.swap_button.isEnabled())
        self.assertFalse(self.window.model_combo.isEnabled())
        self.assertFalse(self.window.source_mode.isEnabled())
        self.assertTrue(self.window.pause_button.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())
        self.window.set_running(True, paused=True)
        self.assertEqual(self.window.pause_button.text(), "继续")
        self.assertTrue(self.window.model_combo.isEnabled())
        self.assertTrue(self.window.source_mode.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())

    def test_swap_button_has_accessible_icon_and_swaps_languages(self):
        button = self.window.swap_button
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.iconSize().width(), 32)
        self.assertEqual(button.iconSize().height(), 32)
        self.assertEqual(button.accessibleName(), "交换识别语言与翻译目标")
        self.window.source_language.setCurrentIndex(self.window.source_language.findData("en"))
        self.window.target_language.setCurrentIndex(self.window.target_language.findData("zh"))
        button.click()
        self.assertEqual(self.window.source_language.currentData(), "zh")
        self.assertEqual(self.window.target_language.currentData(), "en")

    def test_language_change_saves_complete_native_config(self):
        emitted = []
        self.window.config_changed.connect(emitted.append)
        self.window.set_running(True)
        self.window.source_language.setCurrentIndex(self.window.source_language.findData("fr"))
        self.assertEqual(self.window.settings["source_language"], "fr")
        self.assertEqual(emitted[-1]["wlk"]["lan"], "fr")
        self.assertIn("backend", emitted[-1]["wlk"])
        self.assertIn("model_size", emitted[-1]["wlk"])

    def test_transition_blocks_pause_but_keeps_end_button_available(self):
        self.window.set_running(True, paused=True)
        self.window.set_transitioning(True, "正在加载新模型…")
        self.assertFalse(self.window.pause_button.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())
        self.assertIn("正在加载新模型", self.window.status_label.text())

    def test_stop_waits_for_session_callback_before_unlocking(self):
        emitted = []
        self.window.stop_requested.connect(lambda: emitted.append(True))
        self.window.set_running(True)
        self.window.stop_button.click()
        self.assertEqual(emitted, [True])
        self.assertTrue(self.window.stop_pending)
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.set_running(False)
        self.assertFalse(self.window.stop_pending)
        self.assertTrue(self.window.start_button.isEnabled())

    def test_start_emits_a_copy_of_the_current_configuration(self):
        emitted = []
        self.window.start_requested.connect(emitted.append)
        self.window.start_button.click()
        self.assertEqual(emitted[0]["source_mode"], "system")
        self.assertEqual(emitted[0]["source_language"], "auto")
        self.assertEqual(emitted[0]["target_language"], "zh")

    def test_display_settings_change_caption_font_and_overlay_only(self):
        self.window.apply_live_settings(font_size=31, opacity=0.82)
        self.assertEqual(self.window.current_font_size, 31)
        self.assertAlmostEqual(self.window.windowOpacity(), 1.0, places=2)
        self.assertEqual(self.window.subtitle_overlay.preferences()["overlay_background_opacity"], 82)

    def test_subtitle_window_does_not_replace_or_resize_the_main_window(self):
        rows = [
            {"id": f"row-{i}", "source": f"line {i}", "translation": f"第{i}行", "start": i, "end": i + 1, "language": "en"}
            for i in range(3)
        ]
        self.window.update_caption(rows)
        self.window.show()
        self.app.processEvents()
        size = self.window.size()
        page = self.window.stack.currentWidget()
        self.window.toggle_compact_mode()
        self.app.processEvents()
        self.assertTrue(self.window.compact_mode)
        self.assertEqual(self.window.size(), size)
        self.assertIs(self.window.stack.currentWidget(), page)
        self.assertTrue(self.window.subtitle_overlay.isVisible())
        self.assertTrue(self.window.source_mode_field.isVisible())
        self.assertTrue(self.window.settings_button.isVisible())
        self.assertEqual(self.window.history_list.count(), 3)
        self.window.toggle_compact_mode()
        self.app.processEvents()
        self.assertFalse(self.window.subtitle_overlay.isVisible())
        self.assertEqual(self.window.size(), size)

    def test_subtitle_window_shows_long_source_and_translation(self):
        # This long row is from the final epoch in logs/live-settings-smoke.json.
        row = {
            "id": "both:g1:e1:real-smoke-last",
            "source": "The contract documents are still under review. and we will share an up-to-date information.",
            "translation": "合同文件仍在审查中. 我们将分享最新的信息.",
            "start": 36.76,
            "end": 40.48,
            "language": "en",
            "configured_language": "en",
            "target_language": "zh",
            "speaker": 1,
            "speaker_name": "说话人 1",
        }
        self.window.update_caption([row])
        self.window.show()
        self.window.toggle_compact_mode()
        self.app.processEvents()
        overlay = self.window.subtitle_overlay
        self.assertEqual(overlay.source_label.text(), row["source"])
        self.assertEqual(overlay.translation_label.text(), row["translation"])
        self.assertTrue(overlay.source_scroll.isVisible())
        self.assertTrue(overlay.translation_scroll.isVisible())

    def test_meeting_history_button_toggles_index_while_subtitle_is_open(self):
        self.window.update_caption(
            [{"id": "row-1", "source": "hello", "translation": "你好", "start": 0, "end": 1, "language": "en"}]
        )
        self.window.show()
        self.window.toggle_compact_mode()
        self.app.processEvents()
        self.window.history_button.click()
        self.assertTrue(self.window.history_panel.isVisible())
        self.assertEqual(self.window.history_list.count(),1)
        self.window.history_button.click()
        self.assertFalse(self.window.history_panel.isVisible())

    def test_subtitle_window_starts_in_bilingual_mode(self):
        self.window.update_caption(
            [{
                "id": "row-1",
                "source": "The contract documents are still under review.",
                "translation": "合同文件仍在审查中.",
                "start": 0,
                "end": 2,
                "language": "en",
            }]
        )
        self.window.show()
        self.window.toggle_compact_mode()
        self.app.processEvents()
        overlay = self.window.subtitle_overlay
        self.assertEqual(overlay.display_mode_combo.currentData(), "bilingual")
        self.assertTrue(overlay.source_scroll.isVisible())
        self.assertTrue(overlay.translation_scroll.isVisible())


if __name__ == "__main__":
    unittest.main()
