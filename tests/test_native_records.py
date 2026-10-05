import json
import tempfile
import unittest
from pathlib import Path

from app.records import CaptionStore, Journal, export_rows, read_record


class NativeRecordTests(unittest.TestCase):
    def test_speaker_revision_keeps_one_stable_row_and_translation(self):
        store = CaptionStore()
        store.ingest_snapshot({"type": "snapshot", "lines": [
            {"start": "0:00:01.00", "end": "0:00:02.00", "text": "Hello", "speaker": 0},
        ]})
        row_id = store.rows()[0]["id"]
        store.apply_translation(row_id, "Hello", "你好")
        changed = store.ingest_snapshot({"type": "diff", "n_lines": 1, "new_lines": [
            {"start": "0:00:01.00", "end": "0:00:02.00", "text": "Hello", "speaker": 1},
        ]})
        self.assertEqual(len(store.rows()), 1)
        self.assertEqual(store.rows()[0]["id"], row_id)
        self.assertEqual(store.rows()[0]["translation"], "你好")
        self.assertEqual(store.rows()[0]["speaker"], 1)
        self.assertEqual(len(changed), 1)

    def test_snapshot_preserves_native_fields_and_applies_timed_translation(self):
        store = CaptionStore()
        line = {
            "start": "0:00:01.20", "end": "0:00:02.30", "text": "Good morning",
            "speaker": 2, "detected_language": "en", "translation": {"text": "早上好"},
            "words": [{"word": "Good", "start": 1.2, "end": 1.6}, {"word": "morning", "start": 1.6, "end": 2.3}],
        }
        store.ingest_snapshot({"type": "snapshot", "status": "running", "lines": [line],
                               "buffer_transcription": "next", "buffer_translation": "下句"})
        row = store.rows()[0]
        self.assertEqual((row["start"], row["end"]), (1.2, 2.3))
        self.assertEqual(row["translation"], "早上好")
        self.assertEqual(row["native"], line)
        self.assertEqual(row["speaker"], 2)
        self.assertEqual(store.snapshot["buffer_transcription"], "next")
        self.assertEqual(store.snapshot["buffer_translation"], "下句")

    def test_diff_protocol_replaces_changed_suffix_and_prunes_front(self):
        store = CaptionStore()
        store.ingest_snapshot({"type": "snapshot", "lines": [
            {"start": 1, "end": 2, "text": "one", "speaker": 1},
            {"start": 2, "end": 3, "text": "two", "speaker": 1},
        ]})
        store.ingest_snapshot({"type": "diff", "lines_pruned": 1, "n_lines": 2,
                              "new_lines": [{"start": 2, "end": 3, "text": "two revised", "speaker": 2},
                                            {"start": 3, "end": 4, "text": "three", "speaker": -1}],
                              "buffer_diarization": "speaker pending"})
        rows = store.rows()
        self.assertEqual([r["source"] for r in rows], ["one", "two revised", "three"])
        self.assertEqual(store.snapshot["buffer_diarization"], "speaker pending")

    def test_speaker_mapping_exports_vtt_verbose_native_and_journal_roundtrip(self):
        store = CaptionStore()
        native = {"start": "0:00:00.50", "end": "0:00:01.50", "text": "Hi",
                  "speaker": 3, "words": [{"word": "Hi", "start": 0.5, "end": 1.5}]}
        store.ingest_snapshot({"type": "snapshot", "lines": [native]})
        store.rename_speaker(3, "Alice")
        row = store.rows()[0]
        self.assertEqual(row["speaker_name"], "Alice")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for fmt in ("txt", "srt", "vtt", "verbose_json", "native_json"):
                export_rows([row], folder / f"out.{fmt}", fmt)
            self.assertIn("Alice: Hi", (folder / "out.txt").read_text(encoding="utf-8"))
            self.assertIn("Alice: Hi", (folder / "out.srt").read_text(encoding="utf-8"))
            self.assertIn("Alice: Hi", (folder / "out.vtt").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((folder / "out.verbose_json").read_text(encoding="utf-8"))["words"][0]["start"], 0.5)
            original = json.loads((folder / "out.native_json").read_text(encoding="utf-8"))
            self.assertEqual(original["lines"][0], native)
            journal = Journal(folder / "records", {})
            journal.save([row], native_snapshot=store.snapshot)
            loaded = read_record(journal.path)
            self.assertEqual(loaded["rows"][0]["speaker_name"], "Alice")
            self.assertIn("native_snapshot", loaded)

    def test_unknown_speakers_and_silence_are_not_labeled_or_saved(self):
        store = CaptionStore()
        store.ingest_snapshot({"type": "snapshot", "lines": [
            {"start": 0, "end": 1, "text": "pending", "speaker": -1},
            {"start": 1, "end": 2, "text": "", "speaker": -2},
        ]})
        self.assertEqual(len(store.rows()), 1)
        self.assertIsNone(store.rows()[0]["speaker_name"])

    def test_legacy_records_remain_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.json"
            path.write_text(json.dumps({"created_at": "old", "rows": [{"id": "a", "source": "x"}]}), encoding="utf-8")
            self.assertEqual(read_record(path)["rows"][0]["source"], "x")


if __name__ == "__main__":
    unittest.main()
def test_diff_counts_silence_and_keeps_archived_history_when_server_prunes():
    from app.records import CaptionStore
    store=CaptionStore()
    store.ingest_snapshot({'type':'snapshot','lines':[
        {'speaker':-2,'start':0,'end':1,'text':''},
        {'speaker':1,'start':1,'end':2,'text':'A'},
        {'speaker':-2,'start':2,'end':3,'text':''},
        {'speaker':2,'start':3,'end':4,'text':'B'}]})
    store.ingest_snapshot({'type':'diff','n_lines':4,'new_lines':[
        {'speaker':2,'start':3,'end':4,'text':'B','translation':'乙'}]})
    assert [(r['source'],r['translation']) for r in store.rows()]==[('A',''),('B','乙')]
    store.ingest_snapshot({'type':'diff','lines_pruned':3,'n_lines':1})
    assert [r['source'] for r in store.rows()]==['A','B']
    assert len(store.snapshot['lines'])==1
