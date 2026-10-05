import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.ui import CaptionCard, MainWindow, SettingsDialog


class UiModelsV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_language_picker_searches_aliases_and_commits_only_legal_choice(self):
        self.assertIsNotNone(importlib.util.find_spec("app.language_picker"), "searchable language picker module should exist")
        from app.language_picker import LanguagePicker
        picker = LanguagePicker([("中文", "zh"), ("英语", "en"), ("阿拉伯语", "ar")], current="en")
        self.assertEqual(picker.currentData(), "en")
        picker.search_edit.setText("阿拉伯")
        self.assertEqual(picker.currentData(), "en")
        self.assertTrue(any(picker.proxy_model.data(picker.proxy_model.index(row, 0), picker.code_role) == "ar"
                            for row in range(picker.proxy_model.rowCount())))
        picker.search_edit.setText("nothing matches")
        self.assertEqual(picker.currentData(), "en")
        self.assertTrue(picker.status_label.text())
        picker.commit_code("ar")
        self.assertEqual(picker.currentData(), "ar")
        picker.commit_code("en")
        picker.setFocus()
        picker.search_edit.selectAll()
        QTest.keyClicks(picker.search_edit, "arabic")
        self.assertEqual(picker.currentData(), "en")
        QTest.keyClick(picker.search_edit, Qt.Key.Key_Escape)
        self.assertEqual(picker.currentData(), "en")
        self.assertEqual(picker.search_edit.text(), "英语")
        self.assertIn("English", picker.itemText(picker.findData("en")))
        picker.search_edit.setText("arabic")
        QTest.keyClick(picker.search_edit, Qt.Key.Key_Return)
        self.assertEqual(picker.currentData(), "ar")

    def test_caption_deltas_preserve_full_rows_and_render_bounded_cards(self):
        window = MainWindow(settings={"source_language": "auto", "target_language": "zh", "asr_model": "small"}, devices={})
        try:
            rows = [{"id": f"row-{index}", "source": f"line {index}", "start": index, "end": index + 1} for index in range(230)]
            window.apply_caption_changes(rows, [], draft="draft")
            self.assertEqual(len(window.caption_rows), 230)
            self.assertLessEqual(len(window.caption_cards), 200)
            self.assertEqual(window.caption_rows["row-0"]["source"], "line 0")
            window.apply_caption_changes([dict(rows[0], source="edited")], ["row-1"], draft="")
            self.assertEqual(window.caption_rows["row-0"]["source"], "edited")
            self.assertNotIn("row-1", window.caption_rows)
            self.assertEqual(window.caption_list.count(), len(window.caption_cards))
        finally:
            window.close()

    def test_caption_rows_are_ordered_by_start_then_id_for_deltas_and_snapshots(self):
        window = MainWindow(settings={"source_language": "auto", "target_language": "zh", "asr_model": "small"}, devices={})
        try:
            late = {"id": "z", "source": "late", "start": 2}
            early_z = {"id": "z-early", "source": "early z", "start": 1}
            early_a = {"id": "a-early", "source": "early a", "start": 1}
            window.apply_caption_changes([late, early_z, early_a], [])
            self.assertEqual(window.caption_order, ["a-early", "z-early", "z"])
            self.assertEqual(window.history_list.item(0).data(Qt.ItemDataRole.UserRole), "a-early")
            window.copy_transcript()
            self.assertTrue(self.app.clipboard().text().startswith("early a"))
            window.apply_caption_changes([dict(late, start=0.5)], [])
            self.assertEqual(window.caption_order, ["z", "a-early", "z-early"])
            window.update_caption([late, early_z, early_a])
            self.assertEqual(window.caption_order, ["a-early", "z-early", "z"])
        finally:
            window.close()

    def test_caption_card_displays_translation_state_without_mutating_translation(self):
        row = {"id": "r", "source": "corrected", "translation": "old wording", "translation_pending": True,
               "translation_stale": True, "translation_error": "service timeout"}
        card = CaptionCard(row, 24, compact=True)
        self.assertIn("\u7ffb\u8bd1\u4e2d", card.translation_status_label.text())
        self.assertIn("\u65e7\u8bd1\u6587\u5f85\u66f4\u65b0", card.translation_status_label.text())
        self.assertIn("\u672a\u5b8c\u6210", card.translation_status_label.text())
        self.assertEqual(card.row["translation"], "old wording")
        self.assertEqual(card.translation_text.text(), "old wording")
        self.assertFalse(card.translation_status_label.isHidden())

    def test_caption_card_exposes_source_provenance_and_marks_original_display(self):
        row = {"id": "r", "source": "wrong", "source_original": "wrong", "source_corrected": "right",
               "glossary_revision": "g-7", "display_source_mode": "original"}
        card = CaptionCard(row, 24)
        self.assertEqual(card.source_label.text(), "\u539f\u59cb\u542c\u5199")
        self.assertIn("wrong", card.source_text.toolTip())
        self.assertIn("right", card.source_text.toolTip())
        self.assertIn("g-7", card.source_text.toolTip())

    def test_pending_participant_is_not_presented_as_confirmed_speaker(self):
        row = {"id": "r", "source": "hello", "speaker": 1, "speaker_name": "Wrong Person", "participant_pending": True}
        card = CaptionCard(row, 24)
        self.assertIn("\u5f85\u786e\u8ba4", card.meta_label.text())
        self.assertNotIn("Wrong Person", card.meta_label.text())
        self.assertFalse(card.rename_button.isHidden())
        self.assertEqual(card.rename_button.text(), "\u6807\u6ce8\u59d3\u540d")
        self.assertIn("1", card.meta_label.text())

    def test_pending_participant_id_is_distinct_and_rename_keeps_object_identity(self):
        calls = []
        row = {"id": "r", "source": "hello", "speaker": 1, "participant_id": "p-ab123", "participant_pending": True}
        card = CaptionCard(row, 24, rename_requested=lambda identity, name: calls.append((identity, name)))
        self.assertIn("p-ab123", card.meta_label.text())
        with patch("app.ui.QInputDialog.getText", return_value=("Alice", True)):
            card._rename_speaker()
        self.assertEqual(calls, [("p-ab123", "Alice")])

    def test_unknown_pending_speaker_numbers_do_not_bind_or_offer_rename(self):
        for speaker in (None, 0, -1, -2):
            with self.subTest(speaker=speaker):
                row = {"id": "r", "source": "hello", "speaker": speaker, "speaker_name": "Wrong Person",
                       "participant_id": None, "participant_pending": True}
                card = CaptionCard(row, 24)
                self.assertNotIn("Wrong Person", card.meta_label.text())
                self.assertEqual(card.meta_label.text(), "\u5f85\u786e\u8ba4\u58f0\u7ec4")
                self.assertTrue(card.rename_button.isHidden())

    def test_caption_card_renames_string_participant_ids(self):
        calls = []
        row = {"id": "r", "source": "hi", "participant_id": "participant-alpha", "speaker": 1}
        card = CaptionCard(row, 24, rename_requested=lambda identity, name: calls.append((identity, name)))
        with patch("app.ui.QInputDialog.getText", return_value=("Alice", True)):
            card._rename_speaker()
        self.assertEqual(calls, [("participant-alpha", "Alice")])

    def test_subtitle_window_keeps_main_settings_and_pause_accessible(self):
        window = MainWindow(settings={"source_language": "auto", "target_language": "zh", "asr_model": "small"}, devices={})
        try:
            window.set_running(True)
            window.show()
            self.app.processEvents()
            window.toggle_compact_mode()
            self.app.processEvents()
            self.assertTrue(window.source_language.isVisible())
            self.assertTrue(window.settings_button.isVisible())
            self.assertTrue(window.pause_button.isVisible())
            self.assertTrue(window.subtitle_overlay.isVisible())
        finally:
            window.close()

    def test_external_registry_records_directory_without_copying_files(self):
        self.assertIsNotNone(importlib.util.find_spec("app.model_registry"), "external model registry module should exist")
        from app.model_registry import register_external_model, read_model_registry
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir = root / "fake-existing-model"
            model_dir.mkdir()
            (model_dir / "config.json").write_text("{}", encoding="utf-8")
            (model_dir / "model.bin").write_bytes(b"fake")
            registry = root / "data" / "model_registry.json"
            record = register_external_model(model_dir, name="Demo", kind="asr", backend="faster-whisper", registry_path=registry)
            self.assertEqual(record["path"], str(model_dir.resolve()))
            self.assertTrue((model_dir / "model.bin").is_file())
            self.assertEqual(read_model_registry(registry)[0]["name"], "Demo")
            self.assertEqual(json.loads(registry.read_text(encoding="utf-8"))[0]["path"], str(model_dir.resolve()))

    def test_settings_language_fields_are_searchable_and_keep_committed_codes(self):
        from app.language_picker import LanguagePicker
        dialog = SettingsDialog({"source_language": "en", "target_language": "zh", "mic_language": "ar"}, {"input": [], "output": []})
        self.addCleanup(dialog.close)
        self.assertIsInstance(dialog.source_language_combo, LanguagePicker)
        self.assertIsInstance(dialog.target_language_combo, LanguagePicker)
        self.assertIsInstance(dialog.mic_language, LanguagePicker)
        dialog.source_language_combo.search_edit.setText("invalid language")
        self.assertEqual(dialog.source_language_combo.currentData(), "en")
        self.assertEqual(dialog.values()["source_language"], "en")

    def test_model_inventory_includes_registered_external_fake_directory(self):
        from app import model_manager, model_registry
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_models = root / "models"
            fake_models.mkdir()
            fake_dir = root / "external-model"
            fake_dir.mkdir()
            (fake_dir / "config.json").write_text("{}", encoding="utf-8")
            (fake_dir / "model.bin").write_bytes(b"fake")
            registry_path = root / "data" / "model_registry.json"
            model_registry.register_external_model(fake_dir, name="External Whisper", kind="asr",
                backend="faster-whisper", registry_path=registry_path)
            with patch.object(model_manager, "MODEL_ROOT", fake_models), patch.object(model_registry, "REGISTRY_PATH", registry_path):
                model = next(row for row in model_manager.installed_models() if row["name"] == "External Whisper")
            self.assertEqual(model["source"], "external")
            self.assertTrue(model["installed"])
            self.assertTrue(model["validated"])
            self.assertEqual(model["local_path"], str(fake_dir.resolve()))


if __name__ == "__main__":
    unittest.main()
