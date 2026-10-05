"""Independent, user-positionable subtitle window for the desktop client."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPainter, QPen, QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QSizeGrip,
)
from app.theme import palette_for, normalize_theme, style_for
from app.dialogs import QColorDialog
from app.icons import app_icon


_DEFAULTS: dict[str, Any] = {
    "overlay_width": 680,
    "overlay_height": 300,
    "overlay_x": None,
    "overlay_y": None,
    "overlay_background_color": "#20242b",
    "overlay_background_opacity": 88,
    "overlay_font_family": "Microsoft YaHei UI",
    "overlay_font_size": 30,
    "overlay_source_color": "#ffffff",
    "overlay_translation_color": "#91d9e6",
    "overlay_follow_theme": True,
    "overlay_display_mode": "bilingual",
    "overlay_show_speaker": True,
    "overlay_show_draft": True,
    "overlay_locked": False,
    "overlay_always_on_top": True,
}
_MODES = (("双语", "bilingual"), ("原文", "source"), ("译文", "translation"))
def _bounded_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return fallback


def _valid_color(value: Any, fallback: str) -> str:
    color = QColor(str(value or ""))
    return color.name(QColor.NameFormat.HexRgb).lower() if color.isValid() else fallback


def _contrast_text(background: str) -> str:
    color = QColor(background)
    channels = [color.redF(), color.greenF(), color.blueF()]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    luminance = .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    return "#ffffff" if luminance < .179 else "#263746"


def _overlay_palette(theme_id: str) -> dict[str, str]:
    palette = palette_for(theme_id)
    return {
        "toolbar_bg": palette["surface"], "toolbar_fg": palette["text"],
        "accent": palette["accent"], "status_fg": palette["accent"],
        "badge_bg": palette["soft_surface"], "badge_fg": palette["accent"],
        "badge_border": palette["border"], "source_color": palette["text"],
        "translation_color": palette["translation"], "background_color": palette["window"],
        "border": palette["border"], "hover": palette["accent_hover"],
        "muted": palette["muted"], "disabled_text": palette["disabled_text"],
        "selection_text": palette["accent_text"],
    }


def _clean_preferences(values: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(values or {})
    prefs = dict(_DEFAULTS)
    for key in prefs:
        if key in raw:
            prefs[key] = raw[key]
    prefs["overlay_width"] = _bounded_int(prefs["overlay_width"], 320, 1600, 680)
    prefs["overlay_height"] = _bounded_int(prefs["overlay_height"], 160, 1200, 300)
    prefs["overlay_background_opacity"] = _bounded_int(prefs["overlay_background_opacity"], 15, 100, 88)
    prefs["overlay_font_size"] = _bounded_int(prefs["overlay_font_size"], 12, 72, 30)
    for key in ("overlay_x", "overlay_y"):
        try:
            prefs[key] = int(prefs[key]) if prefs[key] is not None else None
        except (TypeError, ValueError, OverflowError):
            prefs[key] = None
    prefs["overlay_background_color"] = _valid_color(prefs["overlay_background_color"], "#20242b")
    prefs["overlay_source_color"] = _valid_color(prefs["overlay_source_color"], "#ffffff")
    prefs["overlay_translation_color"] = _valid_color(prefs["overlay_translation_color"], "#91d9e6")
    prefs["overlay_font_family"] = str(prefs["overlay_font_family"] or "").strip()
    installed_fonts = {family.casefold(): family for family in QFontDatabase.families()}
    if prefs["overlay_font_family"].casefold() not in installed_fonts:
        preferred = installed_fonts.get("microsoft yahei ui")
        prefs["overlay_font_family"] = preferred or QFontDatabase.systemFont(
            QFontDatabase.SystemFont.GeneralFont
        ).family()
    else:
        prefs["overlay_font_family"] = installed_fonts[prefs["overlay_font_family"].casefold()]
    if prefs["overlay_display_mode"] not in {mode for _, mode in _MODES}:
        prefs["overlay_display_mode"] = "bilingual"
    for key in ("overlay_show_speaker", "overlay_show_draft", "overlay_locked", "overlay_always_on_top", "overlay_follow_theme"):
        prefs[key] = bool(prefs[key])
    return prefs


class _DragHeader(QWidget):
    def __init__(self, owner: "SubtitleOverlay"):
        super().__init__(owner)
        self.owner = owner
        self._press_pos: QPoint | None = None

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and not self.owner.preferences()["overlay_locked"]:
            self._press_pos = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        if self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self._press_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if self._press_pos is not None:
            self._press_pos = None
            self.owner.setGeometry(self.owner._screen_safe_rect(
                self.owner.x(), self.owner.y(), self.owner.width(), self.owner.height()
            ))
            self.owner._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _AppearanceDialog(QDialog):
    """Edits a temporary preference snapshot and previews it on the owner."""

    def __init__(self, owner: "SubtitleOverlay"):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("字幕设置")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._original = owner.preferences()
        self._draft = dict(self._original)
        self._theme_id = owner._ui_theme
        form = QFormLayout()
        self.contrast_notice = QLabel(self)
        self.contrast_notice.setWordWrap(True)
        self.contrast_notice.setObjectName("overlayContrastNotice")
        from app.theme import palette_for
        self.contrast_notice.setStyleSheet(f"color:{palette_for(owner._ui_theme)['warning']};font-size:12px;")

        self.preset = QComboBox()
        self.preset.addItem("自选", "custom")
        self.preset.addItem("紧凑", "compact")
        self.preset.addItem("舒适", "comfortable")
        self.preset.addItem("大字", "large")
        self.preset.addItem("晴空蓝", "sky_colors")
        self.preset.addItem("春意绿", "spring_colors")
        form.addRow("预设", self.preset)

        self.follow_theme = QCheckBox("跟随软件主题配色", self)
        self.follow_theme.setObjectName("overlayFollowTheme")
        self.follow_theme.setChecked(self._draft["overlay_follow_theme"])
        self.follow_theme.toggled.connect(lambda value: self._set("overlay_follow_theme", value))
        form.addRow("字幕配色", self.follow_theme)

        self.width_spin = self._spin("overlayWidth", 320, 1600, "overlay_width")
        self.height_spin = self._spin("overlayHeight", 160, 1200, "overlay_height")
        dimensions = QWidget(self)
        dimensions_layout = QHBoxLayout(dimensions)
        dimensions_layout.setContentsMargins(0, 0, 0, 0)
        dimensions_layout.addWidget(QLabel("宽"))
        dimensions_layout.addWidget(self.width_spin)
        dimensions_layout.addWidget(QLabel("高"))
        dimensions_layout.addWidget(self.height_spin)
        form.addRow("窗口尺寸", dimensions)

        self.background_color = self._color_control("overlay_background_color", "背景色")
        form.addRow("背景颜色", self.background_color)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(15, 100)
        self.opacity.setValue(self._draft["overlay_background_opacity"])
        self.opacity.valueChanged.connect(self._update_opacity)
        self.opacity.setObjectName("overlayOpacity")
        form.addRow("背景不透明度", self.opacity)

        self.font = QFontComboBox(self)
        self.font.setObjectName("overlayFontFamily")
        self.font.setCurrentFont(QFont(self._draft["overlay_font_family"]))
        self.font.currentFontChanged.connect(lambda f: self._set("overlay_font_family", f.family()))
        form.addRow("字体", self.font)
        self.font_size = self._spin("overlayFontSize", 12, 72, "overlay_font_size")
        self.font_size.setSuffix(' px')
        form.addRow("字号", self.font_size)
        self.source_color = self._color_control("overlay_source_color", "原文颜色")
        form.addRow("原文颜色", self.source_color)
        self.translation_color = self._color_control("overlay_translation_color", "译文颜色")
        form.addRow("译文颜色", self.translation_color)
        self.display_mode = QComboBox(self)
        self.display_mode.setObjectName("overlayDisplayMode")
        for label, value in _MODES:
            self.display_mode.addItem(label, value)
        self.display_mode.setCurrentIndex(self.display_mode.findData(self._draft["overlay_display_mode"]))
        self.display_mode.currentIndexChanged.connect(lambda _i: self._set("overlay_display_mode", self.display_mode.currentData()))
        form.addRow("显示内容", self.display_mode)
        self.show_speaker = QCheckBox("显示说话人", self)
        self.show_speaker.setChecked(self._draft["overlay_show_speaker"])
        self.show_speaker.toggled.connect(lambda value: self._set("overlay_show_speaker", value))
        form.addRow("说话人", self.show_speaker)
        self.show_draft = QCheckBox("显示识别/翻译草稿", self)
        self.show_draft.setChecked(self._draft["overlay_show_draft"])
        self.show_draft.toggled.connect(lambda value: self._set("overlay_show_draft", value))
        form.addRow("草稿", self.show_draft)

        form.addRow("颜色对比", self.contrast_notice)
        self._update_contrast_notice()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.restore_defaults_button = QPushButton("恢复默认外观", self)
        self.restore_defaults_button.setObjectName("overlayRestoreDefaults")
        self.restore_defaults_button.clicked.connect(self._restore_appearance_defaults)
        layout.addWidget(self.restore_defaults_button)
        layout.addWidget(buttons)

        self.preset.currentIndexChanged.connect(self._apply_preset)
        self._apply_dialog_theme()
        try:
            from app.appearance import watch_theme
            watch_theme(self,self.apply_ui_theme)
        except (ImportError, AttributeError, TypeError):
            pass

    def apply_ui_theme(self, theme_id: str) -> None:
        from app.theme import palette_for
        if hasattr(self,'contrast_notice'):
            self.contrast_notice.setStyleSheet(f"color:{palette_for(theme_id)['warning']};font-size:12px;")
        self._theme_id = theme_id
        self._apply_dialog_theme()

    def _apply_dialog_theme(self) -> None:
        try:
            from app.theme import style_for
            self.setStyleSheet(style_for(self._theme_id))
        except (ImportError, AttributeError, TypeError):
            pass
        # Color swatches are deliberately independent of the global widget style.
        for button, key in ((self.background_color, "overlay_background_color"), (self.source_color, "overlay_source_color"), (self.translation_color, "overlay_translation_color")):
            self._paint_color_button(button, self._effective_color(key))
        self._sync_color_controls()

    def _spin(self, name: str, low: int, high: int, key: str) -> QSpinBox:
        widget = QSpinBox(self)
        widget.setObjectName(name)
        widget.setRange(low, high)
        widget.setValue(self._draft[key])
        widget.valueChanged.connect(lambda value, pref=key: self._set(pref, value))
        return widget

    def _color_control(self, key: str, label: str) -> QPushButton:
        button = QPushButton(label, self)
        button.setObjectName(key)
        self._paint_color_button(button, self._draft[key])
        button.clicked.connect(lambda _checked=False, pref=key, target=button: self._choose_color(pref, target))
        return button

    def _paint_color_button(self, button: QPushButton, color: str) -> None:
        button.setText(color)
        value=QColor(color)
        foreground=_contrast_text(color)
        border=palette_for(self._theme_id)["border"]
        button.setStyleSheet(f"text-align:left; padding:6px; border:1px solid {border}; background:{color};color:{foreground};")

    def _effective_color(self, key: str) -> str:
        if self._draft["overlay_follow_theme"]:
            names = {"overlay_background_color": "background_color", "overlay_source_color": "source_color",
                     "overlay_translation_color": "translation_color"}
            return _overlay_palette(self._theme_id)[names[key]]
        return self._draft[key]

    def _sync_color_controls(self) -> None:
        follows = self._draft["overlay_follow_theme"]
        for button, key in ((self.background_color, "overlay_background_color"),
                            (self.source_color, "overlay_source_color"),
                            (self.translation_color, "overlay_translation_color")):
            button.setEnabled(not follows)
            self._paint_color_button(button, self._effective_color(key))

    def _choose_color(self, key: str, button: QPushButton) -> None:
        picked = QColorDialog.getColor(QColor(self._effective_color(key)), self, "选择颜色")
        if picked.isValid():
            self._set("overlay_follow_theme", False)
            self._set(key, picked.name(QColor.NameFormat.HexRgb).lower())
            self._paint_color_button(button, self._draft[key])

    def _set(self, key: str, value: Any) -> None:
        self._draft[key] = value
        if key == "overlay_follow_theme":
            self._sync_color_controls()
        self.owner._preview_preferences(self._draft)
        self._update_contrast_notice()

    def _restore_appearance_defaults(self) -> None:
        keys = (
            "overlay_width", "overlay_height", "overlay_background_color",
            "overlay_background_opacity", "overlay_font_family", "overlay_font_size",
            "overlay_source_color", "overlay_translation_color", "overlay_show_speaker",
            "overlay_show_draft", "overlay_follow_theme",
        )
        for key in keys:
            self._draft[key] = _DEFAULTS[key]
        self._draft["overlay_display_mode"] = self._original["overlay_display_mode"]
        self._draft["overlay_x"] = self._original["overlay_x"]
        self._draft["overlay_y"] = self._original["overlay_y"]
        self.width_spin.setValue(self._draft["overlay_width"])
        self.height_spin.setValue(self._draft["overlay_height"])
        self.opacity.setValue(self._draft["overlay_background_opacity"])
        self.font.setCurrentFont(QFont(self._draft["overlay_font_family"]))
        self.font_size.setValue(self._draft["overlay_font_size"])
        self.display_mode.setCurrentIndex(self.display_mode.findData(self._draft["overlay_display_mode"]))
        self.show_speaker.setChecked(self._draft["overlay_show_speaker"])
        self.show_draft.setChecked(self._draft["overlay_show_draft"])
        self.follow_theme.setChecked(self._draft['overlay_follow_theme'])
        for button, key in ((self.background_color, "overlay_background_color"),
                            (self.source_color, "overlay_source_color"),
                            (self.translation_color, "overlay_translation_color")):
            self._paint_color_button(button, self._draft[key])
        self._sync_color_controls()
        self.owner._preview_preferences(self._draft)
        self._update_contrast_notice()

    def _update_contrast_notice(self) -> None:
        background = QColor(self._effective_color("overlay_background_color"))

        def luminance(color: QColor) -> float:
            channels = [color.redF(), color.greenF(), color.blueF()]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
            return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

        low = []
        for key, label in (("overlay_source_color", "原文"), ("overlay_translation_color", "译文")):
            values = sorted((luminance(background), luminance(QColor(self._effective_color(key)))), reverse=True)
            if (values[0] + .05) / (values[1] + .05) < 4.5:
                low.append(label)
        self.contrast_notice.setText(
            f"{', '.join(low)}颜色与背景对比偏低，可继续使用自选颜色。" if low
            else "文字与背景对比良好。仍可继续使用自选颜色。"
        )

    def _update_opacity(self, value: int) -> None:
        self._set("overlay_background_opacity", value)

    def _apply_preset(self, _index: int) -> None:
        preset = self.preset.currentData()
        if preset in {"sky_colors", "spring_colors"}:
            self._draft["overlay_follow_theme"] = False
            self.follow_theme.blockSignals(True)
            self.follow_theme.setChecked(False)
            self.follow_theme.blockSignals(False)
            palette = _overlay_palette(preset.removesuffix("_colors"))
            for key, button, palette_key in (("overlay_background_color", self.background_color, "background_color"), ("overlay_source_color", self.source_color, "source_color"), ("overlay_translation_color", self.translation_color, "translation_color")):
                self._draft[key] = palette[palette_key]
                self._paint_color_button(button, self._draft[key])
            self.owner._preview_preferences(self._draft)
            self._sync_color_controls()
            self._update_contrast_notice()
            return
        values = {
            "compact": (520, 220, 24),
            "comfortable": (680, 300, 30),
            "large": (900, 420, 40),
        }.get(preset)
        if values:
            self.width_spin.setValue(values[0])
            self.height_spin.setValue(values[1])
            self.font_size.setValue(values[2])

    def accept(self) -> None:
        super().accept()

    def reject(self) -> None:
        self.owner._preview_preferences(self._original)
        super().reject()


class SubtitleOverlay(QWidget):
    """A tool window for captions; it never owns or stops the meeting session."""

    preferences_changed = pyqtSignal(dict)
    control_requested = pyqtSignal(str)
    translation_enabled_changed = pyqtSignal(bool)
    visibility_changed = pyqtSignal(bool)
    hidden = pyqtSignal()

    def __init__(self, settings: dict[str, Any] | None = None, parent: QWidget | None = None):
        # Keep a Python ownership reference, but avoid a native QWidget parent:
        # Windows hides native owned tool windows when their owner is minimized.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.owner = parent
        if parent is not None:
            parent.destroyed.connect(self._owner_destroyed)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("实时字幕")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(320, 160)
        self._prefs = _clean_preferences(settings)
        self._translation_mode = str((settings or {}).get("translation_mode", "local"))
        from app.appearance import current_theme
        self._ui_theme = current_theme(parent)
        self._translation_preparing = False
        self._session_transitioning = False
        self._session_stop_pending = False
        self._applying_geometry = True
        self.background_color = QColor(self._prefs["overlay_background_color"])
        self.appearance_dialog: _AppearanceDialog | None = None
        self._build_ui()
        try:
            from app.appearance import current_theme, watch_theme
            self._ui_theme = current_theme()
            watch_theme(self, self.apply_ui_theme)
        except (ImportError, AttributeError, TypeError):
            pass
        self._apply_visual_preferences()
        self._restore_geometry()
        self._applying_geometry = False
        self._sync_translation_control()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 6)
        root.setSpacing(7)

        header = _DragHeader(self)
        self.drag_header = header
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        primary = QHBoxLayout()
        secondary = QHBoxLayout()
        header_layout.addLayout(primary)
        header_layout.addLayout(secondary)
        primary.setContentsMargins(0, 0, 0, 0)
        secondary.setContentsMargins(0, 0, 0, 0)
        title = QLabel("实时字幕", header)
        title.setStyleSheet("font-weight:600")
        primary.addWidget(title)
        self.status_label = QLabel("待开始", header)
        self.status_label.setObjectName("overlayStatus")
        self.status_label.setAccessibleName("听写状态")
        primary.addWidget(self.status_label)
        primary.addStretch(1)
        self.pause_button = QPushButton("暂停", header)
        primary.addWidget(self.pause_button)
        self.pause_button.clicked.connect(lambda: self.control_requested.emit("pause"))
        self.show_main_button = QPushButton("返回主窗口", header)
        primary.addWidget(self.show_main_button)
        self.show_main_button.setEnabled(True)
        self.show_main_button.clicked.connect(lambda: self.control_requested.emit("show_main"))
        self.hide_button=QPushButton('×',header)
        self.hide_button.setToolTip('隐藏字幕窗，听写与会议保存仍继续。主窗口或托盘可以再次显示字幕。')
        self.hide_button.setFixedWidth(28)
        self.hide_button.clicked.connect(self.close)
        primary.addWidget(self.hide_button)
        self.translation_toggle = QCheckBox("实时翻译", header)
        self.translation_toggle.toggled.connect(self._request_translation)
        secondary.addWidget(self.translation_toggle)
        self.appearance_button = QPushButton("字幕设置", header)
        self.appearance_button.clicked.connect(self.open_settings)
        secondary.addWidget(self.appearance_button)
        self.lock_toggle = QCheckBox("锁定", header)
        self.lock_toggle.toggled.connect(lambda value: self._set_preference("overlay_locked", value))
        secondary.addWidget(self.lock_toggle)
        self.topmost_toggle = QCheckBox("置顶", header)
        self.topmost_toggle.toggled.connect(self._set_topmost)
        secondary.addWidget(self.topmost_toggle)
        self.display_mode_combo = QComboBox(header)
        self.display_mode_combo.setToolTip("选择字幕显示原文、译文或双语")
        for label, value in _MODES:
            self.display_mode_combo.addItem(label, value)
        self.display_mode_combo.currentIndexChanged.connect(self._mode_changed)
        secondary.addWidget(self.display_mode_combo)
        secondary.addStretch(1)
        root.addWidget(header)

        self.empty_label = QLabel("会议开始后，实时字幕会显示在这里。\n可以拖动窗口，或在外观中调整字体和背景。", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        self.speaker_label = QLabel(self)
        self.speaker_label.setObjectName("overlaySpeaker")
        root.addWidget(self.speaker_label)
        self.source_badge = QLabel(self)
        self.source_badge.setObjectName("overlayAudioSource")
        root.addWidget(self.source_badge)

        self.source_scroll = self._scroll_label("overlaySource")
        self.source_label = self.source_scroll.widget()
        root.addWidget(self.source_scroll, 2)
        self.translation_scroll = self._scroll_label("overlayTranslation")
        self.translation_label = self.translation_scroll.widget()
        root.addWidget(self.translation_scroll, 2)
        self.translation_status = QLabel("", self)
        self.translation_status.setWordWrap(True)
        root.addWidget(self.translation_status)
        self.draft_label = QLabel("", self)
        for label in (self.speaker_label,self.translation_status,self.draft_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.draft_label.setWordWrap(True)
        self.draft_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.draft_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setObjectName("overlayResizeGrip")
        footer.addWidget(self.resize_grip, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(footer)

        self.lock_toggle.setChecked(self._prefs["overlay_locked"])
        self.topmost_toggle.setChecked(self._prefs["overlay_always_on_top"])
        self.display_mode_combo.setCurrentIndex(self.display_mode_combo.findData(self._prefs["overlay_display_mode"]))
        self._set_caption_content(None)

    @staticmethod
    def _scroll_label(name: str) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName(name + "Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        label = QLabel()
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll.setWidget(label)
        scroll.setStyleSheet('QScrollArea, QScrollArea QWidget { background:transparent; border:0; }')
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    def preferences(self) -> dict[str, Any]:
        self._save_position()
        return deepcopy(self._prefs)

    def _set_preference(self, key: str, value: Any, emit: bool = True) -> None:
        candidate = _clean_preferences({**self._prefs, key: value})
        if candidate == self._prefs:
            return
        self._prefs = candidate
        self._apply_visual_preferences()
        if emit:
            self.preferences_changed.emit(self.preferences())

    def _effective_colors(self) -> dict[str, str]:
        theme = palette_for(self._ui_theme)
        if self._prefs["overlay_follow_theme"]:
            return {"background": theme["window"], "source": theme["text"],
                    "translation": theme["translation"], "text": theme["text"],
                    "muted": theme["muted"], "border": theme["border"],
                    "accent": theme["accent"], "accent_hover": theme["accent_hover"],
                    "accent_text": theme["accent_text"], "warning": theme["warning"],
                    "error": theme["error"], "draft": theme["draft_text"]}
        background = self._prefs["overlay_background_color"]
        contrast = _contrast_text(background)
        return {"background": background, "source": self._prefs["overlay_source_color"],
                "translation": self._prefs["overlay_translation_color"], "text": contrast,
                "muted": contrast, "border": theme["border"], "accent": contrast,
                "accent_hover": theme["accent_hover"], "accent_text": theme["accent_text"],
                "warning": contrast, "error": contrast, "draft": contrast}

    def _set_topmost(self, value: bool) -> None:
        self._set_preference("overlay_always_on_top", value)
        self._set_window_flag(Qt.WindowType.WindowStaysOnTopHint, value)

    def _set_window_flag(self, flag: Qt.WindowType, enabled: bool) -> None:
        was_visible = self.isVisible()
        flags = self.windowFlags()
        self.setWindowFlag(flag, enabled)
        if was_visible:
            self.show()

    def _mode_changed(self, _index: int) -> None:
        mode = self.display_mode_combo.currentData()
        self._set_preference("overlay_display_mode", mode)
        self._refresh_caption_visibility()

    def _request_translation(self, enabled: bool) -> None:
        self.translation_enabled_changed.emit(enabled)

    def apply_preferences(self, settings: dict[str, Any]) -> None:
        """Apply controller-confirmed settings and synchronize the actual mode."""
        incoming = dict(settings or {})
        merged = {**self._prefs, **{k: v for k, v in incoming.items() if k.startswith("overlay_")}}
        self._prefs = _clean_preferences(merged)
        if "translation_mode" in incoming:
            self._translation_mode = str(incoming["translation_mode"] or "off")
        self._apply_visual_preferences()
        self._restore_geometry()
        self._sync_translation_control()
        self._sync_preference_controls()

    def _sync_translation_control(self) -> None:
        enabled = self._translation_mode != "off"
        self.translation_toggle.blockSignals(True)
        self.translation_toggle.setChecked(enabled)
        self.translation_toggle.blockSignals(False)

    def _sync_preference_controls(self) -> None:
        self.lock_toggle.blockSignals(True)
        self.lock_toggle.setChecked(self._prefs["overlay_locked"])
        self.lock_toggle.blockSignals(False)
        self.topmost_toggle.blockSignals(True)
        self.topmost_toggle.setChecked(self._prefs["overlay_always_on_top"])
        self.topmost_toggle.blockSignals(False)
        self.display_mode_combo.blockSignals(True)
        self.display_mode_combo.setCurrentIndex(self.display_mode_combo.findData(self._prefs["overlay_display_mode"]))
        self.display_mode_combo.blockSignals(False)
        self._set_window_flag(Qt.WindowType.WindowStaysOnTopHint, self._prefs["overlay_always_on_top"])

    def update_caption(self, row: dict[str, Any] | None, draft: str = "", translation_draft: str = "") -> None:
        self._set_caption_content(row, draft, translation_draft)

    def _set_caption_content(self, row: dict[str, Any] | None, draft: str = "", translation_draft: str = "") -> None:
        row = row if isinstance(row, dict) else None
        self._current_row = row
        source = str((row or {}).get("source") or (row or {}).get("text") or "")
        translation = str((row or {}).get("translation") or "")
        if row and translation:
            if row.get("translation_stale"):
                translation = f"（旧译文，待更新）{translation}"
            elif row.get("translation_error"):
                translation = f"（翻译未完成）{translation}"
            elif row.get("translation_pending"):
                translation = f"（翻译中）{translation}"
        speaker = str((row or {}).get("speaker_name") or (row or {}).get("participant_name") or "")
        if not speaker and (row or {}).get("speaker") is not None:
            speaker = f"说话人 {row['speaker']}"
        self.source_label.setText(source)
        self.translation_label.setText(translation)
        self._apply_caption_fonts()
        self._align_caption(self.source_label, source)
        self._align_caption(self.translation_label, translation)
        self.speaker_label.setText(speaker)
        audio_source = str((row or {}).get("audio_source") or "").strip()
        self.source_badge.setText({"system":"系统声音", "mic":"麦克风", "main":"主音源"}.get(audio_source,audio_source))
        self.source_badge.setVisible(bool(audio_source))
        self.speaker_label.setVisible(bool(speaker) and self._prefs["overlay_show_speaker"])
        self.empty_label.setVisible(not bool(source or translation or draft or translation_draft))
        draft_parts = []
        if draft:
            draft_parts.append(f"识别草稿：{draft}")
        if translation_draft:
            draft_parts.append(f"翻译草稿：{translation_draft}")
        self.draft_label.setText("　·　".join(draft_parts))
        self._apply_caption_fonts()
        self.draft_label.setVisible(bool(draft_parts) and self._prefs["overlay_show_draft"])

        status = []
        if row:
            if row.get("translation_pending"):
                status.append("翻译中，译文尚未更新")
            if row.get("translation_stale"):
                status.append("译文已过期，等待重新翻译")
            if row.get("translation_error"):
                err = row.get("translation_error")
                status.append("翻译未完成" + (f"：{err}" if isinstance(err, str) and err.strip() else ""))
        self.translation_status.setText(" · ".join(status))
        colors = self._effective_colors()
        self.translation_status.setStyleSheet(f"color:{colors['warning']};")
        self.translation_status.setVisible(bool(status))
        self._refresh_caption_visibility()

    def _refresh_caption_visibility(self) -> None:
        mode = self._prefs["overlay_display_mode"]
        has_source = bool(getattr(self, "_current_row", None) and (
            self._current_row.get("source") or self._current_row.get("text")
        ))
        row = getattr(self, "_current_row", None)
        speaker = self.speaker_label.text() if hasattr(self, "speaker_label") else ""
        self.speaker_label.setVisible(bool(speaker) and self._prefs["overlay_show_speaker"])
        self.draft_label.setVisible(bool(self.draft_label.text()) and self._prefs["overlay_show_draft"])
        has_translation = bool(row and row.get("translation"))
        source_visible = mode in {"source", "bilingual"} and has_source
        translation_visible = mode in {"translation", "bilingual"} and has_translation
        self.source_scroll.setVisible(source_visible)
        self.translation_scroll.setVisible(translation_visible)
        if mode == "translation" and not has_translation:
            self.empty_label.setText(
                "只显示译文；翻译已关闭。" if self._translation_mode == "off"
                else "只显示译文；译文尚未生成。"
            )
            self.empty_label.setVisible(True)
        elif not has_source and not has_translation and not self.draft_label.text():
            self.empty_label.setText("会议开始后，实时字幕会显示在这里。\n可以拖动窗口，或在字幕设置中调整字体和背景。")
            self.empty_label.setVisible(True)
        else:
            self.empty_label.setVisible(False)
        # Error or stale state stays visible in every mode so old output is never implied current.
        if self.translation_status.text():
            self.translation_status.setVisible(True)

    @staticmethod
    def _align_caption(label: QLabel, text: str) -> None:
        first_strong = next((ch for ch in text if ch.isalpha()), "")
        arabic = bool(first_strong and "\u0600" <= first_strong <= "\u08ff")
        alignment = Qt.AlignmentFlag.AlignRight if arabic else Qt.AlignmentFlag.AlignLeft
        label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)

    def set_session_state(self, running: bool, paused: bool, transitioning: bool = False, stop_pending: bool = False) -> None:
        self._session_transitioning = bool(transitioning)
        self._session_stop_pending = bool(stop_pending)
        self.pause_button.setText("继续" if paused else "暂停")
        self.pause_button.setEnabled(bool(running) and not transitioning and not stop_pending)
        self.translation_toggle.setEnabled(not self._translation_preparing and not transitioning and not stop_pending)
        self.show_main_button.setEnabled(True)
        if stop_pending:
            self.set_status("正在结束", "busy")
        elif transitioning:
            self.set_status("正在切换听写状态", "busy")
        elif paused:
            self.set_status("已暂停", "paused")
        elif running:
            self.set_status("正在听写", "listening")
        else:
            self.set_status("未在听写", "idle")

    def set_status(self, text: str, kind: str = "idle") -> None:
        """Show a short persistent session status independent of caption updates."""
        kind = str(kind or "idle")
        message = str(text or "")
        self.status_label.setText(message if len(message)<=26 else message[:25]+"…")
        self.status_label.setProperty("statusKind", kind)
        colors = self._effective_colors()
        status_color = {"error": colors["error"], "paused": colors["warning"],
                        "busy": colors["warning"], "listening": colors["accent"],
                        "idle": colors["muted"]}.get(kind, colors["text"])
        self.status_label.setStyleSheet(f"font-size:12px; color:{status_color};")
        status_palette = QPalette(self.status_label.palette())
        status_palette.setColor(self.status_label.foregroundRole(), QColor(status_color))
        self.status_label.setPalette(status_palette)
        self.status_label.setToolTip(message)

    def set_translation_preparing(self, preparing: bool) -> None:
        """Mark translation startup while leaving pause and return controls usable."""
        self._translation_preparing = bool(preparing)
        self.translation_toggle.setText("实时翻译（准备中）" if preparing else "实时翻译")
        if preparing:
            self.translation_toggle.blockSignals(True)
            self.translation_toggle.setChecked(self._translation_mode != "off")
            self.translation_toggle.blockSignals(False)
        else:
            self._sync_translation_control()
        self.translation_toggle.setEnabled(
            not preparing and not self._session_transitioning and not self._session_stop_pending
        )

    def open_appearance(self) -> None:
        if self.appearance_dialog is not None and self.appearance_dialog.isVisible():
            self.appearance_dialog.raise_()
            return
        dialog = _AppearanceDialog(self)
        self.appearance_dialog = dialog
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self.appearance_dialog = None
        if accepted:
            self._commit_appearance(dialog._draft)

    def open_settings(self) -> None:
        """Open the overlay's own appearance settings dialog."""
        self.open_appearance()

    def _preview_preferences(self, values: dict[str, Any]) -> None:
        self._prefs = _clean_preferences(values)
        self._apply_visual_preferences()
        self._sync_preference_controls()

    def _commit_appearance(self, values: dict[str, Any]) -> None:
        self._prefs = _clean_preferences(values)
        self._apply_visual_preferences()
        self._sync_preference_controls()
        self.preferences_changed.emit(self.preferences())

    def _apply_visual_preferences(self) -> None:
        if not hasattr(self, "source_label"):
            return
        self._applying_geometry = True
        self.resize(self._prefs["overlay_width"], self._prefs["overlay_height"])
        colors = self._effective_colors()
        self.background_color = QColor(colors["background"])
        self.background_color.setAlpha(round(self._prefs["overlay_background_opacity"] * 2.55))
        alpha = self.background_color.alpha()
        font = QFont(self._prefs["overlay_font_family"], self._prefs["overlay_font_size"])
        font.setPixelSize(self._prefs['overlay_font_size'])
        for label in (self.source_label, self.translation_label):
            label.setFont(font)
        self._apply_caption_fonts()
        self.resize_grip.setEnabled(not self._prefs["overlay_locked"])
        palette = _overlay_palette(self._ui_theme)
        contrast = colors["text"]
        control_style = (f"QPushButton, QComboBox {{background:{palette['toolbar_bg']};color:{palette['toolbar_fg']};"
                         f"border:1px solid {palette['badge_border']};border-radius:5px;padding:3px 5px;}}"
                         f"QPushButton:hover, QPushButton:pressed {{background:{palette['accent']};color:{palette['selection_text']};}}"
                         f"QPushButton:disabled, QComboBox:disabled {{color:{palette['disabled_text']};}}")
        for control in (self.pause_button, self.show_main_button, self.hide_button,
                        self.appearance_button, self.display_mode_combo):
            control.setStyleSheet(control_style)
        self.source_badge.setStyleSheet(
            f"color:{palette['badge_fg']};background:{palette['badge_bg']};"
            f"border:1px solid {palette['badge_border']};border-radius:4px;"
            "padding:2px 6px;font-size:12px;font-weight:600;"
        )
        themed_style = style_for(self._ui_theme)
        self.setStyleSheet(themed_style+
            "SubtitleOverlay {background:transparent;}"
            f"QLabel#overlaySpeaker {{color:{contrast};font-size:12px;}}"
            "QLabel { background:transparent; }"
            f"QWidget {{color:{palette['toolbar_fg']};}}"
            f"QPushButton, QComboBox {{background:{palette['toolbar_bg']};color:{palette['toolbar_fg']};border:1px solid {palette['badge_border']};border-radius:5px;padding:3px 5px;}}"
            f"QPushButton:hover {{background:{palette['accent']};color:{palette['selection_text']};}}"
            f"QPushButton:disabled {{color:{palette['disabled_text']};}}"
            f"QComboBox QAbstractItemView {{background:{palette['toolbar_bg']};color:{palette['toolbar_fg']};selection-background-color:{palette['accent']};selection-color:{palette['selection_text']};border:1px solid {palette['border']};}}"
            f"QLabel#overlayAudioSource {{color:{palette['badge_fg']};background:{palette['badge_bg']};border:1px solid {palette['badge_border']};border-radius:4px;padding:2px 6px;font-size:12px;font-weight:600;}}"
            f"QScrollBar:vertical {{background:{palette['toolbar_bg']};width:7px;border:1px solid {palette['border']};}}"
            f"QScrollBar::handle:vertical {{background:{palette['accent']};min-height:15px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical:hover {{background:{palette['hover']};}}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}"
        )
        self._refresh_caption_visibility()
        for checkbox in (self.translation_toggle,self.lock_toggle,self.topmost_toggle):
            checkbox.setStyleSheet(f'QCheckBox {{color:{contrast};}} QCheckBox::indicator {{border:1px solid {colors["border"]};background:{palette["toolbar_bg"]};}} QCheckBox::indicator:checked {{background:{palette["accent"]};}}')
        self.empty_label.setStyleSheet(f'color:{contrast};background:transparent;')
        self.translation_status.setStyleSheet(f"color:{colors['warning']};")
        self.set_status(self.status_label.toolTip() or self.status_label.text(), self.status_label.property("statusKind") or "idle")
        self.update()

    def apply_ui_theme(self, theme_id: str) -> None:
        """Apply a global UI theme while preserving all caption preferences."""
        self._ui_theme = normalize_theme(theme_id)
        self._apply_visual_preferences()
        if self.appearance_dialog is not None and self.appearance_dialog.isVisible():
            self.appearance_dialog.apply_ui_theme(self._ui_theme)

    def _apply_caption_fonts(self) -> None:
        from app.text_fonts import css_family
        colors = self._effective_colors()
        for label, color in ((self.source_label,colors['source']),(self.translation_label,colors['translation'])):
            family=css_family(label.text(),self._prefs['overlay_font_family'])
            label.setStyleSheet(f'color:{color};background:transparent;font-family:"{family}";font-size:{self._prefs["overlay_font_size"]}px;padding:4px;')
            label_palette = QPalette(label.palette())
            label_palette.setColor(label.foregroundRole(), QColor(color))
            label.setPalette(label_palette)
        self.draft_label.setStyleSheet(f'color:{colors["draft"]};background:transparent;font-family:"{css_family(self.draft_label.text(),self._prefs["overlay_font_family"])}";font-size:14px;')
        self._applying_geometry = False

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.background_color)
        painter.setPen(QPen(QColor(palette_for(self._ui_theme)["border"]),1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),8,8)

    def _restore_geometry(self) -> None:
        self._applying_geometry = True
        width, height = self._prefs["overlay_width"], self._prefs["overlay_height"]
        x, y = self._prefs["overlay_x"], self._prefs["overlay_y"]
        if x is None or y is None:
            screen = QGuiApplication.primaryScreen()
            area = screen.availableGeometry() if screen else None
            if area:
                x, y = area.x() + max(0, (area.width() - width) // 2), area.y() + max(0, (area.height() - height) * 3 // 4)
            else:
                x, y = 80, 80
        self.setGeometry(self._screen_safe_rect(int(x), int(y), width, height))
        self._applying_geometry = False

    @staticmethod
    def _screen_safe_rect(x: int, y: int, width: int, height: int):
        from PyQt6.QtCore import QRect

        screen = QGuiApplication.screenAt(QPoint(x + min(width // 2, 50), y + min(height // 2, 50))) or QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(x, y, width, height)
        area = screen.availableGeometry()
        width = min(width, area.width())
        height = min(height, area.height())
        x = max(area.left(), min(x, area.right() - width + 1))
        y = max(area.top(), min(y, area.bottom() - height + 1))
        return QRect(x, y, width, height)

    def _save_position(self) -> None:
        if not hasattr(self, "_prefs"):
            return
        geometry = self.geometry()
        self._prefs["overlay_x"] = geometry.x()
        self._prefs["overlay_y"] = geometry.y()
        self._prefs["overlay_width"] = max(320, geometry.width())
        self._prefs["overlay_height"] = max(160, geometry.height())

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if hasattr(self, "_prefs"):
            self._prefs["overlay_width"] = event.size().width()
            self._prefs["overlay_height"] = event.size().height()
            self._emit_geometry_preferences()

    def moveEvent(self, event):  # noqa: N802 - Qt API
        super().moveEvent(event)
        if hasattr(self, "_prefs"):
            self._prefs["overlay_x"] = event.pos().x()
            self._prefs["overlay_y"] = event.pos().y()
            self._emit_geometry_preferences()

    def _emit_geometry_preferences(self) -> None:
        if not self._applying_geometry and self.isVisible():
            self.preferences_changed.emit(deepcopy(self._prefs))

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self._save_position()
        event.accept()
        self.visibility_changed.emit(False)
        self.hidden.emit()

    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def _owner_destroyed(self, *_args) -> None:
        self.owner = None
        self.close()
