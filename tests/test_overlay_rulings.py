import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from unittest.mock import patch

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QLabel

from app.subtitle_overlay import SubtitleOverlay, _AppearanceDialog


class SubtitleOverlayRulingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_overlay(self, **settings):
        overlay = SubtitleOverlay(settings)
        self.addCleanup(overlay.close)
        return overlay

    def test_translation_only_explains_empty_translation_without_revealing_source_or_changing_mode(self):
        overlay = self.make_overlay(overlay_display_mode="translation", translation_mode="off")
        overlay.update_caption({"source": "原文内容", "audio_source": "麦克风"})
        self.assertEqual(overlay.display_mode_combo.currentData(), "translation")
        self.assertFalse(overlay.source_scroll.isVisible())
        self.assertFalse(overlay.translation_scroll.isVisible())
        self.assertFalse(overlay.empty_label.isHidden())
        self.assertIn("只显示译文", overlay.empty_label.text())
        self.assertIn("翻译已关闭", overlay.empty_label.text())
        self.assertNotIn("原文内容", overlay.empty_label.text())

        overlay.apply_preferences({"translation_mode": "local"})
        overlay.update_caption({"source": "新的原文", "audio_source": "系统声音"})
        self.assertIn("尚未生成", overlay.empty_label.text())
        self.assertEqual(overlay.display_mode_combo.currentData(), "translation")
        self.assertFalse(overlay.source_scroll.isVisible())

    def test_status_api_is_persistent_and_session_state_reports_dictation(self):
        overlay = self.make_overlay()
        self.assertTrue(hasattr(overlay, "set_status"))
        overlay.set_session_state(running=True, paused=False)
        self.assertIn("听写", overlay.status_label.text())
        overlay.set_status("麦克风连接失败", kind="error")
        self.assertEqual(overlay.status_label.text(), "麦克风连接失败")
        overlay.update_caption({"source": "你好"})
        self.assertEqual(overlay.status_label.text(), "麦克风连接失败")
        overlay.set_session_state(running=True, paused=True)
        self.assertEqual(overlay.status_label.text(), "已暂停")

    def test_translation_preparing_only_disables_translation_toggle(self):
        overlay = self.make_overlay(translation_mode="off")
        overlay.set_session_state(running=True, paused=False)
        self.assertTrue(hasattr(overlay, "set_translation_preparing"))
        requests = []
        overlay.translation_enabled_changed.connect(requests.append)
        overlay.translation_toggle.setChecked(True)
        self.assertEqual(requests, [True])
        overlay.set_translation_preparing(True)
        self.assertIn("准备中", overlay.translation_toggle.text())
        self.assertFalse(overlay.translation_toggle.isChecked())
        self.assertFalse(overlay.translation_toggle.isEnabled())
        self.assertTrue(overlay.pause_button.isEnabled())
        self.assertTrue(overlay.show_main_button.isEnabled())
        overlay.apply_preferences({"translation_mode": "local"})
        overlay.set_translation_preparing(False)
        self.assertTrue(overlay.translation_toggle.isEnabled())
        self.assertTrue(overlay.translation_toggle.isChecked())
        self.assertEqual(overlay.translation_toggle.text(), "实时翻译")

    def test_audio_source_is_shown_as_a_caption_source_marker(self):
        overlay = self.make_overlay()
        overlay.update_caption({"source": "Hello", "audio_source": "系统声音"})
        self.assertEqual(overlay.source_badge.text(), "系统声音")
        self.assertFalse(overlay.source_badge.isHidden())
        overlay.update_caption({"source": "Hello", "audio_source": ""})
        self.assertFalse(overlay.source_badge.isVisible())

    def test_restore_defaults_changes_appearance_without_changing_display_mode_or_session_mode(self):
        overlay = self.make_overlay(
            overlay_display_mode="source", overlay_font_size=44, overlay_source_color="#ff0000",
            translation_mode="off", overlay_x=140, overlay_y=160,
        )
        dialog = _AppearanceDialog(overlay)
        dialog.display_mode.setCurrentIndex(dialog.display_mode.findData("translation"))
        dialog.font_size.setValue(50)
        dialog.restore_defaults_button.click()
        self.assertEqual(dialog._draft["overlay_font_size"], 30)
        self.assertEqual(dialog._draft["overlay_source_color"], "#ffffff")
        self.assertEqual(dialog._draft["overlay_display_mode"], "source")
        self.assertEqual(overlay._translation_mode, "off")
        self.assertEqual(dialog._draft["overlay_x"], dialog._original["overlay_x"])
        self.assertEqual(dialog._draft["overlay_y"], dialog._original["overlay_y"])
        dialog.reject()
        self.assertEqual(overlay.preferences()["overlay_font_size"], 44)
        self.assertEqual(overlay.preferences()["overlay_source_color"], "#ff0000")
        self.assertEqual(overlay.preferences()["overlay_display_mode"], "source")

    def test_caption_alignment_follows_arabic_text_without_reversing_controls(self):
        overlay = self.make_overlay()
        overlay.update_caption({"source": "مرحبا بالعالم"})
        self.assertTrue(overlay.source_label.alignment() & Qt.AlignmentFlag.AlignRight)
        self.assertFalse(overlay.layoutDirection() == Qt.LayoutDirection.RightToLeft)
        overlay.update_caption({"source": "Hello مرحبا"})
        self.assertTrue(overlay.source_label.alignment() & Qt.AlignmentFlag.AlignLeft)
        overlay.update_caption({"source": "مرحبا Hello"})
        self.assertTrue(overlay.source_label.alignment() & Qt.AlignmentFlag.AlignRight)
        self.assertFalse(overlay.layoutDirection() == Qt.LayoutDirection.RightToLeft)
        overlay.update_caption({"source": "你好，世界"})
        self.assertTrue(overlay.source_label.alignment() & Qt.AlignmentFlag.AlignLeft)

    def test_settings_expose_background_opacity_without_alpha_color_picker(self):
        dialog = _AppearanceDialog(self.make_overlay())
        self.assertIn("不透明度", dialog.findChild(QLabel).text() + "".join(
            label.text() for label in dialog.findChildren(QLabel)
        ))
        self.assertEqual(dialog.opacity.minimum(), 15)
        self.assertEqual(dialog.opacity.maximum(), 100)
        self.assertTrue(hasattr(dialog, "contrast_notice"))
        with patch("app.subtitle_overlay.QColorDialog.getColor", return_value=QColor("#123456")) as picker:
            dialog._choose_color("overlay_source_color", dialog.source_color)
        self.assertEqual(len(picker.call_args.args), 3)
        dialog._draft["overlay_source_color"] = "#222222"
        dialog._update_contrast_notice()
        self.assertIn("偏低", dialog.contrast_notice.text())
        self.assertIn("可继续使用自选颜色", dialog.contrast_notice.text())


if __name__ == "__main__":
    unittest.main()
