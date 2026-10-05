"""Small, explicit export dialog for transcript and native meeting data."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.appearance import watch_theme
from app.dialogs import QFileDialog, QMessageBox


_FORMATS = (
    ("纯文本（TXT）", "txt", ".txt"),
    ("字幕（SRT）", "srt", ".srt"),
    ("字幕（VTT）", "vtt", ".vtt"),
    ("原始会议数据（JSON）", "native_json", ".json"),
    ("详细识别数据（JSON）", "verbose_json", ".verbose.json"),
    ("说话人数据（JSON）", "diarized_json", ".diarized.json"),
)
_RAW_FORMATS = {"native_json", "verbose_json", "diarized_json"}
_SUFFIXES = tuple(sorted((suffix for _, _, suffix in _FORMATS), key=len, reverse=True))


class ExportDialog(QDialog):
    """Choose an export format, record scope, and destination path."""

    def __init__(self, visible_count: int, total_count: int, parent=None):
        super().__init__(parent)
        self.visible_count = min(max(0, int(visible_count)), max(0, int(total_count)))
        self.total_count = max(0, int(total_count))
        self.setWindowTitle("导出会议记录")
        self.setMinimumWidth(500)
        watch_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        heading = QLabel("导出会议记录")
        heading.setObjectName("title")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        self.format_combo = QComboBox()
        for label, format_name, _suffix in _FORMATS:
            self.format_combo.addItem(label, format_name)
        form.addRow("文件格式", self.format_combo)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem(f"本次显示范围（{self.visible_count} 条）", "visible")
        self.scope_combo.addItem(f"整场会议（{self.total_count} 条）", "all")
        visible_item = self.scope_combo.model().item(0)
        visible_item.setEnabled(self.visible_count > 0)
        all_item = self.scope_combo.model().item(1)
        all_item.setEnabled(self.total_count > 0)
        if self.visible_count == 0 and self.total_count > 0:
            self.scope_combo.setCurrentIndex(1)
        form.addRow("导出范围", self.scope_combo)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择导出文件位置")
        self.path_edit.setClearButtonEnabled(True)
        self.browse_button = QPushButton("浏览…")
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(self.browse_button)
        form.addRow("保存到", path_row)
        layout.addLayout(form)

        self.scope_help = QLabel()
        self.scope_help.setObjectName("muted")
        self.scope_help.setWordWrap(True)
        layout.addWidget(self.scope_help)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        self.export_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.export_button.setText("导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.format_combo.currentIndexChanged.connect(self._format_changed)
        self.scope_combo.currentIndexChanged.connect(self._update_state)
        self.path_edit.textChanged.connect(self._update_state)
        self.browse_button.clicked.connect(self._browse)
        self._format_changed()

    @staticmethod
    def _suffix_for(format_name: str) -> str:
        return next(suffix for _label, name, suffix in _FORMATS if name == format_name)

    @classmethod
    def _normalized_path(cls, value: str, format_name: str) -> str:
        path = Path(str(value).strip())
        if not path.name:
            return ""
        name = path.name
        stem = None
        folded = name.casefold()
        for suffix in _SUFFIXES:
            if folded.endswith(suffix):
                stem = name[:-len(suffix)]
                break
        if stem is None:
            stem = path.stem if path.suffix else name
        return str(path.with_name((stem or "会议记录") + cls._suffix_for(format_name)))

    def _format_changed(self, *_args) -> None:
        format_name = str(self.format_combo.currentData() or "txt")
        raw = format_name in _RAW_FORMATS
        if raw:
            self.scope_combo.setCurrentIndex(1)
            self.scope_combo.setEnabled(False)
        else:
            self.scope_combo.setEnabled(True)
        existing_path = self.path_edit.text().strip()
        if existing_path:
            self.path_edit.setText(self._normalized_path(existing_path, format_name))
        self._update_state()

    def _update_state(self, *_args) -> None:
        format_name = str(self.format_combo.currentData() or "txt")
        scope = str(self.scope_combo.currentData() or "")
        if self.total_count == 0:
            help_text = "本次会议还没有可导出的字幕。"
        elif format_name in _RAW_FORMATS:
            help_text = "原始 JSON 固定导出整场会议，保留各路原始数据；其中可能包含清屏前的内容。清屏只清除当前视图，不会删除会议资料。"
        elif scope == "visible":
            help_text = "导出当前会议视图中的全部字幕，包括未清屏的字幕；不受主窗口每页 200 条的显示限制。"
        else:
            help_text = "导出整场会议的字幕记录。"
        if scope == "visible" and self.visible_count == 0:
            help_text = "当前视图没有可导出的字幕；如需保留已清屏前的会议内容，请选择整场会议。"
        self.scope_help.setText(help_text)
        count = self.visible_count if scope == "visible" else self.total_count
        self.export_button.setEnabled(count > 0 and bool(self.path_edit.text().strip()))

    def _browse(self) -> None:
        format_name = str(self.format_combo.currentData() or "txt")
        suffix = self._suffix_for(format_name)
        filters = {
            "txt": "纯文本 (*.txt)",
            "srt": "SubRip 字幕 (*.srt)",
            "vtt": "WebVTT 字幕 (*.vtt)",
            "native_json": "原始会议数据 (*.json)",
            "verbose_json": "详细识别数据 (*.verbose.json)",
            "diarized_json": "说话人数据 (*.diarized.json)",
        }
        initial = self.path_edit.text().strip() or str(Path.cwd() / ("会议记录" + suffix))
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self, "选择导出位置", initial, filters[format_name]
        )
        if selected_path:
            self.path_edit.setText(self._normalized_path(selected_path, format_name))

    def result_values(self) -> tuple[str, str, str]:
        """Return normalized (path, format, scope) for the accepted choice."""
        format_name = str(self.format_combo.currentData() or "txt")
        scope = "all" if format_name in _RAW_FORMATS else str(self.scope_combo.currentData() or "")
        count = self.visible_count if scope == "visible" else self.total_count
        path = self._normalized_path(self.path_edit.text(), format_name)
        if count <= 0:
            raise ValueError("没有可导出的字幕范围。")
        if not path:
            raise ValueError("请选择导出文件位置。")
        return path, format_name, scope

    def _accept_export(self) -> None:
        try:
            path, _format_name, _scope = self.result_values()
        except ValueError as exc:
            self.scope_help.setText(str(exc))
            return
        self.path_edit.setText(path)
        if Path(path).exists():
            answer = QMessageBox.question(
                self,
                "确认覆盖文件",
                f"文件已存在：\n{path}\n\n要替换这个文件吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()
