"""Visual theme coverage smoke for the complete Qt desktop UI.

This script uses only synthetic meeting/model data. It does not start services,
capture audio, open real meeting records, or write into application settings.
Screenshots and a small JSON report are written under logs/ux-theme-complete.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from PyQt6.QtCore import QEventLoop, QTimer, Qt, QTranslator, QLibraryInfo
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QMenu, QMessageBox, QSystemTrayIcon,
    QWidget,
)

from app.qt_bootstrap import configure_application
from app.settings import DEFAULTS, ROOT
from app.appearance import set_theme, current_theme
from app.theme import THEME_CHOICES, palette_for, style_for
from app.ui import MainWindow, SettingsDialog
from app.ai_ui import AIModelDialog
from app.glossary_ui import GlossaryDialog
from app.meeting_ui import ParticipantsDialog, RecoveryDialog
from app.export_ui import ExportDialog
from app.subtitle_overlay import _AppearanceDialog
from app.tools_ui import ToolsDialog
from app.participants import ParticipantRegistry
from app.dialogs import QFileDialog, QColorDialog, QInputDialog, QMessageBox as ThemedMessageBox
from app.icons import app_icon


OUT = REPO / "logs" / "ux-theme-complete"
THEMES = ["dark", "sky", "spring"]
SAMPLE_ROWS = [
    {"id": "theme-smoke-1", "timestamp": 1.25, "source": "Synthetic greeting",
     "translation": "合成问候文本", "language": "en", "speaker": 1,
     "speaker_namespace": "smoke", "audio_source": "main"},
    {"id": "theme-smoke-2", "timestamp": 3.5, "source": "Synthetic follow-up",
     "translation": "合成后续文本", "language": "en", "speaker": 2,
     "speaker_namespace": "smoke", "audio_source": "mic"},
]


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in tuple(self._slots):
            slot(*args)


class _FakeServer:
    def __init__(self):
        self.changed, self.error = _Signal(), _Signal()
        self.ready = False
        self.active = False
        self.url = ""


class _FakeController:
    """Controller surface needed by ToolsDialog; every action stays inert."""
    def __init__(self, window):
        self.window = window
        self.server = _FakeServer()
        self.active = self.starting = self.resuming = self.closing = False
        self.original_view_action = _FakeAction("显示 / 导出原始听写")
        self.long_mode_action = _FakeAction("长会议模式")

    def toggle_pause(self):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        # Tool callbacks are visible but deliberately inert in this smoke.
        return lambda *args, **kwargs: None


class _FakeAction:
    def __init__(self, text):
        self._text = text
        self._checked = False
        self._enabled = True
        self.toggled = _Signal()
        self.changed = _Signal()

    def text(self): return self._text
    def isChecked(self): return self._checked
    def isEnabled(self): return self._enabled
    def setChecked(self, value): self._checked = bool(value)


def _pump(ms=180):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _snapshot(widget: QWidget, name: str, theme: str, report: dict):
    widget.ensurePolished()
    _pump(100)
    image = widget.grab()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    path = OUT / theme / f"{safe}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = image.save(str(path), "PNG")
    report["screenshots"].append({"theme": theme, "name": name,
                                  "path": str(path), "saved": bool(ok),
                                  "size": [image.width(), image.height()]})
    if not ok or image.isNull():
        report["failures"].append(f"screenshot failed: {theme}/{name}")
    return image


def _visible(widget: QWidget, name: str, theme: str, report: dict, *, delay=100):
    widget.show()
    widget.raise_()
    _pump(delay)
    _snapshot(widget, name, theme, report)
    return widget


def _check_widget(widget: QWidget, expected_style: str, label: str, report: dict):
    actual = widget.styleSheet()
    managed = bool(widget.property("themeManaged"))
    ok = (actual == expected_style) and managed
    report["checks"].append({"name": label, "themeManaged": managed,
                            "stylesheetMatches": actual == expected_style})
    if not ok:
        report["failures"].append(f"theme ownership/style mismatch: {label}")


def _close_all(widgets):
    for widget in widgets:
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
    _pump(50)


def _build_registry():
    registry = ParticipantRegistry(meeting_id="theme-smoke", state={
        "meeting_id": "theme-smoke",
        "participants": {
            "p-smoke-1": {"name": "Synthetic Alice", "source": "main", "confirmed": True},
            "p-smoke-2": {"name": "Synthetic Bob", "source": "mic", "confirmed": False},
        },
        "bindings": {"smoke|1": "p-smoke-1", "smoke|2": "p-smoke-2"},
    })
    return registry


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    configure_application(app)
    app.setQuitOnLastWindowClosed(False)
    translator=QTranslator(app)
    translated=translator.load('qtbase_zh_CN',QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    if translated:
        app.installTranslator(translator)

    report = {"themes": THEMES, "screenshots": [], "checks": [], "failures": [],
              "syntheticOnly": True, "serviceStarted": False, "audioCaptured": False,
              "userRecordsRead": False, "settingsFileRead": False,
              "applicationStyleSheetSet": False, "qtChineseTranslation": translated}
    base = deepcopy(DEFAULTS)
    base.update({
        "appearance_theme": "dark", "asr_model": "small",
        "source_language": "en", "target_language": "zh",
        "translation_mode": "local", "save_records": False,
        "server_url": "", "llm_url": "http://127.0.0.1:1234/v1",
        "llm_model": "synthetic-model", "llm_api_token": "",
        "glossary_profile": "Theme Smoke", "glossary_enabled": True,
        "glossary_rules": [
            {"original": "Synthetic", "replacement": "合成", "language": "en",
             "match_mode": "text", "enabled": True, "target_language": "zh",
             "fixed_translation": "", "notes": "synthetic fixture"},
            {"original": "Follow-up", "replacement": "后续", "language": "en",
             "match_mode": "whole_word", "enabled": False, "target_language": "zh",
             "fixed_translation": "", "notes": "synthetic fixture"},
        ],
        "context": "Synthetic context only",
    })
    base["wlk"] = {**(base.get("wlk") or {}), "host": "127.0.0.1", "port": 18000,
                   "model_dir": "", "api_token": ""}
    devices = {"output": ["Synthetic system output"], "input": ["Synthetic microphone"]}

    # Isolate glossary profile discovery from application data.
    from app import glossary_ui
    from PyQt6.QtWidgets import QTabWidget
    tmp_root = tempfile.TemporaryDirectory(prefix="theme-coverage-")
    glossary_ui.GLOSSARY_DIR = Path(tmp_root.name) / "glossaries"

    # Keep ToolsDialog's optional model discovery away from disk and networking.
    original_refresh = ToolsDialog.refresh_models
    original_model_info = getattr(ToolsDialog, "_show_model_details", None)
    def fake_refresh(self, *_):
        self.model_list.clear()
        self.model_list.addItems(["Synthetic ASR model · installed", "Synthetic translator · available"])
        self.backend_list.clear()
        self.backend_list.addItems(["Synthetic backend · ready", "Synthetic backend · optional"])
        self.model_output.setPlainText("Synthetic model inventory; no scan or download performed.")
    ToolsDialog.refresh_models = fake_refresh
    if original_model_info:
        ToolsDialog._show_model_details = lambda self: None

    all_widgets = []
    try:
        window = MainWindow(deepcopy(base), devices)
        all_widgets.append(window)
        window.update_caption(SAMPLE_ROWS)
        window.update_history(SAMPLE_ROWS) if hasattr(window, "update_history") else None

        for theme in THEMES:
            set_theme(theme)
            window.settings["appearance_theme"] = theme
            window._apply_appearance_theme(theme)
            _visible(window, "main_window", theme, report)
            _check_widget(window, style_for(theme), f"main/{theme}", report)
            QTest.mouseMove(window.start_button, window.start_button.rect().center())
            _pump(120)
            _snapshot(window, "main_primary_hover", theme, report)
            if window.history_list.count():
                window.history_list.setCurrentRow(0)
                _snapshot(window, "main_selected_history_row", theme, report)

            # Main window's interactive language pickers and combo popups.
            for key, picker in (("source", window.source_mode),
                                ("target", window.target_language)):
                if hasattr(picker, "showPopup"):
                    picker.showPopup(); _pump(100)
                    popup = picker.view().window()
                    _snapshot(popup, f"main_{key}_combo_popup", theme, report)
                    picker.hidePopup()
            # Custom meeting context menu and tray menu, rendered without firing actions.
            fake_controller = _FakeController(window)
            from app.controller_meeting_tools import MeetingToolsMixin
            MeetingToolsMixin.setup_meeting_tools(fake_controller)
            meeting_menu = fake_controller.meeting_menu
            meeting_menu.popup(window.mapToGlobal(window.rect().center()))
            _pump(120)
            _snapshot(meeting_menu, "meeting_tools_menu", theme, report)
            meeting_menu.close()
            tray_menu = QMenu(window)
            tray_menu.addAction("打开主窗口")
            tray_menu.addAction("显示字幕窗")
            pause = tray_menu.addAction("暂停 / 继续"); pause.setEnabled(False)
            tray_menu.addSeparator(); tray_menu.addAction("退出并保存")
            from app.appearance import watch_theme
            watch_theme(tray_menu)
            tray_menu.popup(window.mapToGlobal(window.rect().center()))
            _pump(120)
            _snapshot(tray_menu, "tray_menu", theme, report)
            tray_menu.close()
            report["checks"].append({"name": "tray icon", "present": not app_icon().isNull(),
                                    "systemTrayAvailable": QSystemTrayIcon.isSystemTrayAvailable()})
            if app_icon().isNull(): report["failures"].append("application icon is null")

            # Every ToolsDialog page: direct tab selection, no service starts or commands.
            tools = ToolsDialog(fake_controller, window)
            all_widgets.append(tools)
            for tab in range(tools.tabs.count()):
                tools.tabs.setCurrentIndex(tab)
                _visible(tools, f"tools_{tab}_{tools.tabs.tabText(tab)}", theme, report)
                _check_widget(tools, style_for(theme), f"tools/{tab}/{theme}", report)
            tools.close()

            # Independent app dialogs; each receives only disposable synthetic rows/state.
            settings = SettingsDialog(deepcopy(base), devices, window)
            all_widgets.append(settings)
            _visible(settings, "settings", theme, report)
            picker = getattr(settings, "target_language_combo", None)
            if picker is not None and hasattr(picker, "completer"):
                completer = picker.completer()
                completer.setCompletionPrefix("Eng")
                completer.complete(); _pump(120)
                popup = completer.popup()
                if popup:
                    _snapshot(popup, "language_completer_popup", theme, report)
                    popup.hide()
            settings_tabs = [tab for tab in settings.findChildren(QTabWidget) if tab.count() == 2]
            outer_tabs = settings_tabs[-1] if settings_tabs else settings.findChild(QTabWidget)
            if outer_tabs is not None:
                for tab in range(outer_tabs.count()):
                    outer_tabs.setCurrentIndex(tab)
                    _snapshot(settings, f"settings_outer_{tab}_{outer_tabs.tabText(tab)}", theme, report)
                    if tab == 0 and hasattr(settings, "common_tabs"):
                        for inner in range(settings.common_tabs.count()):
                            settings.common_tabs.setCurrentIndex(inner)
                            _snapshot(settings, f"settings_common_{inner}_{settings.common_tabs.tabText(inner)}", theme, report)
            glossary = GlossaryDialog(deepcopy(base), window)
            all_widgets.append(glossary)
            _visible(glossary, "glossary", theme, report)
            if glossary.table.rowCount():
                glossary.table.selectRow(0)
                _snapshot(glossary, "glossary_selected_row", theme, report)

            participants = ParticipantsDialog(_build_registry(), SAMPLE_ROWS, window)
            all_widgets.append(participants)
            _visible(participants, "participants", theme, report)
            if participants.participant_list.count():
                participants.participant_list.setCurrentRow(0)
                _snapshot(participants, "participants_selected", theme, report)

            recovery = RecoveryDialog([
                ("synthetic-record-A.json", {"row_count": 2, "last_saved_at": "2099-01-01T00:00:00Z", "rows": SAMPLE_ROWS}),
                ("synthetic-record-B.json", {"row_count": 0, "rows": []}),
            ], window)
            all_widgets.append(recovery)
            _visible(recovery, "recovery", theme, report)
            recovery.records_table.selectRow(0)
            _snapshot(recovery, "recovery_selected_row", theme, report)

            export = ExportDialog(2, 2, window)
            all_widgets.append(export)
            _visible(export, "export", theme, report)
            export.format_combo.showPopup(); _pump(100)
            _snapshot(export.format_combo.view().window(), "export_format_popup", theme, report)
            export.format_combo.hidePopup()

            ai = AIModelDialog(deepcopy(base), lambda: deepcopy(SAMPLE_ROWS),
                               lambda: None, window)
            all_widgets.append(ai)
            ai.result_view.setPlainText("Synthetic AI response\n合成回答")
            _visible(ai, "meeting_ai", theme, report)

            overlay = window.subtitle_overlay
            overlay.update_caption(SAMPLE_ROWS[0], "Synthetic partial", "合成草稿")
            overlay.show(); overlay.raise_(); _pump(150)
            _snapshot(overlay, "subtitle_window", theme, report)
            report["checks"].append({"name": f"subtitle-follow/{theme}",
                                    "uiTheme": getattr(overlay, "_ui_theme", None),
                                    "followTheme": overlay.preferences().get("overlay_follow_theme")})
            if overlay.preferences().get("overlay_follow_theme") and getattr(overlay, "_ui_theme", None) != theme:
                report["failures"].append(f"subtitle window did not follow {theme}")
            overlay.hide()

            overlay_dialog = _AppearanceDialog(window.subtitle_overlay)
            all_widgets.append(overlay_dialog)
            _visible(overlay_dialog, "subtitle_appearance", theme, report)
            overlay_dialog.preset.showPopup(); _pump(100)
            _snapshot(overlay_dialog.preset.view().window(), "subtitle_preset_popup", theme, report)
            overlay_dialog.preset.hidePopup()

            # Native-dialog replacements are directly instantiated and cancelled.
            with tempfile.TemporaryDirectory(prefix="theme-picker-") as picker_tmp:
                file_picker = QFileDialog(window, "测试文件选择器", picker_tmp, "所有文件 (*.*)")
                all_widgets.append(file_picker)
                _visible(file_picker, "file_picker", theme, report)
                color_picker = QColorDialog(QColor("#43A4B8"), window)
                all_widgets.append(color_picker)
                _visible(color_picker, "color_picker", theme, report)
            for cls, label in ((QInputDialog, "input_dialog"), (ThemedMessageBox, "message_box")):
                dialog = cls(window)
                all_widgets.append(dialog)
                if isinstance(dialog, QInputDialog):
                    dialog.setWindowTitle("合成输入"); dialog.setLabelText("仅用于主题预览")
                    dialog.setTextValue("Synthetic value")
                else:
                    dialog.setWindowTitle("合成提示"); dialog.setText("仅用于主题预览")
                    dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
                _visible(dialog, label, theme, report)

            # QSS-managed key foreground/selected-row evidence.
            from PyQt6.QtGui import QPalette
            palette = app.palette()
            text_color = palette.color(QPalette.ColorRole.Text).name()
            highlighted = palette.color(QPalette.ColorRole.HighlightedText).name()
            expected = palette_for(theme)
            report["checks"].append({"name": f"palette/{theme}", "text": text_color,
                                    "expectedText": QColor(expected["text"]).name(),
                                    "highlightedText": highlighted,
                                    "expectedSelectedText": QColor(expected["accent_text"]).name()})
            if text_color.lower() != QColor(expected["text"]).name().lower():
                report["failures"].append(f"foreground palette mismatch: {theme}")
            if highlighted.lower() != QColor(expected["accent_text"]).name().lower():
                report["failures"].append(f"selected foreground palette mismatch: {theme}")

            _close_all(all_widgets[1:])
            all_widgets = [window]

        # Switch themes while a Qt-owned popup stays open. This exercises the
        # real transient-window watcher rather than only styling newly opened popups.
        set_theme("dark")
        window._apply_appearance_theme("dark")
        window.source_mode.showPopup(); _pump(120)
        open_popup = window.source_mode.view().window()
        for switched in ("sky", "spring", "dark"):
            set_theme(switched)
            window.settings["appearance_theme"] = switched
            window._apply_appearance_theme(switched)
            _pump(120)
            _snapshot(open_popup, f"open_combo_popup_{switched}", switched, report)
            managed = bool(open_popup.property("themeManaged"))
            style_ok = open_popup.styleSheet() == style_for(switched)
            report["checks"].append({"name": f"open-popup-switch/{switched}",
                                    "themeManaged": managed, "stylesheetMatches": style_ok})
            if not managed or not style_ok:
                report["failures"].append(f"open combo popup did not retheme to {switched}")
        window.source_mode.hidePopup()
        _close_all(all_widgets)
    finally:
        ToolsDialog.refresh_models = original_refresh
        if original_model_info:
            ToolsDialog._show_model_details = original_model_info
        tmp_root.cleanup()
        app.processEvents()
        report["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"report": str(OUT / "report.json"),
                      "screenshots": len(report["screenshots"]),
                      "checks": len(report["checks"]),
                      "failures": report["failures"]}, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
