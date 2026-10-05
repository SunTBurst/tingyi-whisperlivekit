"""Connect WhisperLiveKit's native streaming translation engine to local weights."""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path
from typing import Any

from app.settings import ROOT

NLLB_MODEL_DIR = ROOT / "models" / "nllb-600m"
_PATCH_ATTR = "_whisperlivekit_local_ct2_wrapper"


def _nllb_ready(path: Path) -> bool:
    """Return true only for a complete CTranslate2 NLLB model + tokenizer."""
    required = (
        "config.json",
        "model.bin",
        "shared_vocabulary.txt",
        "sentencepiece.bpe.model",
        "tokenizer.json",
        "tokenizer_config.json",
    )
    return path.is_dir() and all((path / name).is_file() for name in required)


def _enable_cjk_streaming_guard(nllw_core) -> None:
    """Keep nllw's streaming logic active for scripts without word spaces."""
    backend_type = nllw_core.TranslationBackend
    if getattr(backend_type, "_local_cjk_guard", False):
        return
    original_translate = backend_type.translate
    source = textwrap.dedent(inspect.getsource(original_translate))
    guard = "if word_count < 3:"
    if source.count(guard) != 1:
        raise RuntimeError(
            "Unsupported nllw TranslationBackend.translate source: expected one "
            "`if word_count < 3:` guard; review local CJK compatibility patch."
        )

    def _local_cjk_input_ready(text: str) -> bool:
        cjk_count = sum(
            "\u3400" <= char <= "\u9fff"
            or "\u3040" <= char <= "\u30ff"
            or "\uac00" <= char <= "\ud7af"
            for char in text
        )
        has_sentence_end = text.rstrip().endswith((".", "!", "?", "。", "！", "？"))
        return cjk_count >= 6 or (cjk_count >= 2 and has_sentence_end)

    namespace = dict(original_translate.__globals__)
    namespace["_local_cjk_input_ready"] = _local_cjk_input_ready
    source = source.replace(guard, "if word_count < 3 and not _local_cjk_input_ready(buffer_text):", 1)
    exec(compile(source, inspect.getsourcefile(original_translate) or "nllw/core.py", "exec"), namespace)
    patched_translate = namespace[original_translate.__name__]
    setattr(patched_translate, "_local_cjk_guard", True)
    backend_type.translate = patched_translate
    backend_type._local_cjk_guard = True


class _LocalNllbTokenizer:
    """Transformers-5-independent NLLB tokenizer using the checkpoint SPM.

    NeMo is not involved here. nllw's CT2 backend needs token IDs for its
    streaming stability logic, while the CT2 checkpoint exchanges the original
    SentencePiece strings. This adapter maps between the checkpoint's shared
    vocabulary IDs and its bundled SentencePiece model.
    """

    _SPECIAL = {"<s>", "<pad>", "</s>", "<unk>", "<mask>"}

    def __init__(self, sentencepiece, vocabulary: list[str], src_lang: str):
        import torch

        self._sp = sentencepiece
        self._id_to_token = vocabulary
        self._token_to_id = {piece: index for index, piece in enumerate(vocabulary)}
        self._torch = torch
        self.src_lang = src_lang
        self.eos_token = "</s>"
        self.eos_token_id = self._token_to_id[self.eos_token]
        self.vocab_size = len(vocabulary)
        self.lang_code_to_id = {
            token: index for index, token in enumerate(vocabulary)
            if "_" in token and len(token) <= 12 and token not in self._SPECIAL
        }

    def __call__(self, text: str, return_tensors: str | None = None, **_kwargs):
        pieces = [self.src_lang, *self._sp.encode(text, out_type=str), self.eos_token]
        ids = [self._token_to_id.get(piece, self._token_to_id["<unk>"]) for piece in pieces]
        if return_tensors == "pt":
            tensor = self._torch.tensor([ids], dtype=self._torch.int64)
            return {"input_ids": tensor, "attention_mask": self._torch.ones_like(tensor)}
        return {"input_ids": ids}

    def convert_tokens_to_ids(self, tokens):
        if isinstance(tokens, str):
            return self._token_to_id.get(tokens, self._token_to_id["<unk>"])
        return [self.convert_tokens_to_ids(token) for token in tokens]

    def convert_ids_to_tokens(self, ids):
        if isinstance(ids, int):
            return self._id_to_token[ids] if 0 <= ids < self.vocab_size else "<unk>"
        if hasattr(ids, "tolist"):
            ids = ids.tolist()
        return [self.convert_ids_to_tokens(int(index)) for index in ids]

    def decode(self, ids, skip_special_tokens: bool = True, **_kwargs) -> str:
        if hasattr(ids, "tolist"):
            ids = ids.tolist()
        if isinstance(ids, int):
            ids = [ids]
        pieces = self.convert_ids_to_tokens(ids)
        if skip_special_tokens:
            pieces = [piece for piece in pieces if piece not in self._SPECIAL and piece not in self.lang_code_to_id]
        return self._sp.decode(pieces)


