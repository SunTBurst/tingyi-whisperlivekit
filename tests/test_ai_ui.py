import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.ai_ui import AIModelDialog


class AIModelDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self, rows=None, record_path=None, settings=None):
        dialog = AIModelDialog(settings or {}, lambda: rows or [], lambda: record_path)
        self.addCleanup(dialog.close)
        return dialog

    def test_values_keep_llm_and_optional_translation_settings_separate(self):
        dialog = self.make_dialog(settings={"llm_url": "http://127.0.0.1:1234/v1", "llm_model": "qwen"})
        dialog.llm_token.setText("local-key")
        dialog.timeout_spin.setValue(45)
        dialog.context_spin.setValue(12000)
        dialog.translation_provider.setCurrentIndex(dialog.translation_provider.findData("lmstudio"))
        dialog.fallback_check.setChecked(True)
        values = dialog.values()
        self.assertEqual(values["llm_model"], "qwen")
        self.assertEqual(values["llm_api_token"], "local-key")
        self.assertEqual(values["llm_timeout"], 45)
        self.assertEqual(values["llm_context_chars"], 12000)
        self.assertEqual(values["translation_provider"], "lmstudio")
        self.assertTrue(values["llm_fallback"])

    def test_question_context_carries_row_id_time_and_participant(self):
        rows = [
            {"id": "row-17", "start": 12.5, "source": "决定先验证接口", "participant_name": "林工"},
            {"id": "row-18", "start": 33, "source": "下次会议复核", "speaker_name": "赵工"},
        ]
        dialog = self.make_dialog(rows)
        context = dialog._context_for_question("本次会议")
        self.assertIn("[row-17]", context)
        self.assertIn("00:00:12", context)
        self.assertIn("林工", context)
        self.assertIn("[row-18]", context)

    def test_time_range_selects_rows_without_losing_citation_context(self):
        rows = [
            {"id": "early", "start": 5, "source": "早段内容"},
            {"id": "inside", "start": 65, "source": "范围内内容"},
            {"id": "late", "start": 3600, "source": "晚段内容"},
        ]
        dialog = self.make_dialog(rows)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("time"))
        dialog.range_start.setText("00:00:30")
        dialog.range_end.setText("00:02:00")
        selected = dialog._selected_rows()
        self.assertEqual([row["id"] for row in selected], ["inside"])

    def test_saved_meeting_context_loads_rows_from_record_json(self):
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "meeting.json"
            record.write_text(json.dumps({"rows": [{"id": "saved-1", "start": 7, "source": "存档字幕"}]}, ensure_ascii=False), encoding="utf-8")
            dialog = self.make_dialog([], record)
            dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("saved"))
            self.assertEqual(dialog._selected_rows()[0]["id"], "saved-1")

    def test_oversized_question_context_is_rejected_instead_of_truncated(self):
        rows = [{"id": "long", "start": 1, "source": "会议事实" * 500}]
        dialog = self.make_dialog(rows, settings={"llm_context_chars": 1000})
        with self.assertRaisesRegex(ValueError, "缩小时间范围"):
            dialog._context_for_question("当前会议")

    def test_citation_review_flags_missing_or_unknown_ids_without_claiming_facts_verified(self):
        rows = [{"id": "known-1", "start": 1, "source": "内容"}]
        missing, missing_state = AIModelDialog._citation_review("AI给出结论但没有引用。", rows, "question")
        self.assertEqual(missing_state, "missing")
        self.assertIn("未检测到", missing)
        unknown, unknown_state = AIModelDialog._citation_review("结论 [made-up-9]", rows, "summary")
        self.assertEqual(unknown_state, "unknown_and_incomplete")
        self.assertIn("made-up-9", unknown)
        matched, matched_state = AIModelDialog._citation_review("结论 [known-1]", rows, "question")
        self.assertEqual(matched_state, "matched")
        self.assertIn("仍需人工核对", matched)

    def test_summary_reports_uncited_source_rows_for_manual_coverage_review(self):
        rows = [{"id": "segment-a"}, {"id": "segment-b"}, {"id": "segment-c"}]
        note, state = AIModelDialog._citation_review("摘要 [segment-a] [segment-c]", rows, "summary")
        self.assertEqual(state, "incomplete_coverage")
        self.assertIn("摘要未引用的片段，请核对", note)
        self.assertIn("segment-b", note)

    def test_saved_summary_artifact_records_missing_source_ids_for_review(self):
        rows = [{"id": "segment-a", "start": 1}, {"id": "segment-b", "start": 2}]
        dialog = self.make_dialog(rows)
        dialog.model_combo.addItem("fake", "fake")
        with tempfile.TemporaryDirectory() as temp, patch("app.ai_ui.ROOT", Path(temp)):
            artifact = dialog._save_ai_artifact("summary", "摘要", "结论 [segment-a]", rows)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(payload["citation_review"], "incomplete_coverage")
        self.assertEqual(payload["uncited_source_ids"], ["segment-b"])

    def test_async_question_keeps_ui_responsive_and_persists_separate_ai_result(self):
        entered = threading.Event()
        release = threading.Event()
        rows = [{"id": "q-1", "start": 10, "source": "周五前发送报告", "speaker_name": "王工"}]
        dialog = self.make_dialog(rows, settings={"llm_api_token": "synthetic-token"})
        dialog.model_combo.addItem("fake", "fake")
        dialog.question_edit.setPlainText("有什么待办？")
        dialog.client_factory = lambda config: object()

        def fake_chat(_client, _messages, _cancel, on_piece):
            entered.set()
            release.wait(2)
            on_piece("周五前发送报告 [q-1]")
            return "周五前发送报告 [q-1]"

        with tempfile.TemporaryDirectory() as temp, patch("app.ai_ui.ROOT", Path(temp)), patch.object(
            dialog, "_run_chat", side_effect=fake_chat
        ):
            dialog.ask_button.click()
            self.assertTrue(entered.wait(1))
            timer_fired = []
            from PyQt6.QtCore import QTimer
            timer = QTimer(dialog)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: timer_fired.append(True))
            timer.start(10)
            deadline = time.monotonic() + 0.5
            while not timer_fired and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertTrue(timer_fired, "Qt event loop was blocked by the HTTP worker")
            release.set()
            self.wait_until(lambda: "[q-1]" in dialog.result_view.toPlainText())
            saved = list((Path(temp) / "records" / "ai").glob("*.json"))
            self.assertEqual(len(saved), 1)
            payload = json.loads(saved[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "question")
            self.assertIn("[q-1]", payload["answer"])
            self.assertTrue(payload["ai_generated"])
            self.assertTrue(payload["review_required"])
            self.assertNotIn("llm_api_token", payload)
            self.assertNotIn("synthetic-token", saved[0].read_text(encoding="utf-8"))

    def test_close_cancels_inflight_task_without_waiting_for_http_timeout(self):
        entered = threading.Event()
        rows = [{"id": "q", "start": 1, "source": "内容"}]
        dialog = self.make_dialog(rows)
        dialog.model_combo.addItem("fake", "fake")
        dialog.question_edit.setPlainText("问题")
        dialog.client_factory = lambda config: object()

        def blocking_chat(_client, _messages, cancel, _on_piece):
            entered.set()
            cancel.wait(1)
            return ""

        with patch.object(dialog, "_run_chat", side_effect=blocking_chat):
            dialog.ask_button.click()
            self.assertTrue(entered.wait(1))
            worker = dialog._worker_thread
            started = time.monotonic()
            dialog.close()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(dialog._cancel_event.is_set())
            worker.join(timeout=0.5)
            self.assertFalse(worker.is_alive(), "cancelled dialog worker should exit promptly")

    def wait_until(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertTrue(condition(), "timed out waiting for Qt worker completion")


if __name__ == "__main__":
    unittest.main()
