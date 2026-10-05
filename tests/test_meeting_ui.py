import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.meeting_ui import ParticipantsDialog, RecoveryDialog
from app.participants import ParticipantRegistry


def make_row(namespace, speaker, source="system", text="字幕"):
    return {"id": namespace + ":row", "start": 4, "source": text, "speaker": speaker,
            "audio_source": source, "speaker_namespace": namespace,
            "native": {"speaker": speaker, "text": text}}


class MeetingDialogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_participants_rename_associate_merge_and_split_are_meeting_scoped(self):
        registry = ParticipantRegistry("meeting-a")
        rows = [make_row("sys:g0:e0", 1), make_row("sys:g1:e0", 1),
                make_row("mic:g0:e0", 1, "mic")]
        dialog = ParticipantsDialog(registry, rows)
        self.addCleanup(dialog.close)
        changes = []
        dialog.changed.connect(changes.append)

        original_ids = {ParticipantRegistry.key(row): dialog.registry.bindings[ParticipantRegistry.key(row)] for row in rows}
        first_pid = original_ids["sys:g0:e0|1"]
        second_pid = original_ids["sys:g1:e0|1"]
        mic_pid = original_ids["mic:g0:e0|1"]
        dialog.select_participant(first_pid)
        dialog.name_edit.setText("林工")
        dialog.rename_button.click()
        self.assertEqual(dialog.registry.participants[first_pid]["name"], "林工")

        dialog.select_binding("sys:g1:e0|1")
        dialog.select_participant(first_pid)
        dialog.associate_button.click()
        self.assertEqual(dialog.registry.bindings["sys:g1:e0|1"], first_pid)

        dialog.select_participant(mic_pid)
        dialog.target_combo.setCurrentIndex(dialog.target_combo.findData(first_pid))
        dialog.merge_button.click()
        self.assertNotIn(mic_pid, dialog.registry.participants)
        self.assertEqual(dialog.registry.bindings["mic:g0:e0|1"], first_pid)

        dialog.select_binding("sys:g1:e0|1")
        dialog.split_name_edit.setText("独立分段")
        dialog.split_button.click()
        split_pid = dialog.registry.bindings["sys:g1:e0|1"]
        self.assertNotEqual(split_pid, first_pid)
        self.assertEqual(dialog.registry.participants[split_pid]["name"], "独立分段")
        self.assertEqual([row["native"] for row in dialog.rows], [row["native"] for row in rows])
        self.assertTrue(changes)
        self.assertEqual(changes[-1], dialog.registry.to_dict())

    def test_participant_dialog_starts_from_a_copy_and_exposes_serializable_registry(self):
        registry = ParticipantRegistry("meeting-copy")
        row = make_row("system:g0:e0", 2)
        dialog = ParticipantsDialog(registry, [row])
        self.addCleanup(dialog.close)
        pid = dialog.registry.bindings[ParticipantRegistry.key(row)]
        dialog.select_participant(pid)
        dialog.name_edit.setText("王工")
        dialog.rename_button.click()
        self.assertEqual(registry.participants, {})
        self.assertEqual(dialog.registry.to_dict()["participants"][pid]["name"], "王工")

    def test_recovery_dialog_shows_incomplete_record_summary_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "meeting.json"
            record.write_text("kept", encoding="utf-8")
            dialog = RecoveryDialog([(record, {"rows": [{"id": "1"}, {"id": "2"}], "row_count": 250,
                                      "last_saved_at": "2026-10-03T10:30:00"})])
            self.addCleanup(dialog.close)
            self.assertEqual(dialog.records_table.rowCount(), 1)
            self.assertEqual(dialog.records_table.item(0, 1).text(), "250")
            self.assertIn("未正常结束", dialog.records_table.item(0, 2).text())
            dialog.records_table.selectRow(0)
            dialog.continue_button.click()
            self.assertEqual(dialog.mode, "continue")
            self.assertEqual(dialog.selected_path, str(record))
            self.assertEqual(record.read_text(encoding="utf-8"), "kept")

    def test_recovery_view_sets_view_mode_and_unknown_save_time_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "recover.json"
            dialog = RecoveryDialog([(record, {"rows": []})])
            self.addCleanup(dialog.close)
            self.assertIn("未知", dialog.records_table.item(0, 2).text())
            dialog.records_table.selectRow(0)
            dialog.view_button.click()
            self.assertEqual(dialog.mode, "view")
            self.assertEqual(dialog.selected_path, str(record))

    def test_recovery_close_leaves_selection_empty_and_file_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "recover.json"
            record.write_text(json.dumps({"rows": [1]}), encoding="utf-8")
            dialog = RecoveryDialog([(record, {"rows": [1]})])
            self.addCleanup(dialog.close)
            dialog.close_button.click()
            self.assertIsNone(dialog.selected_path)
            self.assertIsNone(dialog.mode)
            self.assertTrue(record.exists())


if __name__ == "__main__":
    unittest.main()
