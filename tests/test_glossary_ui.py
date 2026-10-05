import pytest
from PyQt6.QtWidgets import QApplication

from app import glossary_ui
from app.glossary_ui import GlossaryDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_dialog_returns_enabled_rules_and_current_profile(app, tmp_path, monkeypatch):
    monkeypatch.setattr(glossary_ui, "GLOSSARY_DIR", tmp_path / "glossaries")
    dialog = GlossaryDialog({"glossary_enabled": False,
                             "glossary_rules": [{"enabled": True, "language": "en",
                                                 "original": "teh", "replacement": "the",
                                                 "match_mode": "text"}]})

    values = dialog.values()

    assert values["glossary_enabled"] is False
    assert values["glossary_rules"][0]["original"] == "teh"
    assert values["glossary_profile"] == "Default"


def test_profile_switching_preserves_separate_project_rules(app, tmp_path, monkeypatch):
    monkeypatch.setattr(glossary_ui, "GLOSSARY_DIR", tmp_path / "glossaries")
    dialog = GlossaryDialog({})
    dialog.set_rules([{"enabled": True, "language": "en", "original": "teh",
                       "replacement": "the", "match_mode": "text"}])
    dialog.add_profile("Project B")
    dialog.set_rules([{"enabled": True, "language": "zh", "original": "风机",
                       "replacement": "风力发电机", "match_mode": "text"}])
    dialog.select_profile("Default")

    assert dialog.values()["glossary_rules"][0]["original"] == "teh"
    assert (tmp_path / "glossaries" / "profiles.json").exists()


def test_import_merge_can_be_previewed_applied_and_undone(app, tmp_path, monkeypatch):
    monkeypatch.setattr(glossary_ui, "GLOSSARY_DIR", tmp_path / "glossaries")
    incoming = tmp_path / "incoming.csv"
    incoming.write_text(
        "enabled,language,original,replacement,match_mode\ntrue,en,teh,the,text\n",
        encoding="utf-8-sig")
    dialog = GlossaryDialog({})

    preview = dialog.load_import(incoming)
    dialog.apply_import("merge")
    assert len(preview["added"]) == 1
    assert dialog.values()["glossary_rules"][0]["replacement"] == "the"
    assert dialog.undo_import() is True
    assert dialog.values()["glossary_rules"] == []


def test_text_preview_shows_rule_hits_without_changing_rule_or_source(app):
    dialog = GlossaryDialog({"glossary_rules": [
        {"enabled": True, "language": "en", "original": "teh", "replacement": "the",
         "match_mode": "text"}]})
    result = dialog.preview_text("teh meeting", "en")
    assert result["corrected"] == "the meeting"
    assert result["hits"]
