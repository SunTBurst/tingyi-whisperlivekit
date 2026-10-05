"""One-shot text translation using the application's loaded NLLB model."""
from __future__ import annotations

from collections import OrderedDict
import re
import threading
from typing import Any

from app.glossary import canonical_language, language_matches, normalize_rule

_TERM_CACHE: OrderedDict[tuple[Any, ...], tuple[Any, str]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 512


def clear_term_translation_cache() -> None:
    """Clear small in-process terminology translations (useful for model swaps/tests)."""
    with _CACHE_LOCK:
        _TERM_CACHE.clear()


def _language_code(value: str) -> str:
    from nllw.languages import convert_to_nllb_code
    code = convert_to_nllb_code(value)
    if code is None:
        raise ValueError(f"Unsupported translation language: {value}")
    return code


def _new_backend(model, source: str, target: str):
    """Build a fresh NLLW backend so its streaming prefix cannot leak across calls."""
    from nllw.core import TranslationBackend

    source_code, target_code = _language_code(source), _language_code(target)
    tokenizer = model.get_tokenizer(source_code)
    return TranslationBackend(source_lang=source_code, target_lang=target_code,
                              model_name=getattr(model, "model_name", ""),
                              model=model.translator, tokenizer=tokenizer,
                              backend_type=model.backend_type)


def _decode_short_fallback(backend, text: str) -> str:
    tokenized = backend.tokenizer(text, return_tensors="pt")
    input_ids = tokenized["input_ids"][0]
    if backend.using_ctranslate2:
        tokens = backend._translate_with_ctranslate2(input_ids)
    else:
        tokens = backend._hf_transformers_translate(tokenized)
    decoded = backend.tokenizer.decode(tokens, skip_special_tokens=True)
    return str(decoded or "").strip()


def _translate_once(model, text: str, source: str, target: str) -> str:
    if not text.strip():
        return ""
    if source == target:
        return text
    backend = _new_backend(model, source, target)
    stable, draft = backend.translate(text)
    result = f"{stable or ''}{draft or ''}".strip()
    if result:
        return result
    return _decode_short_fallback(backend, text)


def _applies(rule_language: str, requested_language: str) -> bool:
    return language_matches(rule_language, requested_language)


def _pattern(term: str, mode: str, language: str) -> re.Pattern:
    value = re.escape(term)
    if mode.startswith("whole_word") and canonical_language(language).startswith("en"):
        value = rf"(?<!\w){value}(?!\w)"
    flags = 0 if mode.endswith("case_sensitive") else re.IGNORECASE
    return re.compile(value, flags)


def _cache_key(model, source: str, target: str, term: str) -> tuple[Any, ...]:
    return (id(model), getattr(model, "model_name", ""), source, target, term.casefold())


def _term_translation(model, source: str, target: str, term: str) -> str:
    key = _cache_key(model, source, target, term)
    with _CACHE_LOCK:
        cached = _TERM_CACHE.get(key)
        if cached is not None and cached[0] is model:
            _TERM_CACHE.move_to_end(key)
            return cached[1]
    translated = _translate_once(model, term, source, target).strip()
    with _CACHE_LOCK:
        _TERM_CACHE[key] = (model, translated)
        _TERM_CACHE.move_to_end(key)
        while len(_TERM_CACHE) > _CACHE_LIMIT:
            _TERM_CACHE.popitem(last=False)
    return translated


def _fixed_rules(text: str, source: str, target: str, glossary_rules) -> list[dict[str, Any]]:
    selected = []
    for index, raw in enumerate(glossary_rules or []):
        rule = normalize_rule(raw, index + 1)
        if (not rule["enabled"] or not rule["fixed_translation"] or
                not _applies(rule["language"], source) or
                (rule["target_language"] and not _applies(rule["target_language"], target))):
            continue
        if _pattern(rule["replacement"], rule["match_mode"], source).search(text):
            rule = dict(rule)
            rule["_index"] = index
            selected.append(rule)
    return selected


def _apply_fixed_terms(translation: str, target: str, terms: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    candidates = []
    unapplied = []
    for item in terms:
        translated_term = item["default_translation"]
        if not translated_term:
            unapplied.append({"term": item["replacement"], "fixed_translation": item["fixed_translation"],
                              "reason": "default_term_translation_empty"})
            continue
        pattern = _pattern(translated_term, item["match_mode"], target)
        matches = list(pattern.finditer(translation))
        if not matches:
            unapplied.append({"term": item["replacement"], "fixed_translation": item["fixed_translation"],
                              "reason": "default_term_not_present_in_translation"})
            continue
        for match in matches:
            candidates.append((match.start(), -(match.end() - match.start()), item["_index"],
                               match.end(), item["fixed_translation"], item))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    pieces, applied, cursor = [], set(), 0
    for start, _, _, end, replacement, item in candidates:
        if start < cursor:
            continue
        pieces.extend((translation[cursor:start], replacement))
        cursor = end
        applied.add(item["_index"])
    pieces.append(translation[cursor:])
    for item in terms:
        if item["_index"] not in applied and not any(row["term"] == item["replacement"] for row in unapplied):
            unapplied.append({"term": item["replacement"], "fixed_translation": item["fixed_translation"],
                              "reason": "default_term_not_present_in_translation"})
    return "".join(pieces), unapplied


def translate_with_model(model, text: str, source: str, target: str,
                         glossary_rules=()) -> dict[str, Any]:
    """Translate text with NLLW, optionally fixing glossary terms present in source.

    Each main and term translation receives a new TranslationBackend. This preserves
    NLLW's stable-plus-draft output while keeping its streaming prefix state request-local.
    """
    text = str(text or "")
    if not text.strip():
        return {"translation": "", "fixed_terms_unapplied": []}
    selected = _fixed_rules(text, source, target, glossary_rules)
    translation = _translate_once(model, text, source, target)
    term_jobs = []
    for rule in selected:
        term_jobs.append({**rule, "default_translation": _term_translation(
            model, source, target, rule["replacement"])})
    translation, unapplied = _apply_fixed_terms(translation, target, term_jobs)
    return {"translation": translation, "fixed_terms_unapplied": unapplied}
