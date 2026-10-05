import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from app.subtitle_overlay import SubtitleOverlay, _AppearanceDialog
from app.appearance import set_theme
from app.theme import palette_for


class OverlayThemeCompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_overlay(self, **prefs):
        overlay = SubtitleOverlay(prefs)
        self.addCleanup(overlay.close)
        return overlay

    def test_follow_theme_changes_actual_caption_surface_and_text_colors(self):
        self.addCleanup(set_theme, "dark")
        set_theme("sky")
        overlay = self.make_overlay()
        overlay.update_caption({"source": "hello", "translation": "你好"})
        overlay.set_status("正在听写", "listening")

        colors = palette_for("sky")
        self.assertTrue(overlay.preferences()["overlay_follow_theme"])
        self.assertEqual(overlay.background_color.name(), colors["window"])
        self.assertEqual(overlay.source_label.palette().color(overlay.source_label.foregroundRole()).name(), colors["text"])
        self.assertEqual(overlay.translation_label.palette().color(overlay.translation_label.foregroundRole()).name(), colors["translation"])
        self.assertEqual(overlay.status_label.palette().color(overlay.status_label.foregroundRole()).name(), colors["accent"])

        overlay.resize(680, 300)
        overlay.show()
        self.app.processEvents()
        image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        overlay.render(painter)
        painter.end()
        pixel = image.pixelColor(overlay.width() // 2, overlay.height() // 2)
        self.assertEqual(pixel.alpha(), round(88 * 2.55))
        for actual, expected in zip((pixel.red(), pixel.green(), pixel.blue()),
                                    (int(colors["window"][1:3], 16), int(colors["window"][3:5], 16), int(colors["window"][5:7], 16))):
            self.assertLessEqual(abs(actual - expected), 1)

    def test_dialog_follow_toggle_disables_color_controls_and_custom_pick_turns_follow_off(self):
        self.addCleanup(set_theme, "dark")
        set_theme("spring")
        overlay = self.make_overlay(overlay_background_color="#112233", overlay_source_color="#eeeeee",
                                    overlay_translation_color="#66ccaa")
        dialog = _AppearanceDialog(overlay)
        self.assertTrue(dialog.follow_theme.isChecked())
        self.assertFalse(dialog.background_color.isEnabled())
        self.assertEqual(dialog.background_color.text(), palette_for("spring")["window"])

        dialog.follow_theme.setChecked(False)
        self.assertTrue(dialog.background_color.isEnabled())
        self.assertEqual(dialog.background_color.text(), "#112233")
        dialog.preset.setCurrentIndex(dialog.preset.findData("sky_colors"))
        self.assertFalse(dialog._draft["overlay_follow_theme"])
        self.assertFalse(overlay.preferences()["overlay_follow_theme"])
        self.assertEqual(overlay.background_color.name(), palette_for("sky")["window"])

    def test_cancel_restores_follow_custom_colors_mode_and_geometry(self):
        self.addCleanup(set_theme, "dark")
        set_theme("dark")
        overlay = self.make_overlay(overlay_background_color="#152535", overlay_source_color="#fefefe",
                                    overlay_translation_color="#62c9b2", overlay_display_mode="source",
                                    overlay_width=444, overlay_height=222, overlay_x=81, overlay_y=92)
        before = overlay.preferences()
        dialog = _AppearanceDialog(overlay)
        dialog.follow_theme.setChecked(False)
        dialog._set("overlay_display_mode", "translation")
        dialog.width_spin.setValue(600)
        dialog.reject()
        self.assertEqual(overlay.preferences(), before)
        self.assertEqual(overlay.background_color.name(), palette_for("dark")["window"])
        self.assertEqual(overlay.preferences()["overlay_background_color"], before["overlay_background_color"])

    def test_picking_custom_color_keeps_the_saved_value_and_switches_to_custom_mode(self):
        overlay = self.make_overlay(overlay_background_color="#112233")
        dialog = _AppearanceDialog(overlay)
        dialog.follow_theme.setChecked(False)
        with patch("app.dialogs.QColorDialog.getColor", return_value=QColor("#abcdef")):
            dialog._choose_color("overlay_background_color", dialog.background_color)
        self.assertFalse(dialog._draft["overlay_follow_theme"])
        self.assertFalse(overlay.preferences()["overlay_follow_theme"])
        self.assertEqual(overlay.preferences()["overlay_background_color"], "#abcdef")
        self.assertEqual(overlay.background_color.name(), "#abcdef")

    def test_restore_defaults_reenables_theme_follow_and_cancel_restores_custom_mode(self):
        self.addCleanup(set_theme,'dark')
        set_theme('sky')
        overlay=self.make_overlay(overlay_follow_theme=False,overlay_background_color='#112233')
        before=overlay.preferences()
        dialog=_AppearanceDialog(overlay)
        dialog._restore_appearance_defaults()
        self.assertTrue(dialog.follow_theme.isChecked())
        self.assertTrue(overlay.preferences()['overlay_follow_theme'])
        self.assertFalse(dialog.background_color.isEnabled())
        self.assertEqual(overlay.background_color.name(),palette_for('sky')['window'])
        dialog.reject()
        self.assertEqual(overlay.preferences(),before)


if __name__ == "__main__":
    unittest.main()
