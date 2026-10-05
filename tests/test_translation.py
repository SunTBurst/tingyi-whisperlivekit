import importlib
import unittest


class TranslationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.mod = importlib.import_module('app.translation')
        except ModuleNotFoundError:
            self.fail('缺少本地翻译实现 app.translation')

    def test_language_routes_cover_chinese_english_and_arabic(self):
        self.assertEqual(self.mod.language_tag('zh'), 'zho_Hans')
        self.assertEqual(self.mod.language_tag('en'), 'eng_Latn')
        self.assertEqual(self.mod.language_tag('ar'), 'arb_Arab')
        with self.assertRaises(ValueError):
            self.mod.language_tag('auto')

    def test_auto_language_uses_actual_script_when_metadata_missing(self):
        self.assertEqual(self.mod.resolve_source_language('我们明天开会。', 'auto', None), 'zh')
        self.assertEqual(self.mod.resolve_source_language('مرحبا بالعالم', 'auto', None), 'ar')
        self.assertEqual(self.mod.resolve_source_language('Bonjour.', 'auto', 'fr'), 'fr')
        self.assertEqual(self.mod.resolve_source_language('Meeting starts tomorrow.', 'auto', 'en'), 'en')

    def test_long_input_split_does_not_drop_text(self):
        text = '我们需要讨论工程进度。' * 110
        pieces = self.mod.split_text(text, 200)
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(len(x) <= 200 for x in pieces))

    def test_encoder_payload_contains_source_language_and_eos(self):
        self.assertEqual(self.mod.source_tokens(['▁Hello', '▁world', '!'], 'en'),
                         ['eng_Latn', '▁Hello', '▁world', '!', '</s>'])


if __name__ == '__main__':
    unittest.main()
