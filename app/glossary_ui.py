"""Qt editor for glossary rules and named local project profiles."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from app.appearance import watch_theme
from app.dialogs import QFileDialog, QInputDialog, QMessageBox
from app.glossary import (FIELDS, FIELD_LABELS, MATCH_MODES, Glossary, apply_import,
                          export_rules, export_template, normalize_rule, preview_import)

GLOSSARY_DIR = Path(__file__).resolve().parents[1] / "data" / "glossaries"


class GlossaryDialog(QDialog):
    def __init__(self, settings: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("常用词库")
        self.resize(980, 560)
        self._initial_settings = deepcopy(settings or {})
        self._profiles: dict[str, dict[str, Any]] = {}
        self._undo_state: tuple[list[dict[str, Any]], bool] | None = None
        self._pending_preview: dict[str, Any] | None = None
        self._profile = str(self._initial_settings.get("glossary_profile") or "Default")
        self._enabled = bool(self._initial_settings.get("glossary_enabled", True))
        self._rules = []
        self._load_profiles()
        if self._profile not in self._profiles:
            self._profiles[self._profile] = {"enabled": self._enabled,
                                             "rules": deepcopy(self._initial_settings.get("glossary_rules", []))}
        self._enabled = bool(self._profiles[self._profile].get("enabled", True))
        self._rules = deepcopy(self._profiles[self._profile].get("rules", []))

        self.enabled_box = QCheckBox("对后续新字幕启用词库")
        self.enabled_box.setChecked(self._enabled)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(sorted(self._profiles, key=lambda name: (name != "Default", name.casefold())))
        self.profile_combo.setCurrentText(self._profile)
        self.profile_combo.currentTextChanged.connect(self.select_profile)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("项目词库"))
        profile_row.addWidget(self.profile_combo, 1)
        new_profile = QPushButton("新建词库")
        new_profile.clicked.connect(self._ask_new_profile)
        profile_row.addWidget(new_profile)

        self.table = QTableWidget(0, len(FIELDS))
        self.table.setHorizontalHeaderLabels([FIELD_LABELS[field] for field in FIELDS])
        self.table.horizontalHeader().setStretchLastSection(True)
        self._render_rules()
        edit_row = QHBoxLayout()
        for label, callback in (("新增词条", self._add_row), ("删除选中", self._delete_rows),
                                ("导入词库", self._ask_import), ("导出当前词库", self._ask_export),
                                ("导出空白模板", self._ask_template), ("撤销导入", self.undo_import)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            edit_row.addWidget(button)

        self.preview_input = QTableWidget(1, 2)
        self.preview_input.setHorizontalHeaderLabels(["测试文本", "语言"])
        self.preview_input.setItem(0, 0, QTableWidgetItem(""))
        self.preview_input.setItem(0, 1, QTableWidgetItem("en"))
        preview_button = QPushButton("预览纠错")
        preview_button.clicked.connect(self._show_preview)
        self.preview_label = QLabel("输入文本后可预览命中规则")
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_input, 1)
        preview_row.addWidget(preview_button)
        preview_row.addWidget(self.preview_label, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel |
                                   QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(profile_row)
        layout.addWidget(self.enabled_box)
        layout.addWidget(self.table, 1)
        layout.addLayout(edit_row)
        layout.addLayout(preview_row)
        layout.addWidget(buttons)
        watch_theme(self)

    def _load_profiles(self) -> None:
        path = GLOSSARY_DIR / "profiles.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if isinstance(saved, dict):
                self._profiles = {str(name): {"enabled": bool(value.get("enabled", True)),
                                              "rules": value.get("rules", [])}
                                  for name, value in saved.items() if isinstance(value, dict)}
        except (OSError, ValueError, AttributeError):
            self._profiles = {}

    def _persist_profiles(self) -> None:
        GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
        path = GLOSSARY_DIR / "profiles.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _save_active_to_profiles(self) -> None:
        self._profiles[self._profile] = {"enabled": self.enabled_box.isChecked(),
                                         "rules": self.rules()}
        self._persist_profiles()

    def _sync_from_widgets(self) -> None:
        self._enabled = self.enabled_box.isChecked()
        self._rules = self.rules()

    def _render_rules(self) -> None:
        self.table.setRowCount(len(self._rules))
        for row_index, raw in enumerate(self._rules):
            rule = normalize_rule(raw, row_index + 1)
            for column, field in enumerate(FIELDS):
                value = ("是" if rule[field] else "否") if field == "enabled" else str(rule[field])
                self.table.setItem(row_index, column, QTableWidgetItem(value))

    def rules(self) -> list[dict[str, Any]]:
        result = []
        for row in range(self.table.rowCount()):
            values = {}
            for column, field in enumerate(FIELDS):
                item = self.table.item(row, column)
                values[field] = item.text() if item else ""
            result.append(normalize_rule(values, row + 1))
        return result

    def set_rules(self, rules: list[dict[str, Any]]) -> None:
        checked = [normalize_rule(rule, index) for index, rule in enumerate(rules, 1)]
        Glossary(checked)
        self._rules = checked
        self._render_rules()
        self._save_active_to_profiles()

    def values(self) -> dict[str, Any]:
        self._sync_from_widgets()
        Glossary(self._rules, self._enabled)
        profiles = deepcopy(self._profiles)
        profiles[self._profile] = {"enabled": self._enabled, "rules": deepcopy(self._rules)}
        return {"glossary_enabled": self._enabled, "glossary_rules": deepcopy(self._rules),
                "glossary_profile": self._profile, "glossary_profiles": profiles}

    def add_profile(self, name: str) -> None:
        name = str(name).strip()
        if not name or name in self._profiles:
            raise ValueError("profile name must be non-empty and unique")
        self._save_active_to_profiles()
        self._profiles[name] = {"enabled": self.enabled_box.isChecked(), "rules": []}
        self._persist_profiles()
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    def select_profile(self, name: str) -> None:
        if not name or name == self._profile or name not in self._profiles:
            return
        self._save_active_to_profiles()
        self._undo_state = None
        self._profile = name
        profile = self._profiles[name]
        self._enabled = bool(profile.get("enabled", True))
        self._rules = deepcopy(profile.get("rules", []))
        self.enabled_box.setChecked(self._enabled)
        self._render_rules()

    def load_import(self, path: str | Path) -> dict[str, Any]:
        self._sync_from_widgets()
        self._pending_preview = preview_import(path, self._rules)
        return self._pending_preview

    def apply_import(self, mode: str = "merge") -> list[dict[str, Any]]:
        if self._pending_preview is None:
            raise ValueError("preview an import before applying it")
        self._sync_from_widgets()
        self._undo_state = (deepcopy(self._rules), self._enabled)
        self._rules = apply_import(self._rules, self._pending_preview, mode)
        self._pending_preview = None
        self._render_rules()
        self._save_active_to_profiles()
        return self._rules

    def undo_import(self) -> bool:
        if self._undo_state is None:
            return False
        self._rules, self._enabled = self._undo_state
        self._undo_state = None
        self._render_rules()
        self.enabled_box.setChecked(self._enabled)
        self._save_active_to_profiles()
        return True

    def accept(self) -> None:
        try:
            self._sync_from_widgets()
            Glossary(self._rules, self._enabled)
            self._save_active_to_profiles()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "词库无效", str(exc))
            return
        super().accept()

    def preview_text(self, text: str, language: str | None = None) -> dict[str, Any]:
        self._sync_from_widgets()
        return Glossary(self._rules, self._enabled).correct(text, language)

    def _add_row(self) -> None:
        self.table.insertRow(self.table.rowCount())
        defaults = {"enabled": "是", "language": "*", "original": "", "replacement": "",
                    "match_mode": "text", "target_language": "", "fixed_translation": "", "notes": ""}
        row = self.table.rowCount() - 1
        for column, field in enumerate(FIELDS):
            self.table.setItem(row, column, QTableWidgetItem(defaults[field]))

    def _delete_rows(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def _ask_new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "新建词库", "项目名称")
        if ok:
            try:
                self.add_profile(name)
            except ValueError as exc:
                QMessageBox.warning(self, "词库", str(exc))

    def _ask_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入词库", "", "Glossary (*.csv *.xlsx)")
        if not path:
            return
        try:
            report = self.load_import(path)
            message = (f"新增 {report['counts']['added']} 条；覆盖 {report['counts']['overwritten']} 条；"
                       f"跳过 {report['counts']['skipped']} 条。\n合并：覆盖冲突词条；替换：用导入内容替换当前词库。")
            choice = QMessageBox.question(self, "导入预览", message,
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                          QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Yes)
            if choice == QMessageBox.StandardButton.Yes:
                self.apply_import("merge")
            elif choice == QMessageBox.StandardButton.No:
                self.apply_import("replace")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _ask_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出当前词库", "glossary.csv", "CSV (*.csv);;Excel (*.xlsx)")
        if path:
            try:
                export_rules(path, self.rules())
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "导出失败", str(exc))

    def _ask_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出空白模板", "glossary-template.csv",
                                              "CSV (*.csv);;Excel (*.xlsx)")
        if path:
            try:
                export_template(path)
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "导出失败", str(exc))

    def _show_preview(self) -> None:
        text_item = self.preview_input.item(0, 0)
        language_item = self.preview_input.item(0, 1)
        result = self.preview_text(text_item.text() if text_item else "",
                                   language_item.text() if language_item else None)
        self.preview_label.setText(f"纠错结果：{result['corrected']}（命中 {len(result['hits'])} 条）")
