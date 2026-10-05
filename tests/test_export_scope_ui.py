import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.export_ui import ExportDialog


_APP = QApplication.instance() or QApplication([])


def test_result_values_keeps_visible_scope_and_normalizes_selected_format_suffix():
    dialog = ExportDialog(245, 310)
    try:
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("visible"))
        dialog.path_edit.setText("meeting.old")
        path, format_name, scope = dialog.result_values()
        assert path.endswith("meeting.txt")
        assert (format_name, scope) == ("txt", "visible")
        assert "每页 200 条" in dialog.scope_help.text()
    finally:
        dialog.close()


def test_text_export_all_scope_and_raw_json_force_full_meeting_with_clear_explanation():
    dialog = ExportDialog(0, 42)
    try:
        assert dialog.scope_combo.currentData() == "all"
        assert dialog.scope_combo.model().item(0).isEnabled() is False
        dialog.path_edit.setText("archive.txt")
        assert dialog.result_values()[2] == "all"

        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("verbose_json"))
        assert dialog.scope_combo.currentData() == "all"
        assert not dialog.scope_combo.isEnabled()
        assert "清屏前" in dialog.scope_help.text()
        path, format_name, scope = dialog.result_values()
        assert path.endswith("archive.verbose.json")
        assert (format_name, scope) == ("verbose_json", "all")
    finally:
        dialog.close()


def test_empty_meeting_disables_export_and_result_values_rejects_empty_range():
    dialog = ExportDialog(0, 0)
    try:
        dialog.path_edit.setText("empty.txt")
        assert not dialog.export_button.isEnabled()
        with pytest.raises(ValueError, match="没有可导出"):
            dialog.result_values()
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("native_json"))
        assert "没有可导出" in dialog.scope_help.text()
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.close()


def test_visible_empty_can_still_export_full_meeting_and_native_export_cannot_select_visible():
    dialog = ExportDialog(0, 3)
    try:
        dialog.path_edit.setText("meeting.json")
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("native_json"))
        assert dialog.scope_combo.currentData() == "all"
        assert dialog.result_values() == ("meeting.json", "native_json", "all")
    finally:
        dialog.close()


def test_cancel_and_declined_overwrite_leave_existing_file_untouched():
    with TemporaryDirectory() as temp:
        target = Path(temp) / "meeting.txt"
        target.write_text("synthetic content", encoding="utf-8")
        dialog = ExportDialog(1, 1)
        try:
            dialog.path_edit.setText(str(target))
            dialog.reject()
            assert dialog.result() == dialog.DialogCode.Rejected
            assert target.read_text(encoding="utf-8") == "synthetic content"
        finally:
            dialog.close()

        dialog = ExportDialog(1, 1)
        try:
            dialog.path_edit.setText(str(target))
            with patch("app.export_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as ask:
                dialog._accept_export()
            ask.assert_called_once()
            assert dialog.result() == 0
            assert target.read_text(encoding="utf-8") == "synthetic content"
        finally:
            dialog.close()


def test_existing_path_requires_an_explicit_yes_before_accepting():
    with TemporaryDirectory() as temp:
        target = Path(temp) / "meeting.txt"
        target.write_text("synthetic content", encoding="utf-8")
        dialog = ExportDialog(2, 2)
        try:
            dialog.path_edit.setText(str(target))
            with patch("app.export_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                dialog._accept_export()
            assert dialog.result() == dialog.DialogCode.Accepted
            assert target.read_text(encoding="utf-8") == "synthetic content"
        finally:
            dialog.close()
