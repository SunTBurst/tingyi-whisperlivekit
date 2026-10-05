import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from app.icons import app_icon, set_button_icon, standard_icon, swap_icon
from app.theme import STYLE


class ThemeRulingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def has_visible_pixel(image):
        return any(image.pixelColor(x, y).alpha() > 0
                   for y in range(image.height()) for x in range(image.width()))

    def test_every_existing_action_name_has_a_visible_icon(self):
        names = ("lock", "overlay", "history", "settings", "tools", "background",
                 "start", "pause", "stop", "copy", "export", "clear")
        widget = QWidget()
        for name in names:
            with self.subTest(name=name):
                icon = standard_icon(widget, name)
                self.assertIsNotNone(icon)
                self.assertFalse(icon.isNull())
                pixmap = icon.pixmap(QSize(20, 20))
                self.assertFalse(pixmap.isNull())
                self.assertTrue(self.has_visible_pixel(pixmap.toImage()))

    def test_swap_and_app_marks_render(self):
        for icon in (swap_icon(), app_icon()):
            self.assertFalse(icon.isNull())
            pixmap = icon.pixmap(QSize(32, 32))
            self.assertTrue(self.has_visible_pixel(pixmap.toImage()))

    def test_button_icon_helper_uses_consistent_compact_size(self):
        button = QPushButton("Action")
        set_button_icon(button, "copy")
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.iconSize().width(), button.iconSize().height())
        self.assertLessEqual(button.iconSize().width(), 20)

    def test_native_widget_keeps_transparent_surface_and_readable_disabled_text(self):
        host = QWidget()
        host.setStyleSheet(STYLE)
        host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        host.resize(180, 64)
        button = QPushButton("Disabled", host)
        button.setDisabled(True)
        button.ensurePolished()
        host.show()
        self.app.processEvents()
        self.assertTrue(host.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(host.grab().toImage().pixelColor(179, 63).alpha(), 0)
        foreground = button.palette().color(QPalette.ColorRole.ButtonText)
        background = button.palette().color(QPalette.ColorRole.Button)

        def luminance(color):
            channels = [color.redF(), color.greenF(), color.blueF()]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
            return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

        high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
        self.assertGreaterEqual((high + .05) / (low + .05), 4.5)
        host.close()
        host.deleteLater()
        self.app.processEvents()

    def test_theme_has_distinct_interaction_popup_and_overlay_tokens(self):
        for selector in ("QPushButton:hover", "QPushButton:pressed", "QPushButton:disabled",
                         "QMenu", "QComboBox QAbstractItemView", "QLabel#overlayAudioSource",
                         "QLabel#overlayStatus", "QLabel#emptyState"):
            self.assertIn(selector, STYLE)


if __name__ == "__main__":
    unittest.main()
