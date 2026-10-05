"""Schema-driven editor for the less frequently used WhisperLiveKit options."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from app.interaction import attach_help

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _choice_items(choices: Any) -> list[tuple[str, Any]]:
    if isinstance(choices, dict):
        return [(str(label), value) for label, value in choices.items()]
    result = []
    for item in choices or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            result.append((str(item[0]), item[1]))
        else:
            result.append((str(item), item))
    return result


def _make_field(field: dict[str, Any], value: Any) -> QWidget:
    kind = str(field.get("type", "str"))
    choices = _choice_items(field.get("choices"))
    if choices:
        widget = QComboBox()
        if str(field.get("name")) in {"lan", "target_language"}:
            widget.setEditable(True)
            widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for label, item_value in choices:
            widget.addItem(label, item_value)
        found = widget.findData(value)
        if found < 0 and value is not None:
            widget.addItem(str(value), value)
            found = widget.count() - 1
        if found >= 0:
            widget.setCurrentIndex(found)
    elif kind == "bool":
        widget = QCheckBox()
        if field.get("nullable"):
            widget.setTristate(True)
            widget.setCheckState(Qt.CheckState.PartiallyChecked if value is None else (Qt.CheckState.Checked if value else Qt.CheckState.Unchecked))
        else:
            widget.setChecked(bool(value))
    elif kind in ("int", "float") and field.get("nullable"):
        widget = QLineEdit("" if value is None else str(value))
        widget.setPlaceholderText("留空表示自动 / 未设置")
        widget.setValidator(QIntValidator() if kind == "int" else QDoubleValidator())
    elif kind == "int":
        widget = QSpinBox()
        widget.setRange(-2_147_483_648, 2_147_483_647)
        widget.setValue(int(value if value is not None else field.get("default", 0)))
    elif kind == "float":
        widget = QDoubleSpinBox()
        widget.setRange(-1_000_000_000, 1_000_000_000)
        widget.setDecimals(4)
        widget.setValue(float(value if value is not None else field.get("default", 0.0)))
    else:
        widget = QLineEdit("" if value is None else str(value))
        if str(field.get("name")) == "api_token":
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        if field.get("nullable"):
            widget.setPlaceholderText("留空表示自动 / 未设置")
    attach_help(widget, str(field.get("name") or ""), str(field.get("help") or ""))
    return widget


class AdvancedConfigPanel(QWidget):
    """A searchable-by-group complete form built from the WLK field schema."""

    def __init__(self, schema: list[dict[str, Any]], values: dict[str, Any], parent=None):
        super().__init__(parent)
        self.schema = [dict(field) for field in schema]
        self.widgets: dict[str, QWidget] = {}
        self.field_rows: dict[str, tuple[QFormLayout, QWidget, str]] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索参数名、中文名称或说明")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("搜索原库高级参数")
        self.search_edit.textChanged.connect(self._apply_search)
        outer.addWidget(self.search_edit)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        groups: dict[str, QFormLayout] = {}
        boxes: dict[str, QGroupBox] = {}
        for field in self.schema:
            name = str(field["name"])
            group = str(field.get("group") or "其他")
            if group not in groups:
                box = QGroupBox(group)
                form = QFormLayout(box)
                form.setHorizontalSpacing(16)
                form.setVerticalSpacing(8)
                boxes[group] = box
                groups[group] = form
                content_layout.addWidget(box)
            value = values.get(name, field.get("default"))
            widget = _make_field(field, value)
            self.widgets[name] = widget
            label = str(field.get("label") or name)
            groups[group].addRow(label, widget)
            self.field_rows[name] = (groups[group], widget, f"{label} {name} {group} {field.get('help') or ''}")
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _apply_search(self, text: str) -> None:
        """Filter visible rows only; widgets and their values remain intact."""
        needle = str(text or "").strip().casefold()
        visible_groups: set[str] = set()
        for name, (form, widget, searchable) in self.field_rows.items():
            visible = not needle or needle in searchable.casefold()
            form.setRowVisible(widget, visible)
            if visible:
                box = form.parentWidget()
                if isinstance(box, QGroupBox):
                    visible_groups.add(box.title())
        for box in self.findChildren(QGroupBox):
            box.setVisible(not needle or box.title() in visible_groups)

    def replace_field(self, name: str, widget: QWidget, wrapper: QWidget | None = None) -> None:
        form, old, searchable = self.field_rows[name]
        row_widget = wrapper or widget
        form.replaceWidget(old,row_widget)
        self.widgets[name]=widget
        self.field_rows[name]=(form,row_widget,searchable)
        old.deleteLater()

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        nullable = {str(field["name"]): bool(field.get("nullable")) for field in self.schema}
        for name, widget in self.widgets.items():
            from app.language_picker import LanguagePicker
            if isinstance(widget, LanguagePicker):
                value = widget.currentData()
            elif isinstance(widget, QComboBox):
                value = widget.currentText().strip() if widget.isEditable() else widget.currentData()
            elif isinstance(widget, QCheckBox):
                if nullable.get(name) and widget.checkState() == Qt.CheckState.PartiallyChecked:
                    value = None
                else:
                    value = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                field_type = next((field.get("type") for field in self.schema if field.get("name") == name), "str")
                if nullable.get(name) and not text:
                    value = None
                elif field_type == "int":
                    value = int(text) if text else 0
                elif field_type == "float":
                    value = float(text) if text else 0.0
                else:
                    value = text
            result[name] = value
        return result

    def set_fields_enabled(self, enabled: bool, only: set[str] | None = None) -> None:
        """Enable every field or only a named editable subset."""
        for name, widget in self.widgets.items():
            widget.setEnabled(bool(enabled) if only is None else name in only)
