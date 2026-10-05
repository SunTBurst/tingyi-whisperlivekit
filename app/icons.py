"""Small, consistent vector icons for the native Qt interface."""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


_ICON_NAMES = frozenset({
    "lock", "overlay", "history", "settings", "tools", "background",
    "start", "pause", "stop", "copy", "export", "clear",
})
_ICON_COLOR = "#c5d8e0"
_ACTIVE_COLOR = "#71d3dc"
_DISABLED_COLOR = "#71838e"


def _draw_action(painter: QPainter, name: str, color: str) -> None:
    """Draw a simple 24-unit outline glyph using one shared stroke style."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "lock":
        path = QPainterPath()
        path.moveTo(7, 10); path.lineTo(7, 8); path.cubicTo(7, 2, 17, 2, 17, 8); path.lineTo(17, 10)
        painter.drawPath(path); painter.drawRoundedRect(5, 10, 14, 11, 2, 2)
        painter.drawLine(12, 14, 12, 17)
    elif name in {"overlay", "background"}:
        painter.drawRoundedRect(4, 4, 16, 16, 2, 2)
        painter.drawLine(4, 8, 20, 8)
        if name == "overlay":
            painter.drawLine(8, 12, 16, 12); painter.drawLine(8, 15, 14, 15); painter.drawLine(8, 18, 12, 18)
        else:
            painter.drawEllipse(8, 10, 8, 8)
    elif name == "history":
        painter.drawArc(4, 4, 16, 16, 45 * 16, 285 * 16)
        painter.drawLine(4, 5, 4, 10); painter.drawLine(4, 5, 9, 5)
        painter.drawLine(12, 7, 12, 12); painter.drawLine(12, 12, 16, 14)
    elif name == "settings":
        painter.drawEllipse(5, 5, 14, 14); painter.drawEllipse(10, 10, 4, 4)
        for x1, y1, x2, y2 in ((12, 2.5, 12, 5), (12, 19, 12, 21.5), (2.5, 12, 5, 12),
                              (19, 12, 21.5, 12), (5.3, 5.3, 7.1, 7.1), (16.9, 16.9, 18.7, 18.7),
                              (5.3, 18.7, 7.1, 16.9), (16.9, 7.1, 18.7, 5.3)):
            painter.drawLine(round(x1), round(y1), round(x2), round(y2))
    elif name == "tools":
        path = QPainterPath(); path.moveTo(14, 4); path.cubicTo(18, 2, 22, 6, 20, 10)
        path.lineTo(17, 8); path.lineTo(14, 11); path.lineTo(16, 14); path.lineTo(19, 12)
        path.lineTo(21, 15); path.lineTo(12, 20); path.lineTo(9, 17); path.lineTo(4, 9)
        path.cubicTo(2, 6, 6, 3, 9, 5); path.lineTo(11, 8); path.closeSubpath(); painter.drawPath(path)
    elif name == "start":
        path = QPainterPath(); path.moveTo(7, 4); path.lineTo(20, 12); path.lineTo(7, 20); path.closeSubpath()
        painter.setBrush(QColor(color)); painter.drawPath(path)
    elif name == "pause":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
        painter.drawRoundedRect(6, 4, 4, 16, 1, 1); painter.drawRoundedRect(14, 4, 4, 16, 1, 1)
    elif name == "stop":
        painter.setBrush(QColor(color)); painter.drawRoundedRect(5, 5, 14, 14, 2, 2)
    elif name == "copy":
        painter.drawRoundedRect(8, 4, 12, 14, 1.5, 1.5)
        painter.drawLine(6, 8, 4, 8); painter.drawLine(4, 8, 4, 20); painter.drawLine(4, 20, 15, 20)
    elif name == "export":
        painter.drawLine(12, 14, 12, 3); painter.drawLine(8, 7, 12, 3); painter.drawLine(12, 3, 16, 7)
        painter.drawLine(5, 13, 5, 20); painter.drawLine(5, 20, 19, 20); painter.drawLine(19, 20, 19, 13)
    elif name == "clear":
        painter.drawLine(5, 7, 19, 7); painter.drawLine(9, 4, 15, 4)
        painter.drawRoundedRect(7, 8, 10, 12, 1, 1)
        painter.drawLine(10, 11, 10, 17); painter.drawLine(14, 11, 14, 17)


def standard_icon(widget: QWidget, name: str):
    """Return a consistently drawn Qt icon for an existing named action."""
    if name not in _ICON_NAMES:
        return None
    from app.appearance import current_theme
    from app.theme import palette_for
    palette=palette_for(current_theme(widget))
    primary=widget.objectName()=='primary'
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        for mode, color in ((QIcon.Mode.Normal, palette['accent_text'] if primary else palette['icon']),
                            (QIcon.Mode.Active, palette['accent_text'] if primary else palette['icon_active']),
                            (QIcon.Mode.Disabled, palette['icon_disabled'])):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.scale(size / 24, size / 24)
            try:
                _draw_action(painter, name, color)
            finally:
                painter.end()
            icon.addPixmap(pixmap, mode)
    return icon


def set_button_icon(button, name: str) -> None:
    button.setProperty('themeIcon',name)
    icon = standard_icon(button, name)
    if icon is not None:
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))


def swap_icon() -> QIcon:
    """Draw the familiar opposing language arrows in the shared icon color."""
    from app.appearance import current_theme
    from app.theme import palette_for
    color=palette_for(current_theme())['icon']
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(4, 8, 20, 8); painter.drawLine(20, 8, 17, 5); painter.drawLine(20, 8, 17, 11)
        painter.drawLine(20, 16, 4, 16); painter.drawLine(4, 16, 7, 13); painter.drawLine(4, 16, 7, 19)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def app_icon() -> QIcon:
    """Draw the app mark at several sizes for the window and system tray."""
    from app.appearance import current_theme
    from app.theme import palette_for
    colors=palette_for(current_theme())
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors['accent']))
        painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
        painter.setPen(QPen(QColor(colors['accent_text']), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x, height in ((16, 10), (23, 21), (30, 32), (37, 21), (44, 12)):
            painter.drawLine(x, 26 - height // 2, x, 26 + height // 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors['accent_text']))
        painter.drawRoundedRect(14, 41, 36, 4, 2, 2)
        painter.drawRoundedRect(14, 49, 25, 4, 2, 2)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
