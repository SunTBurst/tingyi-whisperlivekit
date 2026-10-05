import csv

import pytest

from app.glossary import FIELD_LABELS, Glossary, export_rules, export_template, preview_import


def rule(original, replacement, **extra):
    return {"enabled": True, "language": "en", "original": original,
            "replacement": replacement, "match_mode": "text", **extra}


def test_corrections_are_single_pass_longest_first_and_keep_hits():
    glossary = Glossary([
        rule("wind", "turbine"),
        rule("wind turbine", "WTG"),
    ])

    result = glossary.correct("The wind turbine and wind.", "en")

    assert result["original"] == "The wind turbine and wind."
    assert result["corrected"] == "The WTG and turbine."
    assert [hit["original"] for hit in result["hits"]] == ["wind turbine", "wind"]
    assert result["revision"]


def test_english_whole_word_does_not_change_longer_words():
    glossary = Glossary([rule("transformer", "transfomer", match_mode="whole_word")])
    assert glossary.correct("transformers transformer", "en")["corrected"] == "transformers transfomer"


def test_language_scope_and_disabled_rules_are_respected():
    glossary = Glossary([
        rule("meeting", "会议", language="en"),
        rule("会议", "会议室", language="zh", enabled=False),
    ])
    assert glossary.correct("meeting", "zh")["corrected"] == "meeting"
    assert glossary.correct("会议", "zh")["corrected"] == "会议"


def test_decorate_preserves_native_evidence_and_marks_old_translation_stale():
    glossary = Glossary([rule("recieve", "receive")])
    row = {"text": "recieve", "words": [{"text": "recieve", "start": 1.0}],
           "native": {"text": "recieve"}, "translation": "收件",
           "translation_source_revision": "old-revision", "language": "en", "start": 1, "end": 2}

    decorated = glossary.decorate(row)

    assert decorated is not row
    assert decorated["source_original"] == "recieve"
    assert decorated["source_corrected"] == "receive"
    assert decorated["source"] == "receive"
    assert decorated["words"] == row["words"] and decorated["native"] is row["native"]
    assert decorated["start"] == 1 and decorated["end"] == 2
    assert decorated["translation_stale"] is True
    assert row["text"] == "recieve"


def test_returning_to_original_text_marks_corrected_translation_stale():
    row = {"source": "Acme Corp", "source_original": "ACME", "source_corrected": "Acme Corp",
           "translation": "旧译文", "translation_source_text": "Acme Corp",
           "translation_source_revision": "old", "translation_stale": False,
           "native": {"text": "ACME"}}

    result = Glossary([], enabled=False).decorate(row)

    assert result["source"] == "ACME"
    assert result["translation"] == "旧译文"
    assert result["translation_stale"] is True
    assert result["native"] is row["native"]


def test_matching_translation_binding_stays_fresh_after_decorate():
    glossary = Glossary([rule("teh", "the")])
    source = glossary.correct("teh", "en")["corrected"]
    row = {"source": "teh", "source_original": "teh", "language": "en", "translation": "译文",
           "translation_source_text": source, "translation_source_revision": glossary.revision,
           "translation_stale": True}

    result = glossary.decorate(row)

    assert result["source"] == source
    assert result["translation_stale"] is False


def test_fixed_translation_can_normalize_translator_output_for_matching_target():
    glossary = Glossary([rule("recieve", "receive", fixed_translation="استلام",
                              target_language="ar")])
    assert glossary.apply_fixed_translations("receive tomorrow", "ar") == "استلام tomorrow"
    assert glossary.apply_fixed_translations("receive tomorrow", "zh") == "receive tomorrow"


def test_disabled_glossary_does_not_rewrite_fixed_translation():
    glossary = Glossary([rule("wtg", "wind turbine", target_language="ar",
                              fixed_translation="توربين")], enabled=False)
    assert glossary.apply_fixed_translations("wind turbine", "ar") == "wind turbine"


def test_import_preview_identifies_additions_conflicts_and_duplicates(tmp_path):
    path = tmp_path / "rules.csv"
    export_rules(path, [rule("recieve", "receive"), rule("colour", "color")])
    current = [rule("recieve", "receive"), rule("colour", "hue")]

    preview = preview_import(path, current)

    assert len(preview["added"]) == 0
    assert len(preview["conflicts"]) == 1
    assert preview["conflicts"][0]["original"] == "colour"
    assert preview["skipped"] == 1


