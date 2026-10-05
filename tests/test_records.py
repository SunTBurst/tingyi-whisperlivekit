import importlib
import tempfile
import unittest
from pathlib import Path


class RecordsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.mod = importlib.import_module('app.records')
        except ModuleNotFoundError:
            self.fail('缺少真实字幕记录实现 app.records')

    def test_changed_source_rejects_stale_translation(self):
        store = self.mod.CaptionStore()
        store.ingest([{'start': 1.25, 'end': 2, 'text': 'Hello', 'speaker': 1, 'detected_language': 'en'}])
        row_id = store.rows()[0]['id']
        store.ingest([{'start': 1.25, 'end': 3, 'text': 'Hello world.', 'speaker': 1, 'detected_language': 'en'}])
        self.assertFalse(store.apply_translation(row_id, 'Hello', '你好'))
        self.assertTrue(store.apply_translation(row_id, 'Hello world.', '你好，世界。'))
        self.assertEqual(store.rows()[0]['translation'], '你好，世界。')
        self.assertEqual(len(store.rows()), 1)

    def test_silence_and_draft_never_become_saved_captions(self):
        store = self.mod.CaptionStore()
        store.ingest([{'start': 0, 'end': 1, 'text': '', 'speaker': -2}])
        self.assertEqual(store.rows(), [])

    def test_srt_uses_real_millisecond_times_and_bilingual_lines(self):
        rows = [{'id':'a', 'source':'Good morning.', 'translation':'早上好。', 'start':1.234, 'end':3.456, 'language':'en'}]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '会议.srt'
            self.mod.export_rows(rows, target, 'srt')
            self.assertEqual(target.read_text(encoding='utf-8'), '1\n00:00:01,234 --> 00:00:03,456\n纠错后文本：Good morning.\n早上好。\n\n')

    def test_record_reload_restores_latest_translation(self):
        rows = [{'id':'a','source':'Test','translation':'测试','start':0,'end':2,'language':'en'}]
        with tempfile.TemporaryDirectory() as folder:
            journal = self.mod.Journal(Path(folder), {'target_language':'zh'})
            journal.save(rows)
            self.assertEqual(self.mod.read_record(journal.path)['rows'], rows)

    def test_text_exports_label_source_mode_and_do_not_present_stale_translation_as_current(self):
        rows = [{'id':'a','source':'标准词','source_original':'误识词','source_corrected':'标准词',
                 'translation':'旧译文','translation_stale':True,'translation_source_text':'误识词',
                 'translation_source_revision':'old','translation_text_revision':'new',
                 'start':0,'end':1,'speaker':1}]
        with tempfile.TemporaryDirectory() as folder:
            for fmt in ('txt','srt','vtt'):
                target = Path(folder) / ('out.'+fmt)
                self.mod.export_rows(rows, target, fmt, source_mode='corrected')
                data = target.read_text(encoding='utf-8')
                self.assertIn('纠错后文本：Speaker 1: 标准词', data)
                self.assertIn('译文待更新：旧译文', data)
                self.assertNotIn('\n旧译文\n', data)

    def test_text_exports_label_translation_error_and_pending_state(self):
        rows = [
            {'id':'pending','source':'Pending','translation':'','translation_pending':True,'start':0,'end':1},
            {'id':'failed','source':'Failed','translation':'last result','translation_error':'offline','start':2,'end':3},
        ]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'out.txt'
            self.mod.export_rows(rows, target, 'txt')
            data = target.read_text(encoding='utf-8')
            self.assertIn('译文待更新', data)
            self.assertIn('译文未完成（offline）：last result', data)

    def test_json_exports_include_translation_binding_and_source_mode(self):
        rows = [{'id':'a','source':'Corrected','source_original':'Original','source_corrected':'Corrected',
                 'translation':'Outdated','translation_stale':True,'translation_source_text':'Original',
                 'translation_source_revision':'g-old','translation_text_revision':'t-new',
                 'glossary_revision':'g-new','start':0,'end':1,
                 'native':{'text':'Original','translation':'Original translation',
                           'words':[{'text':'Original','start':0.1,'end':0.9}]}}]
        with tempfile.TemporaryDirectory() as folder:
            verbose = Path(folder) / 'verbose.json'
            diarized = Path(folder) / 'diarized.json'
            self.mod.export_rows(rows, verbose, 'verbose_json', source_mode='corrected')
            self.mod.export_rows(rows, diarized, 'diarized_json', source_mode='original')
            vdoc = self.mod.json.loads(verbose.read_text(encoding='utf-8'))
            ddoc = self.mod.json.loads(diarized.read_text(encoding='utf-8'))
            self.assertEqual(vdoc['source_mode'], 'corrected')
            self.assertEqual(vdoc['segments'][0]['translation_status'], 'stale')
            self.assertEqual(vdoc['segments'][0]['translation_source_text'], 'Original')
            self.assertEqual(vdoc['segments'][0]['translation_source_revision'], 'g-old')
            self.assertEqual(vdoc['segments'][0]['translation_text_revision'], 't-new')
            self.assertEqual(ddoc['source_mode'], 'original')
            self.assertEqual(ddoc['segments'][0]['text'], 'Original')
            self.assertEqual(ddoc['segments'][0]['translation_status'], 'ready')
            self.assertEqual(ddoc['segments'][0]['translation'], 'Original translation')
            self.assertEqual(ddoc['segments'][0]['translation_source_text'], 'Original')
            self.assertIsNone(ddoc['segments'][0]['translation_source_revision'])

    def test_native_json_stays_native_while_other_exports_mark_source_choice(self):
        native = {'start':'0:00:00.00','end':'0:00:01.00','text':'Original',
                  'tokens':[{'text':'Original','start':0.2,'end':0.8}], 'speaker':1}
        row = {'id':'a','source':'Corrected','source_original':'Original','source_corrected':'Corrected',
               'translation':'译文','start':0,'end':1,'speaker':1,'native':native}
        with tempfile.TemporaryDirectory() as folder:
            native_path = Path(folder) / 'native.json'
            text_path = Path(folder) / 'original.txt'
            self.mod.export_rows([row], native_path, 'native_json', source_mode='original')
            self.mod.export_rows([row], text_path, 'txt', source_mode='original')
            document = self.mod.json.loads(native_path.read_text(encoding='utf-8'))
            self.assertEqual(document['lines'][0], native)
            self.assertIn('原始听写：Speaker 1: Original', text_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
