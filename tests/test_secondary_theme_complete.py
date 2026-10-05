from __future__ import annotations

from copy import deepcopy
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from app.ai_ui import AIModelDialog
from app.glossary_ui import GlossaryDialog
from app.meeting_ui import ParticipantsDialog, RecoveryDialog
from app.participants import ParticipantRegistry
from app.theme import palette_for, style_for
from app.appearance import set_theme


def _app():
    return QApplication.instance() or QApplication([])


def _dialogs(tmp_path, glossary_settings=None):
    registry = ParticipantRegistry(state={
        "participants": {f"p-{i}": {"name": f"Synthetic {i}", "source": "main", "confirmed": False}
                         for i in range(20)},
        "bindings": {},
    })
    records = [(tmp_path / f"synthetic-{i}.json", {
        "rows": [{"text": "synthetic"}], "row_count": 1,
        "last_saved_at": "2099-01-01T00:00:00",
    }) for i in range(24)]
    return [
        AIModelDialog({"llm_url": "http://127.0.0.1:1234/v1"}, lambda: [], lambda: None),
        GlossaryDialog(glossary_settings or {"glossary_rules": []}),
        ParticipantsDialog(registry, []),
        RecoveryDialog(records),
    ]


def _pixel(widget, x=8, y=8):
    image = widget.grab().toImage()
    return image.pixelColor(min(x, image.width() - 1), min(y, image.height() - 1)).name().upper()


def test_all_secondary_dialogs_follow_live_theme_changes_and_preserve_settings(tmp_path, monkeypatch):
    app = _app()
    from app import glossary_ui
    monkeypatch.setattr(glossary_ui, "GLOSSARY_DIR", tmp_path / "glossaries")
    original = {"glossary_rules": [{"original": "x", "replacement": "y"}], "other": {"v": 1}}
    snapshot = deepcopy(original)
    dialogs = _dialogs(tmp_path, original)
    try:
        for dialog in dialogs:
            dialog.show()
        app.processEvents()
        assert original == snapshot

        for theme in ("dark", "sky", "spring", "dark"):
            dialogs[2].participant_list.setCurrentRow(-1)
            set_theme(theme)
            app.processEvents()
            for dialog in dialogs:
                assert dialog.styleSheet() == style_for(theme)
                assert _pixel(dialog) == palette_for(theme)["window"].upper()

            # Check rendered controls as well as top-level backgrounds: fields,
            # table body/header, transcript-style output, and participant lists.
            palette = palette_for(theme)
            ai = dialogs[0]
            glossary = dialogs[1]
            participants = dialogs[2]
            recovery = dialogs[3]
            assert _pixel(ai.url_edit, ai.url_edit.width() - 15,
                          ai.url_edit.height() // 2) == palette["field"].upper()
            assert _pixel(ai.result_view, 20, ai.result_view.height() // 2) == palette["field"].upper()
            assert _pixel(glossary.table.viewport(), 20, 20) == palette["surface"].upper()
            assert _pixel(glossary.table.horizontalHeader(),
                          glossary.table.horizontalHeader().width() - 4,
                          glossary.table.horizontalHeader().height() // 2) == palette["soft_surface"].upper()
            assert _pixel(participants.participant_list.viewport(),
                          participants.participant_list.viewport().width() - 3, 2) == palette["surface"].upper()
            participants.participant_list.setCurrentRow(0)
            selected_rect = participants.participant_list.visualItemRect(participants.participant_list.item(0))
            assert _pixel(participants.participant_list, 2, selected_rect.center().y()) == palette["accent"].upper()
            assert _pixel(recovery.records_table.viewport(), 20, 20) == palette["surface"].upper()
            scrollbar = recovery.records_table.verticalScrollBar()
            assert scrollbar.isVisible()
            scrollbar_color = palette["field"] if theme == "dark" else palette["soft_surface"]
            handle_color = "#4B6473" if theme == "dark" else palette["icon"]
            assert _pixel(scrollbar, 2, 2) == handle_color.upper()
            assert _pixel(scrollbar, 2, scrollbar.height() - 3) == scrollbar_color.upper()

        assert all(dialog.parent() is None for dialog in dialogs)
        dialogs[1]._add_row()
        assert original == snapshot
    finally:
        refs = list(dialogs)
        for dialog in dialogs:
            dialog.close()
            sip.delete(dialog)
        app.processEvents()
        assert all(sip.isdeleted(dialog) for dialog in refs)
        set_theme("dark")
        app.processEvents()

