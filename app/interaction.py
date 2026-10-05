"""App-wide protections against accidental wheel changes and delayed help."""

from __future__ import annotations

import weakref

from PyQt6 import sip

from PyQt6.QtCore import QObject, QEvent, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QScrollArea, QSlider, QSpinBox, QDoubleSpinBox, QToolTip, QPushButton, QWidget

from app.help_text import HELP_TEXT, help_for


class InteractionPolicy(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self._help_timer = QTimer(self)
        self._help_timer.setSingleShot(True)
        self._help_timer.setInterval(800)
        self._help_timer.timeout.connect(self._show_help)
        self._help_widget = None
        app.installEventFilter(self)

    @staticmethod
    def _combo_for(widget):
        node = widget
        while node is not None:
            if isinstance(node, QComboBox):
                return node
            node = node.parentWidget()
        return None

    @staticmethod
    def _scroll_area(widget):
        node = widget.parentWidget()
        while node is not None:
            if isinstance(node, QScrollArea):
                return node
            node = node.parentWidget()
        return None

    def _forward_wheel(self, widget, event):
        area = self._scroll_area(widget)
        if area is None:
            return
        QApplication.sendEvent(area.viewport(), event)


    @staticmethod
    def _auto_attach(widget):
        if widget.property("helpText"):
            return
        key = str(widget.property("helpKey") or widget.objectName() or "")
        fallback = ""
        ancestor = widget.parentWidget()
        while ancestor is not None:
            if ancestor.property("helpText"):
                key = str(ancestor.property("helpKey") or key)
                fallback = str(ancestor.property("helpText"))
                break
            ancestor = ancestor.parentWidget()
        if not key and hasattr(widget, "text"):
            key = str(widget.text() or "").strip()
        known = {
            "开始会议": "start_meeting", "开始": "start_meeting", "停止会议": "stop_meeting",
            "暂停": "pause", "继续": "resume", "设置": "settings", "会议工具": "tools",
            "词库": "glossary", "参会者": "participants", "导出": "export", "保存": "save",
            "取消": "cancel", "应用": "apply", "识别语言": "lan", "翻译目标": "target_language",
            "实时翻译": "overlay_translation_toggle", "显示说话人": "overlay_show_speaker",
            "显示识别/翻译草稿": "overlay_show_draft", "锁定": "overlay_locked",
            "置顶": "overlay_always_on_top", "外观": "overlay_appearance",
            "返回主窗口": "show_main", "overlayWidth": "overlay_width",
            "overlayHeight": "overlay_height", "overlayOpacity": "overlay_background_opacity",
            "overlayFontFamily": "overlay_font_family", "overlayFontSize": "overlay_font_size",
            "overlaySource": "overlay_source_color", "overlayTranslation": "overlay_translation_color",
            "overlayDisplayMode": "overlay_display_mode", "overlaySpeaker": "overlay_show_speaker",
            "overlayDraft": "overlay_show_draft", "overlay_locked": "overlay_locked",
            "overlay_always_on_top": "overlay_always_on_top",
            "overlay_background_color": "overlay_background_color",
            "overlayFollowTheme": "overlay_follow_theme",
            "overlay_source_color": "overlay_source_color",
            "overlay_translation_color": "overlay_translation_color",
        }
        key = known.get(key, key)
        text = help_for(key, "")
        if text and key in HELP_TEXT:
            attach_help(widget, key, fallback)
        elif not widget.toolTip() and not widget.accessibleDescription():
            return

    def _widget_destroyed(self, widget_ref):
        widget = widget_ref()
        if widget is self._help_widget:
            self._help_timer.stop()
            self._help_widget = None

    def _show_help(self):
        widget = self._help_widget
        if widget is None or sip.isdeleted(widget):
            self._help_widget = None
            return
        if not widget.isVisible():
            return
        text = str(widget.property("helpText") or widget.toolTip() or "")
        if text:
            QToolTip.showText(widget.mapToGlobal(widget.rect().bottomLeft()), text, widget)

    def eventFilter(self, watched, event):  # noqa: N802
        typ = event.type()
        if typ == QEvent.Type.Enter and isinstance(watched, QWidget):
            self._help_timer.stop()
            self._help_widget = watched
            if not watched.property("interactionHelpConnected"):
                watched.setProperty("interactionHelpConnected", True)
                watched_ref = weakref.ref(watched)
                watched.destroyed.connect(lambda *_args, ref=watched_ref: self._widget_destroyed(ref))
            if self._help_widget is not None:
                self._auto_attach(self._help_widget)
                self._help_timer.start()
        elif typ in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
            self._help_timer.stop()
            if typ == QEvent.Type.Leave:
                QToolTip.hideText()
        if typ == QEvent.Type.Wheel and isinstance(watched, QWidget):
            combo = self._combo_for(watched)
            if combo is not None and not combo.view().isVisible():
                self._forward_wheel(combo, event)
                event.accept()
                return True
            if isinstance(watched, (QSpinBox, QDoubleSpinBox, QSlider)):
                actively_adjusting = watched.hasFocus() or (isinstance(watched, QSlider) and watched.isSliderDown())
                if not actively_adjusting:
                    self._forward_wheel(watched, event)
                    event.accept()
                    return True
        return False


def install_interaction_policy(app: QApplication) -> InteractionPolicy:
    existing = getattr(app, "_interaction_policy", None)
    if existing is None:
        existing = InteractionPolicy(app)
        app._interaction_policy = existing
    return existing


def attach_help(widget, key: str, fallback: str = "") -> None:
    """Attach verbose Chinese help while keeping the visual tooltip delayed."""
    effective_key = str(key)
    if effective_key == "overlay":
        if isinstance(widget, QSlider):
            effective_key = "overlay_background_opacity"
        elif isinstance(widget, QCheckBox) and "上方" in widget.text():
            effective_key = "overlay_always_on_top"
        elif isinstance(widget, QPushButton) and "字幕窗" in widget.text():
            effective_key = "overlay_window"
    elif effective_key == "translation_provider" and isinstance(widget, QComboBox):
        values = {str(widget.itemData(index)) for index in range(widget.count())}
        if values and values <= {"local", "off"}:
            effective_key = "translation_mode"
    existing = str(widget.toolTip() or "").strip()
    generic_prefixes = ("WhisperLiveKit 原参数：", "WhisperLiveKit 参数 ")
    if existing and not existing.startswith(generic_prefixes):
        # Keep a field's own concrete upstream/UI explanation intact.
        text = existing
    elif effective_key in HELP_TEXT:
        text = HELP_TEXT[effective_key]
    elif existing:
        text = existing
    elif fallback and not str(fallback).startswith("WhisperLiveKit 原参数："):
        text = str(fallback)
    elif fallback:
        text = str(fallback)
    else:
        text = ""
    if not text:
        return
    widget.setProperty("helpKey", effective_key)
    widget.setProperty("helpText", text)
    # Keep the standard tooltip too; Qt displays it after its native hover delay.
    widget.setAccessibleDescription(text)
    widget.setToolTip(text)
