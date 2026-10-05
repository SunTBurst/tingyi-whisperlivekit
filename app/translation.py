"""Offline NLLB translation; no HTTP endpoint or LM Studio is needed."""
import re
from pathlib import Path

TAGS = {
    'zh':'zho_Hans', 'en':'eng_Latn', 'ar':'arb_Arab', 'ja':'jpn_Jpan',
    'ko':'kor_Hang', 'fr':'fra_Latn', 'de':'deu_Latn', 'es':'spa_Latn',
    'ru':'rus_Cyrl', 'hi':'hin_Deva', 'pt':'por_Latn', 'tr':'tur_Latn',
}


def language_tag(code):
    try:
        return TAGS[code]
    except KeyError as exc:
        raise ValueError(f'不支持的翻译语言：{code}，请指定识别语言') from exc


def resolve_source_language(text, selected, detected):
    if selected != 'auto':
        language_tag(selected)
        return selected
    if detected in TAGS:
        return detected
    if re.search(r'[\u4e00-\u9fff]', text):
        return 'zh'
    if re.search(r'[\u0600-\u06ff]', text):
        return 'ar'
    # Avoid silently interpreting every Latin script as English.
    raise ValueError('未能确认输入语言，请在识别语言中选择本次会议的语言')


def split_text(text, limit=250):
    result = []
    while len(text) > limit:
        prefix = text[:limit]
        breaks = [m.end() for m in re.finditer(r'[。！？.!?;；\n]|\s', prefix)]
        cut = breaks[-1] if breaks and breaks[-1] > limit // 3 else limit
        result.append(text[:cut])
        text = text[cut:]
    if text:
        result.append(text)
    return result


def source_tokens(pieces, source):
    return [language_tag(source), *pieces, '</s>']


class LocalTranslator:
    def __init__(self, model_dir):
        from ctranslate2 import Translator
        from sentencepiece import SentencePieceProcessor
        model_dir = Path(model_dir)
        if not (model_dir / 'model.bin').is_file():
            raise FileNotFoundError('本地翻译模型缺失，请运行修复环境.ps1')
        # Keep translation off the GPU so existing local applications can coexist.
        self.model = Translator(str(model_dir), device='cpu', compute_type='int8', intra_threads=8, inter_threads=1)
        self.tokenizer = SentencePieceProcessor(model_file=str(model_dir / 'sentencepiece.bpe.model'))

    def translate(self, text, source, target):
        source_tag, target_tag = language_tag(source), language_tag(target)
        if source == target or not text.strip():
            return text
        translated = []
        for piece in split_text(text):
            tokens = source_tokens(self.tokenizer.encode(piece, out_type=str), source)
            results = self.model.translate_batch([tokens], target_prefix=[[target_tag]], beam_size=2, max_decoding_length=256)
            hypothesis = results[0].hypotheses[0]
            if hypothesis and hypothesis[0] == target_tag:
                hypothesis = hypothesis[1:]
            hypothesis = [token for token in hypothesis if token not in ('</s>', '<s>', '<pad>')]
            output = self.tokenizer.decode(hypothesis).strip()
            if not output:
                raise RuntimeError('本地翻译返回空文本')
            translated.append(output)
        return (' ' if target != 'zh' else '').join(translated)
