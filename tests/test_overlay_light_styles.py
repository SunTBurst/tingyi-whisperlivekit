import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from app.subtitle_overlay import SubtitleOverlay, _AppearanceDialog
from app.appearance import set_theme
from app.theme import palette_for


class OverlayThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_overlay(self, **prefs):
        overlay = SubtitleOverlay(prefs)
        self.addCleanup(overlay.close)
        return overlay

    def test_global_theme_preserves_caption_preferences_and_geometry(self):
        overlay = self.make_overlay(
            overlay_follow_theme=False,
            overlay_background_color="#111111", overlay_background_opacity=73,
            overlay_source_color="#fefefe", overlay_translation_color="#77ccaa",
            overlay_font_family="Arial", overlay_font_size=27,
            overlay_width=444, overlay_height=222, overlay_x=81, overlay_y=92,
        )
        original = overlay.preferences()
        overlay.apply_ui_theme("sky")
        self.assertEqual(overlay.preferences(), original)
        self.assertEqual(overlay.background_color.name(), "#111111")
        self.assertEqual(overlay.background_color.alpha(), round(73 * 2.55))
        self.assertEqual(overlay.source_label.font().pixelSize(), 27)
        self.assertIn(palette_for("sky")["surface"], overlay.styleSheet())
        self.assertIn(palette_for("sky")["accent"], overlay.source_badge.styleSheet())
        overlay.apply_ui_theme("spring")
        self.assertEqual(overlay.preferences(), original)

    def test_color_presets_preview_palette_colors_and_cancel_restores_everything(self):
        overlay = self.make_overlay(overlay_background_color="#151515", overlay_source_color="#eeeeee",
                                    overlay_translation_color="#68c4dd", overlay_background_opacity=73)
        emitted = []
        overlay.preferences_changed.connect(emitted.append)
        before = overlay.preferences()
        dialog = _AppearanceDialog(overlay)
        dialog.preset.setCurrentIndex(dialog.preset.findData("sky_colors"))
        sky = palette_for("sky")
        self.assertEqual(overlay.preferences()["overlay_background_color"], sky["window"])
        self.assertEqual(overlay.preferences()["overlay_source_color"], sky["text"])
        self.assertEqual(overlay.preferences()["overlay_translation_color"], sky["translation"])
        self.assertEqual(overlay.preferences()["overlay_background_opacity"], 73)
        dialog.preset.setCurrentIndex(dialog.preset.findData("spring_colors"))
        spring = palette_for("spring")
        self.assertEqual(overlay.preferences()["overlay_background_color"], spring["window"])
        self.assertEqual(overlay.preferences()["overlay_source_color"], spring["text"])
        self.assertEqual(overlay.preferences()["overlay_translation_color"], spring["translation"])
        dialog.reject()
        self.assertEqual(overlay.preferences(), before)
        self.assertEqual(emitted, [])

    def test_light_theme_renders_toolbar_and_keeps_custom_dark_caption_legible(self):
        overlay = self.make_overlay(overlay_follow_theme=False, overlay_background_color="#121212", overlay_source_color="#ffffff")
        overlay.apply_ui_theme("sky")
        overlay.set_status("正在听写", "listening")
        self.assertIn("#ffffff", overlay.status_label.styleSheet())
        self.assertIn("#ffffff", overlay.styleSheet())
        self.assertIn("#ffffff", overlay.translation_toggle.styleSheet())
        self.assertIn("#ffffff", overlay.empty_label.styleSheet())
        from PyQt6.QtGui import QPalette
        overlay.translation_toggle.ensurePolished()
        self.assertEqual(overlay.translation_toggle.palette().color(QPalette.ColorRole.WindowText).name(),'#ffffff')
        self.assertEqual(overlay.source_label.styleSheet().split("color:", 1)[1].split(";", 1)[0], "#ffffff")
        overlay.resize(680, 300)
        overlay.show()
        self.app.processEvents()
        rendered = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
        rendered.fill(0)
        painter = QPainter(rendered)
        overlay.render(painter)
        painter.end()
        point = overlay.appearance_button.mapTo(overlay, overlay.appearance_button.rect().topLeft())
        pixel = rendered.pixelColor(point.x() + 4, point.y() + 4)
        self.assertGreater(pixel.alpha(), 0)
        self.assertGreater(pixel.red(), 150)

    def test_global_theme_bus_restyles_overlay_without_mutating_body_preferences(self):
        overlay = self.make_overlay(overlay_background_color="#303030", overlay_source_color="#f0f0f0",
                                    overlay_translation_color="#80c8dd", overlay_font_size=26,
                                    overlay_follow_theme=False)
        original = overlay.preferences()
        try:
            set_theme("spring")
            self.assertEqual(overlay._ui_theme, "spring")
            self.assertIn(palette_for("spring")["surface"], overlay.styleSheet())
            self.assertEqual(overlay.preferences(), original)
            self.assertEqual(overlay.source_label.styleSheet().split("color:", 1)[1].split(";", 1)[0], "#f0f0f0")
        finally:
            set_theme("dark")


if __name__ == "__main__":
    unittest.main()
