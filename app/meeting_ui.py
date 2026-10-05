"""Small meeting-scoped participant and recovery dialogs."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.appearance import watch_theme
from app.participants import ParticipantRegistry


class ParticipantsDialog(QDialog):
    """Edit human participant labels and explicit segment-to-person bindings."""

    changed = pyqtSignal(dict)
    settings_changed = pyqtSignal(dict)

    def __init__(self, registry: ParticipantRegistry, rows: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本次会议参会者")
        self.resize(760, 560)
        self.registry = ParticipantRegistry(state=registry.to_dict())
        self.rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._row_counts: Counter[str] = Counter()
        for row in self.rows:
            decorated = self.registry.decorate(row)
            key = decorated.get("speaker_key")
            if key and decorated.get("participant_id"):
                self._row_counts[key] += 1

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "参会者名称由你指定。不同音源或重建分段的同号 speaker 默认分开；请确认后再关联或合并。"
        ))

        lists = QHBoxLayout()
        participant_box = QVBoxLayout()
        participant_box.addWidget(QLabel("参会者"))
        self.participant_list = QListWidget()
        self.participant_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.participant_list.currentRowChanged.connect(self._participant_selected)
        participant_box.addWidget(self.participant_list, 1)
        name_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("参会者名称")
        self.rename_button = QPushButton("保存名称")
        self.rename_button.clicked.connect(self.rename_selected)
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(self.rename_button)
        participant_box.addLayout(name_row)
        merge_row = QHBoxLayout()
        self.target_combo = QComboBox()
        self.merge_button = QPushButton("合并到所选参会者")
        self.merge_button.clicked.connect(self.merge_selected)
        merge_row.addWidget(self.target_combo, 1)
        merge_row.addWidget(self.merge_button)
        participant_box.addLayout(merge_row)
        lists.addLayout(participant_box, 1)

        binding_box = QVBoxLayout()
        binding_box.addWidget(QLabel("声音分段 / 绑定"))
        self.binding_list = QListWidget()
        self.binding_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        binding_box.addWidget(self.binding_list, 1)
        self.binding_list.currentRowChanged.connect(self._binding_selected)
        self.associate_button = QPushButton("将选中分段关联到所选参会者")
        self.associate_button.clicked.connect(self.associate_selected)
        binding_box.addWidget(self.associate_button)
        split_row = QHBoxLayout()
        self.split_name_edit = QLineEdit()
        self.split_name_edit.setPlaceholderText("拆分后参会者名称")
        self.split_button = QPushButton("将选中分段拆为新参会者")
        self.split_button.clicked.connect(self.split_selected)
        split_row.addWidget(self.split_name_edit, 1)
        split_row.addWidget(self.split_button)
        binding_box.addLayout(split_row)
        lists.addLayout(binding_box, 1)
        layout.addLayout(lists, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("原始 speaker 编号与字幕内容保持不变。")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.close_button = QPushButton("完成")
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self._refresh()
        watch_theme(self)

    def _refresh(self, *, select_pid=None, select_key=None):
        if select_pid is None and self.participant_list.currentItem():
            select_pid = self.participant_list.currentItem().data(Qt.ItemDataRole.UserRole)
        if select_key is None and self.binding_list.currentItem():
            select_key = self.binding_list.currentItem().data(Qt.ItemDataRole.UserRole)
        self.participant_list.clear()
        for pid, person in self.registry.participants.items():
            state = "已确认" if person.get("confirmed") else "待确认"
            item = QListWidgetItem(f"{person.get('name') or '未命名'} · {state}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.participant_list.addItem(item)
            if pid == select_pid:
                self.participant_list.setCurrentItem(item)
        self.binding_list.clear()
        for key, pid in self.registry.bindings.items():
            person = self.registry.participants.get(pid, {})
            source, _, speaker = key.partition("|")
            item = QListWidgetItem(
                f"{source} · speaker {speaker} · {person.get('name') or '未命名'} · "
                f"{self._row_counts.get(key, 0)} 条字幕"
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.binding_list.addItem(item)
            if key == select_key:
                self.binding_list.setCurrentItem(item)
        self._refresh_targets()
        self._participant_selected(self.participant_list.currentRow())

    def _selected_pid(self):
        item = self.participant_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_key(self):
        item = self.binding_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_keys(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.binding_list.selectedItems()]

    def _participant_selected(self, _row):
        pid = self._selected_pid()
        if pid in self.registry.participants:
            self.name_edit.setText(self.registry.participants[pid].get("name", ""))
        self._refresh_targets()
        self.associate_button.setEnabled(bool(pid and self._selected_key()))
        self.merge_button.setEnabled(bool(pid and self.target_combo.count()))

    def _binding_selected(self, _row):
        self.associate_button.setEnabled(bool(self._selected_pid() and self._selected_key()))

    def _refresh_targets(self):
        current = self.target_combo.currentData() if hasattr(self, "target_combo") else None
        source_pid = self._selected_pid() if hasattr(self, "participant_list") else None
        self.target_combo.clear()
        for pid, person in self.registry.participants.items():
            if pid != source_pid:
                self.target_combo.addItem(person.get("name") or "未命名", pid)
        index = self.target_combo.findData(current)
        if index >= 0:
            self.target_combo.setCurrentIndex(index)

    def select_participant(self, pid: str):
        for index in range(self.participant_list.count()):
            item = self.participant_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == pid:
                self.participant_list.setCurrentItem(item)
                return

    def select_binding(self, key: str):
        for index in range(self.binding_list.count()):
            item = self.binding_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.binding_list.setCurrentItem(item)
                return

    def _emit_changed(self):
        state = self.registry.to_dict()
        self.changed.emit(state)
        self.settings_changed.emit(state)

    def rename_selected(self):
        pid = self._selected_pid()
        try:
            self.registry.rename(pid, self.name_edit.text())
        except (ValueError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        self._refresh(select_pid=pid, select_key=self._selected_key())
        self.status_label.setText("名称已应用于本次会议的绑定分段。")
        self._emit_changed()

    def associate_selected(self):
        key, pid = self._selected_key(), self._selected_pid()
        try:
            self.registry.associate(key, pid)
        except (ValueError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        self._refresh(select_pid=pid, select_key=key)
        self.status_label.setText("所选声音分段已关联。")
        self._emit_changed()

    def merge_selected(self):
        source_pid, target_pid = self._selected_pid(), self.target_combo.currentData()
        try:
            self.registry.merge(source_pid, target_pid)
        except (ValueError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        self._refresh(select_pid=target_pid)
        self.status_label.setText("参会者已合并；相关声音分段现在指向同一会议内参会者。")
        self._emit_changed()

    def split_selected(self):
        keys = self._selected_keys()
        try:
            pid = self.registry.split(keys, self.split_name_edit.text())
        except (ValueError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        key = keys[0] if keys else None
        self._refresh(select_pid=pid, select_key=key)
        self.status_label.setText("所选声音分段已拆为新的会议内参会者。")
        self._emit_changed()


class RecoveryDialog(QDialog):
    """Choose a damaged/incomplete record to view or continue, never deleting it."""

    def __init__(self, items: list[tuple[str | Path, dict]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("恢复未正常结束的会议")
        self.resize(760, 420)
        self.items = [(str(path), doc if isinstance(doc, dict) else {}) for path, doc in items]
        self.selected_path: str | None = None
        self.mode: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("可查看已保存字幕，或从已有记录继续并保留原文件。选择关闭不会删除或改写记录。"))
        self.records_table = QTableWidget(len(self.items), 3)
        self.records_table.setHorizontalHeaderLabels(["会议记录", "字幕条数", "状态 / 最后保存"])
        self.records_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.records_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.records_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.records_table.horizontalHeader().setStretchLastSection(True)
        for index, (path, doc) in enumerate(self.items):
            rows = doc.get("rows", [])
            preview_count = len(rows) if isinstance(rows, list) else 0
            count = doc.get("row_count", preview_count)
            try:
                count = max(0, int(count))
            except (TypeError, ValueError):
                count = preview_count
            timestamp = self._last_saved(path, doc)
            self.records_table.setItem(index, 0, QTableWidgetItem(path))
            self.records_table.setItem(index, 1, QTableWidgetItem(str(count)))
            self.records_table.setItem(index, 2, QTableWidgetItem(f"未正常结束 · {timestamp}"))
        self.records_table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.records_table, 1)

        actions = QHBoxLayout()
        self.status_label = QLabel("恢复选择不会声称缺失或未落盘内容已经恢复。")
        self.status_label.setWordWrap(True)
        actions.addWidget(self.status_label, 1)
        self.view_button = QPushButton("查看")
        self.view_button.clicked.connect(lambda: self._choose("view"))
        self.continue_button = QPushButton("继续")
        self.continue_button.clicked.connect(lambda: self._choose("continue"))
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.view_button)
        actions.addWidget(self.continue_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self._update_buttons()
        watch_theme(self)

    @staticmethod
    def _last_saved(path: str, doc: dict) -> str:
        for key in ("last_saved_at", "saved_at", "updated_at", "modified_at", "created_at"):
            if doc.get(key):
                return str(doc[key])
        try:
            from datetime import datetime
            return datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="seconds")
        except (OSError, ValueError, OverflowError):
            return "最后保存时间未知"

    def _selected_index(self):
        indexes = self.records_table.selectionModel().selectedRows()
        return indexes[0].row() if indexes else None

    def _update_buttons(self):
        enabled = self._selected_index() is not None
        self.view_button.setEnabled(enabled)
        self.continue_button.setEnabled(enabled)

    def _choose(self, mode: str):
        index = self._selected_index()
        if index is None:
            return
        self.selected_path = self.items[index][0]
        self.mode = mode
        self.accept()

