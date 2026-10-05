import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QMainWindow,
    QMenu,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.theme import STYLE, THEME_CHOICES, normalize_theme, palette_for, style_for


def _luminance(color):
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(first, second):
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class LightPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_names_normalization_and_legacy_dark_stylesheet(self):
        self.assertEqual(THEME_CHOICES, (("深色·静谧", "dark"), ("晴空蓝", "sky"), ("春意绿", "spring")))
        self.assertEqual([normalize_theme(value) for value in ("SKY", "spring", "unknown", None)],
                         ["sky", "spring", "dark", "dark"])
        self.assertEqual(normalize_theme("晴空蓝"), "sky")
        self.assertEqual(style_for("dark"), STYLE)

    def test_light_semantic_text_and_primary_button_contrast(self):
        for theme_id in ("sky", "spring"):
            palette = palette_for(theme_id)
            self.assertGreaterEqual(_contrast(palette["text"], palette["window"]), 4.5)
            self.assertGreaterEqual(_contrast(palette["muted"], palette["window"]), 4.5)
            self.assertGreaterEqual(_contrast(palette["accent_text"], palette["accent"]), 4.5)
            self.assertGreaterEqual(_contrast(palette["translation"], palette["surface"]), 4.5)
            self.assertGreaterEqual(_contrast(palette["disabled_text"], palette["disabled_bg"]), 4.5)
            self.assertGreaterEqual(_contrast(palette["icon_disabled"], palette["disabled_bg"]), 3)

    def test_light_styles_render_real_qt_controls_and_interaction_states(self):
        for theme_id in ("sky", "spring"):
            with self.subTest(theme=theme_id):
                window = QMainWindow()
                root = QWidget()
                layout = QVBoxLayout(root)
                surface = QFrame()
                surface.setObjectName("surface")
                surface_layout = QVBoxLayout(surface)
                primary = QPushButton("开始")
                primary.setObjectName("primary")
                disabled = QPushButton("不可用")
                disabled.setDisabled(True)
                combo = QComboBox()
                combo.addItems(("中文", "English"))
                checkbox = QCheckBox("启用")
                checkbox.setChecked(True)
                tabs = QTabWidget()
                tabs.addTab(QWidget(), "常规")
                tabs.addTab(QWidget(), "高级")
                tabs.setCurrentIndex(1)
                menu = QMenu(primary)
                menu.addAction("普通项")
                menu.addAction("禁用项").setDisabled(True)
                for widget in (primary, disabled, combo, checkbox, tabs):
                    surface_layout.addWidget(widget)
                layout.addWidget(surface)
                window.setCentralWidget(root)
                stylesheet = style_for(theme_id)
                window.setStyleSheet(stylesheet)
                window.resize(360, 300)
                window.show()
                self.app.processEvents()

                image = QImage(QSize(360, 300), QImage.Format.Format_ARGB32)
                image.fill(0)
                painter = QPainter(image)
                window.render(painter)
                painter.end()
                self.assertFalse(image.isNull())
                self.assertGreater(image.byteCount() if hasattr(image, "byteCount") else image.sizeInBytes(), 0)
                self.assertTrue(primary.isEnabled())
                self.assertFalse(disabled.isEnabled())
                self.assertTrue(checkbox.isChecked())
                self.assertEqual(tabs.currentIndex(), 1)
                for selector in ("QMenu::item:selected", "QToolTip", ":focus", ":disabled",
                                 "QCheckBox::indicator:checked", "QScrollBar::handle:vertical:hover"):
                    self.assertIn(selector, stylesheet)
                self.assertTrue(menu.actions()[1].isEnabled() is False)
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