def configure_local_models(config: Any) -> bool:
    """Route configured NLLB 600M CTranslate2 loads through local model files.

    WhisperLiveKit's core calls ``from nllw import load_model`` and then keeps
    using nllw's OnlineTranslation/TranslationBackend streaming policy. nllw
    currently downloads the CTranslate2 weights from a fixed HF repository, so
    this hook substitutes only its loader for the explicitly requested local
    600M CT2 model. Other backends and model sizes retain nllw's own loader.

    Returns whether the local hook was installed.
    """
    if getattr(config, "nllb_backend", None) != "ctranslate2":
        return False
    if str(getattr(config, "nllb_size", "")).upper() != "600M":
        return False
    if not _nllb_ready(NLLB_MODEL_DIR):
        return False

    import nllw

    current = getattr(nllw, "load_model", None)
    if current is None:
        raise ImportError("Installed nllw package does not expose load_model")
    if getattr(current, _PATCH_ATTR, False):
        return True

    def load_local_model(src_langs, nllb_backend="transformers", nllb_size="600M"):
        # Honor nllw's public signature even if a caller bypasses this config
        # hook and supplies different values later.
        if nllb_backend != "ctranslate2" or str(nllb_size).upper() != "600M":
            return current(src_langs, nllb_backend=nllb_backend, nllb_size=nllb_size)

        import ctranslate2
        from sentencepiece import SentencePieceProcessor
        from nllw.core import TranslationModel
        from nllw.languages import convert_to_nllb_code
        import nllw.core as nllw_core

        _enable_cjk_streaming_guard(nllw_core)

        # Keep the validated 8 GB GPU available to ASR and Sortformer. The
        # deployed NLLB checkpoint is int8, so CPU decoding stays compact.
        device = "cpu"
        converted = []
        for language in src_langs:
            code = convert_to_nllb_code(language)
            if code is None:
                raise ValueError(f"Unknown language identifier: {language}")
            converted.append(code)

        translator = ctranslate2.Translator(
            str(NLLB_MODEL_DIR),
            device=device,
            compute_type="int8",
            inter_threads=1,
            intra_threads=8,
        )
        with (NLLB_MODEL_DIR / "shared_vocabulary.txt").open(encoding="utf-8") as stream:
            vocabulary = [line.rstrip("\r\n") for line in stream]
        spm = SentencePieceProcessor(model_file=str(NLLB_MODEL_DIR / "sentencepiece.bpe.model"))
        tokenizer = {
            language: _LocalNllbTokenizer(spm, vocabulary, language)
            for language in converted if language != "auto"
        }
        model = TranslationModel(
            translator=translator,
            tokenizer=tokenizer,
            backend_type="ctranslate2",
            device=device,
            nllb_size="600M",
            model_name=str(NLLB_MODEL_DIR),
        )

        def get_local_tokenizer(input_lang: str):
            if not model.tokenizer.get(input_lang):
                model.tokenizer[input_lang] = _LocalNllbTokenizer(spm, vocabulary, input_lang)
            return model.tokenizer[input_lang]

        model.get_tokenizer = get_local_tokenizer
        return model

    setattr(load_local_model, _PATCH_ATTR, True)
    nllw.load_model = load_local_model
    return True