def test_csv_template_roundtrip_is_utf8_bom_and_deduplicates(tmp_path):
    template = tmp_path / "template.csv"
    export_template(template)
    assert template.read_bytes().startswith(b"\xef\xbb\xbf")
    with template.open(encoding="utf-8-sig", newline="") as stream:
        fields = csv.DictReader(stream).fieldnames
    assert set(FIELD_LABELS.values()) <= set(fields)

    rules = [rule("recieve", "receive"), rule("recieve", "receive")]
    current = tmp_path / "current.csv"
    export_rules(current, rules)
    preview = preview_import(current, [])
    assert len(preview["added"]) == 1
    assert preview["skipped"] == 1


def test_xlsx_export_import_roundtrip_when_openpyxl_is_available(tmp_path):
    pytest.importorskip("openpyxl")
    path = tmp_path / "rules.xlsx"
    source = [rule("recieve", "receive", fixed_translation="استلام", target_language="ar")]
    export_rules(path, source)
    result = preview_import(path, [])
    assert result["added"][0]["original"] == "recieve"
    assert result["added"][0]["fixed_translation"] == "استلام"
    assert result["added"][0]["target_language"] == "ar"


def test_import_with_same_key_and_different_replacement_is_located(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "original,replacement,language,match_mode\nacme,ACME,en,text\nacme,Acme,en,text\n",
        encoding="utf-8-sig")
    with pytest.raises(ValueError, match="conflict in import.*row"):
        preview_import(path, [])


def test_import_skips_empty_rows_without_shifting_valid_rules(tmp_path):
    path = tmp_path / "with-blank-rows.csv"
    path.write_text(
        "original,replacement,language,match_mode,enabled\n\n , , , , \nwtg,wind turbine,en,text,\n",
        encoding="utf-8-sig")
    preview = preview_import(path, [])
    assert preview["added"][0]["original"] == "wtg"


def test_enabled_defaults_on_when_missing_or_blank_but_respects_explicit_false():
    assert Glossary([{"language": "en", "original": "wtg", "replacement": "wind turbine"}]).rules[0]["enabled"]
    assert Glossary([{"language": "en", "original": "wtg", "replacement": "wind turbine",
                      "enabled": ""}]).rules[0]["enabled"]
    assert not Glossary([{"language": "en", "original": "wtg", "replacement": "wind turbine",
                          "enabled": "否"}]).rules[0]["enabled"]


@pytest.mark.parametrize(("entered", "normalized"), [
    ("中文", "zh"), ("英语", "en"), ("英文", "en"), ("阿拉伯语", "ar"), ("全部", "*"),
])
def test_chinese_language_names_normalize_to_supported_scopes(entered, normalized):
    glossary = Glossary([{"language": entered, "original": "name", "replacement": "标准词"}])
    assert glossary.rules[0]["language"] == normalized


def test_glossary_language_scopes_match_iso_and_nllb_codes_without_heavy_imports():
    glossary = Glossary([rule("wrong", "right", language="英文",
                              target_language="中文", fixed_translation="固定译名")])

    assert glossary.correct("wrong", "eng_Latn")["corrected"] == "right"
    assert glossary.correct("wrong", "en")["corrected"] == "right"
    assert glossary.rules[0]["target_language"] == "zh"
    assert glossary.apply_fixed_translations("right", "zho_Hans") == "固定译名"
    assert glossary.apply_fixed_translations("right", "zho_Hant") == "固定译名"


def test_generic_chinese_rule_does_not_cross_specific_script_codes():
    glossary = Glossary([rule("术语", "标准词", language="zho_Hans")])
    assert glossary.correct("术语", "zh")["corrected"] == "标准词"
    assert glossary.correct("术语", "zho_Hans")["corrected"] == "标准词"
    assert glossary.correct("术语", "zho_Hant")["corrected"] == "术语"


def test_matching_regexes_are_compiled_once_when_rules_are_loaded(monkeypatch):
    import app.glossary as glossary_module

    finditer_calls = []
    original_finditer = glossary_module.re.finditer
    monkeypatch.setattr(glossary_module.re, "finditer",
                        lambda *args, **kwargs: (finditer_calls.append(args[0]) or original_finditer(*args, **kwargs)))
    glossary = Glossary([rule(f"term-{index}", f"fixed-{index}") for index in range(1000)])
    finditer_calls.clear()

    for _ in range(10):
        glossary.correct("term-999 remains", "en")

    assert finditer_calls == []


def test_invalid_rule_collisions_are_rejected():
    with pytest.raises(ValueError, match="conflict"):
        Glossary([rule("acme", "ACME"), rule("acme", "Acme")])


def test_same_correction_with_conflicting_fixed_translations_is_rejected():
    with pytest.raises(ValueError, match="conflict"):
        Glossary([rule("wtg", "wind turbine", target_language="ar", fixed_translation="أ"),
                  rule("wtg", "wind turbine", target_language="ar", fixed_translation="ب")])
