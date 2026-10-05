"""Subtle, transparent theme motifs for unused window background space."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from app.theme import normalize_theme


class ThemeBackdrop(QWidget):
    """A non-interactive decorative layer; keep content surfaces opaque above it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_id = "dark"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_theme(self, theme_id):
        theme_id = normalize_theme(theme_id)
        if theme_id != self._theme_id:
            self._theme_id = theme_id
            self.update()

    def paintEvent(self, event):
        if self._theme_id == "dark" or self.width() <= 0 or self.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        w, h = float(self.width()), float(self.height())
        if self._theme_id == "sky":
            self._paint_sky(painter, w, h)
        else:
            self._paint_spring(painter, w, h)
        painter.end()

    @staticmethod
    def _paint_sky(painter, w, h):
        # Keep the large shapes near the upper-right title whitespace and corners.
        scale = min(w, h)
        mist = QLinearGradient(w * 0.68, 0, w, h * 0.37)
        mist.setColorAt(0.0, QColor(255, 255, 255, 0))
        mist.setColorAt(0.5, QColor(255, 255, 255, 8))
        mist.setColorAt(1.0, QColor(255, 255, 255, 0))
        cloud = QPainterPath()
        cloud.moveTo(w * 0.61, h * 0.18)
        cloud.cubicTo(w * 0.69, h * 0.12, w * 0.75, h * 0.19, w * 0.80, h * 0.16)
        cloud.cubicTo(w * 0.86, h * 0.08, w * 0.94, h * 0.13, w * 0.98, h * 0.10)
        cloud.cubicTo(w * 1.03, h * 0.16, w * 0.95, h * 0.22, w * 0.87, h * 0.20)
        cloud.cubicTo(w * 0.78, h * 0.24, w * 0.70, h * 0.19, w * 0.61, h * 0.23)
        cloud.closeSubpath()
        painter.fillPath(cloud, mist)

        pen = QPen(QColor(92, 157, 192, 8), max(1.0, scale * 0.002))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arc = QPainterPath()
        arc.moveTo(w * 0.76, h * 0.01)
        arc.cubicTo(w * 0.93, h * 0.035, w * 0.96, h * 0.12, w * 1.02, h * 0.17)
        painter.drawPath(arc)
        lower_arc = QPainterPath()
        lower_arc.moveTo(0, h * 0.93)
        lower_arc.cubicTo(w * 0.07, h * 0.90, w * 0.09, h * 0.95, w * 0.16, h)
        painter.drawPath(lower_arc)

    @staticmethod
    def _paint_spring(painter, w, h):
        scale = min(w, h)
        pen = QPen(QColor(91, 143, 89, 8), max(1.0, scale * 0.002))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # A few airy stems and leaf outlines leave the central reading area clear.
        stem = QPainterPath()
        stem.moveTo(w * 0.98, 0)
        stem.cubicTo(w * 0.91, h * 0.09, w * 0.96, h * 0.17, w * 0.86, h * 0.25)
        painter.drawPath(stem)
        ThemeBackdrop._leaf(painter, w * 0.90, h * 0.09, scale * 0.12, -0.65)
        ThemeBackdrop._leaf(painter, w * 0.93, h * 0.17, scale * 0.10, 0.58)

        corner_stem = QPainterPath()
        corner_stem.moveTo(0, h * 0.91)
        corner_stem.cubicTo(w * 0.08, h * 0.89, w * 0.11, h * 0.97, w * 0.20, h)
        painter.drawPath(corner_stem)
        ThemeBackdrop._leaf(painter, w * 0.08, h * 0.94, scale * 0.08, -0.35)

    @staticmethod
    def _leaf(painter, x, y, length, angle):
        painter.save()
        painter.translate(x, y)
        painter.rotate(angle * 57.295779513)
        leaf = QPainterPath()
        leaf.moveTo(0, 0)
        leaf.cubicTo(length * 0.25, -length * 0.42, length * 0.82, -length * 0.38, length, 0)
        leaf.cubicTo(length * 0.73, length * 0.34, length * 0.22, length * 0.29, 0, 0)
        painter.drawPath(leaf)
        vein = QPainterPath()
        vein.moveTo(length * 0.05, 0)
        vein.cubicTo(length * 0.38, -length * 0.02, length * 0.62, -length * 0.03, length * 0.93, 0)
        painter.drawPath(vein)
        painter.restore()
