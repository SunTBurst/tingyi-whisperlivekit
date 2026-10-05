from app import text_translation


class FakeTokenizer:
    def __init__(self, answers):
        self.answers = answers

    def __call__(self, text, return_tensors=None):
        return {"input_ids": [[text]], "text": text}

    def decode(self, token_ids, skip_special_tokens=True):
        if isinstance(token_ids, list) and token_ids:
            return self.answers.get(token_ids[0], str(token_ids[0]))
        return str(token_ids)


class FakeBackend:
    def __init__(self, text, answers, output):
        self.text = text
        self.tokenizer = FakeTokenizer(answers)
        self.output = output
        self.input_buffer = []
        self.using_ctranslate2 = True
        self.fallback_calls = []

    def translate(self, text):
        self.input_buffer.append(text)
        return self.output.get(text, ("", ""))

    def _translate_with_ctranslate2(self, input_ids):
        self.fallback_calls.append(input_ids)
        return [input_ids[0]]


def patch_backends(monkeypatch, factory):
    monkeypatch.setattr(text_translation, "_new_backend", factory)
    text_translation.clear_term_translation_cache()


def test_returns_stable_and_draft_text_from_a_fresh_backend(monkeypatch):
    made = []

    def factory(model, source, target):
        backend = FakeBackend("", {}, {"First sentence.": ("Stable ", "draft")})
        made.append(backend)
        return backend

    patch_backends(monkeypatch, factory)
    result = text_translation.translate_with_model(object(), "First sentence.", "en", "zh")

    assert result == {"translation": "Stable draft", "fixed_terms_unapplied": []}
    assert made[0].input_buffer == ["First sentence."]


def test_short_term_uses_backend_fallback_and_tokenizer_decode(monkeypatch):
    made = []

    def factory(model, source, target):
        backend = FakeBackend("", {"NLLB_TOKEN": "中文词"}, {})
        backend.tokenizer = FakeTokenizer({"single": "中文词", "NLLB_TOKEN": "中文词"})
        backend._translate_with_ctranslate2 = lambda ids: (made.append(ids) or ["NLLB_TOKEN"])
        made.append(backend)
        return backend

    patch_backends(monkeypatch, factory)
    result = text_translation.translate_with_model(object(), "single", "en", "zh")

    assert result["translation"] == "中文词"
    assert len(made) == 2
    assert made[1] == ["single"]


def test_calls_use_independent_backend_prefix_state(monkeypatch):
    made = []

    def factory(model, source, target):
        backend = FakeBackend("", {}, {"First.": ("first ", "draft"),
                                         "Second.": ("second ", "draft")})
        made.append(backend)
        return backend

    patch_backends(monkeypatch, factory)
    model = object()
    first = text_translation.translate_with_model(model, "First.", "en", "zh")
    second = text_translation.translate_with_model(model, "Second.", "en", "zh")

    assert first["translation"] == "first draft"
    assert second["translation"] == "second draft"
    assert len(made) == 2
    assert made[0].input_buffer == ["First."]
    assert made[1].input_buffer == ["Second."]


def test_fixed_term_is_reported_when_translated_text_has_no_default_term(monkeypatch):
    calls = []

    def output_backend(model, source, target):
        backend = FakeBackend("", {}, {"Acme turbine is ready.": ("This machine is ready.", ""),
                                        "Acme turbine": ("Acme engine", ""),
                                        "Acme": ("default ", "translated term")})
        backend.translate = lambda text: (calls.append(text) or backend.output.get(text, ("", "")))
        return backend

    patch_backends(monkeypatch, output_backend)
    result = text_translation.translate_with_model(
        object(), "Acme turbine is ready.", "en", "zh",
        glossary_rules=[{"enabled": True, "language": "en", "original": "acme turbine",
                         "replacement": "Acme turbine", "match_mode": "text",
                         "target_language": "zh", "fixed_translation": "阿克米涡轮机"}],
    )

    assert result["translation"] == "This machine is ready."
    assert result["fixed_terms_unapplied"][0]["term"] == "Acme turbine"
    assert calls.count("Acme turbine") == 1


def test_fixed_term_translation_is_applied_when_default_term_is_present(monkeypatch):
    calls = []

    def factory(model, source, target):
        outputs = {"The Acme turbine works.": ("The 阿克米涡轮机 works.", ""),
                   "Acme turbine": ("阿克米涡轮机", "")}
        backend = FakeBackend("", {}, outputs)
        backend.translate = lambda text: (calls.append(text) or outputs.get(text, ("", "")))
        return backend

    patch_backends(monkeypatch, factory)
    result = text_translation.translate_with_model(
        object(), "The Acme turbine works.", "en", "zh",
        glossary_rules=[{"enabled": True, "language": "en", "original": "acme turbine",
                         "replacement": "Acme turbine", "match_mode": "whole_word",
                         "target_language": "zh", "fixed_translation": "艾克米风机"}],
    )

    assert result["translation"] == "The 艾克米风机 works."
    assert result["fixed_terms_unapplied"] == []
    assert "Acme turbine" in calls


def test_default_term_translation_is_cached_per_model_and_language_pair(monkeypatch):
    calls = []

    def factory(model, source, target):
        outputs = {"Acme turbine arrives.": ("Term arrives.", ""),
                   "Acme turbine departs.": ("Term departs.", ""),
                   "Acme turbine": ("Term", "")}
        backend = FakeBackend("", {}, outputs)
        backend.translate = lambda text: (calls.append(text) or outputs.get(text, ("", "")))
        return backend

    patch_backends(monkeypatch, factory)
    model = object()
    rule = {"enabled": True, "language": "en", "original": "acme turbine",
            "replacement": "Acme turbine", "match_mode": "whole_word",
            "target_language": "zh", "fixed_translation": "艾克米风机"}
    first = text_translation.translate_with_model(model, "Acme turbine arrives.", "en", "zh", [rule])
    second = text_translation.translate_with_model(model, "Acme turbine departs.", "en", "zh", [rule])

    assert first["translation"] == "艾克米风机 arrives."
    assert second["translation"] == "艾克米风机 departs."
    assert calls.count("Acme turbine") == 1


def test_chinese_glossary_target_scope_matches_nllb_hans_code(monkeypatch):
    calls = []

    def factory(model, source, target):
        outputs = {"The turbine works.": ("The default-term works.", ""),
                   "turbine": ("default-term", "")}
        backend = FakeBackend("", {}, outputs)
        backend.translate = lambda text: (calls.append(text) or outputs.get(text, ("", "")))
        return backend

    patch_backends(monkeypatch, factory)
    result = text_translation.translate_with_model(
        object(), "The turbine works.", "eng_Latn", "zho_Hans",
        glossary_rules=[{"language": "英文", "original": "turbine", "replacement": "turbine",
                         "match_mode": "whole_word", "target_language": "中文",
                         "fixed_translation": "风机"}],
    )

    assert result["translation"] == "The 风机 works."
    assert result["fixed_terms_unapplied"] == []
    assert calls.count("turbine") == 1
