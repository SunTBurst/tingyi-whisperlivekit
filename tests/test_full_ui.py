import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from app.ui import LANGUAGES, MainWindow, SettingsDialog, _language_catalog
from app.wlk_config import field_schema


class FullUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, **extra):
        settings = {
            "source_mode": "system", "source_language": "auto", "target_language": "zh",
            "asr_model": "medium", "translation_mode": "local", "font_size": 24,
            "opacity": 0.94, "always_on_top": False, "save_records": True,
            **extra,
        }
        window = MainWindow(settings, {"output": [], "input": []})
        self.addCleanup(window.close)
        return window

    def test_complete_whisper_and_nllb_language_catalog_is_loaded_lazily(self):
        assert LANGUAGES is None
        catalog = _language_catalog()
        values = {value for _, value in catalog}
        assert "auto" in values and "yue" in values and "zh" in values
        assert "zho_Hans" in values
        window = self.make_window()
        assert window.source_language.count() >= 90
        assert window.source_language.findData("zho_Hans") < 0
        assert window.target_language.findData("zho_Hans") >= 0

    def test_settings_expose_common_pipeline_and_full_advanced_schema(self):
        dialog = SettingsDialog({"asr_model": "medium", "wlk": {}, "context": "PIF5"}, {"output": [], "input": []})
        self.addCleanup(dialog.close)
        assert dialog.model_combo.count() == 12
        assert dialog.advanced.widgets.keys() == {field["name"] for field in field_schema()}
        assert dialog.backend_combo.currentData() == "faster-whisper"
        assert dialog.policy_combo.currentData() == "localagreement"
        assert dialog.nllb_backend.currentData() == "ctranslate2"
        dialog.context_edit.setPlainText("术语" * 1001)
        values = dialog.values()
        assert len(values["context"]) == 1000
        assert values["wlk"]["model_size"] == "medium"
        assert values["wlk"]["model_dir"] is None

    def test_manual_model_directory_and_advanced_model_size_are_retained(self):
        dialog = SettingsDialog({"asr_model": "medium", "wlk": {}}, {"output": [], "input": []})
        self.addCleanup(dialog.close)
        model_widget = dialog.advanced.widgets["model_size"]
        model_widget.setCurrentIndex(model_widget.findData("large-v3"))
        dir_widget = dialog.advanced.widgets["model_dir"]
        dir_widget.setText("D:/speech models/custom")
        values = dialog.values()
        assert values["asr_model"] == "large-v3"
        assert values["wlk"]["model_size"] == "large-v3"
        assert values["wlk"]["model_dir"] == "D:/speech models/custom"

    def test_running_settings_allow_only_language_and_display_edits(self):
        dialog = SettingsDialog({"asr_model": "medium", "source_mode": "both", "wlk": {}}, {"output": [], "input": []}, session_active=True)
        self.addCleanup(dialog.close)
        assert not dialog.model_combo.isEnabled()
        assert not dialog.backend_combo.isEnabled()
        assert not dialog.output_device.isEnabled()
        assert not dialog.separate_sources.isEnabled()
        assert dialog.source_language_combo.isEnabled()
        assert dialog.target_language_combo.isEnabled()
        assert dialog.mic_language.isEnabled()
        assert dialog.mic_target_language.isEnabled()
        assert dialog.advanced.widgets["lan"].isEnabled()
        assert dialog.advanced.widgets["target_language"].isEnabled()
        assert not dialog.advanced.widgets["backend"].isEnabled()
        assert dialog.font_spin.isEnabled()
        assert dialog.opacity_slider.isEnabled()

    def test_paused_settings_allow_every_native_pipeline_field(self):
        dialog = SettingsDialog({"asr_model": "medium", "wlk": {}}, {"output": [], "input": []},
                                session_active=True, session_paused=True)
        self.addCleanup(dialog.close)
        assert dialog.model_combo.isEnabled()
        assert dialog.output_device.isEnabled()
        assert dialog.separate_sources.isEnabled()
        assert all(widget.isEnabled() for widget in dialog.advanced.widgets.values())
        assert dialog.server_url.isEnabled()

    def test_accepting_live_settings_applies_languages_and_preserves_engine_values(self):
        window = self.make_window(source_language="en", target_language="zh", asr_model="medium",
                                  wlk={"backend": "faster-whisper", "model_dir": "D:/models/manual",
                                       "custom_alignment_heads": "manual-heads"})
        window.set_running(True)

        def edit_live_languages():
            dialog = next(widget for widget in self.app.topLevelWidgets()
                          if isinstance(widget, SettingsDialog) and widget.isVisible())
            dialog.source_language_combo.setCurrentIndex(dialog.source_language_combo.findData("fr"))
            dialog.target_language_combo.setCurrentIndex(dialog.target_language_combo.findData("en"))
            dialog.mic_language.setCurrentIndex(dialog.mic_language.findData("ja"))
            dialog.model_combo.setCurrentIndex(dialog.model_combo.findData("small"))
            dialog.accept()

        QTimer.singleShot(0, edit_live_languages)
        window.open_settings()
        assert window.settings["source_language"] == "fr"
        assert window.settings["target_language"] == "en"
        assert window.settings["mic_language"] == "ja"
        assert window.settings["asr_model"] == "medium"
        assert window.settings["wlk"]["model_dir"] == "D:/models/manual"
        assert window.settings["wlk"]["custom_alignment_heads"] == "manual-heads"

    def test_accepting_paused_settings_updates_model_and_native_options(self):
        window = self.make_window(asr_model="medium", wlk={"backend": "faster-whisper", "custom_alignment_heads": "old"})
        window.set_running(True, paused=True)

        def edit_paused_pipeline():
            dialog = next(widget for widget in self.app.topLevelWidgets()
                          if isinstance(widget, SettingsDialog) and widget.isVisible())
            dialog.model_combo.setCurrentIndex(dialog.model_combo.findData("small"))
            dialog.backend_combo.setCurrentIndex(dialog.backend_combo.findData("whisper"))
            dialog.advanced.widgets["custom_alignment_heads"].setText("new-heads")
            dialog.accept()

        QTimer.singleShot(0, edit_paused_pipeline)
        window.open_settings()
        assert window.settings["asr_model"] == "small"
        assert window.settings["wlk"]["model_size"] == "small"
        assert window.settings["wlk"]["backend"] == "whisper"
        assert window.settings["wlk"]["custom_alignment_heads"] == "new-heads"

    def test_api_token_uses_password_echo_mode(self):
        from PyQt6.QtWidgets import QLineEdit
        dialog = SettingsDialog({"asr_model": "medium", "wlk": {"api_token": "secret"}},
                                {"output": [], "input": []})
        self.addCleanup(dialog.close)
        token = dialog.advanced.widgets["api_token"]
        assert token.echoMode() == QLineEdit.EchoMode.Password

    def test_toolbar_language_change_emits_full_synced_snapshot_while_running(self):
        window = self.make_window(wlk={"custom_alignment_heads": "manual"})
        snapshots = []
        window.config_changed.connect(snapshots.append)
        window.set_running(True)
        assert window.source_language.isEnabled() and window.target_language.isEnabled()
        assert not window.model_combo.isEnabled() and not window.source_mode.isEnabled()
        window.source_language.setCurrentIndex(window.source_language.findData("fr"))
        assert snapshots
        latest = snapshots[-1]
        assert latest["source_language"] == "fr"
        assert latest["wlk"]["lan"] == "fr"
        assert latest["wlk"]["custom_alignment_heads"] == "manual"
        assert window.settings["source_language"] == "fr"
        assert "正在应用新的听写语言设置" in window.status_label.text()

    def test_language_rollback_api_restores_supported_values_without_emitting(self):
        window = self.make_window()
        emitted = []
        window.config_changed.connect(emitted.append)
        window.set_running(True)
        window.source_language.setCurrentIndex(window.source_language.findData("fr"))
        emitted.clear()
        assert window.set_languages({"source_language": "en", "target_language": "zh"})
        assert window.source_language.currentData() == "en"
        assert window.target_language.currentData() == "zh"
        assert emitted == []
        assert not window.set_languages({"source_language": "zho_Hans", "target_language": "zh"})
        assert window.source_language.currentData() == "en"

    def test_paused_toolbar_can_change_model_and_discard_only_automatic_model_dir(self):
        auto_dir = str((__import__("pathlib").Path(__file__).resolve().parents[1] / "models" / "whisper-medium"))
        window = self.make_window(wlk={"model_dir": auto_dir})
        window.set_running(True, paused=True)
        assert window.model_combo.isEnabled() and window.source_mode.isEnabled()
        window.model_combo.setCurrentIndex(window.model_combo.findData("small"))
        assert window.settings["wlk"]["model_size"] == "small"
        assert window.settings["wlk"]["model_dir"] is None

    def test_transition_locks_paused_model_settings_until_reload_finishes(self):
        window = self.make_window()
        window.set_running(True, paused=True)
        window.set_transitioning(True, "正在加载新模型…")
        assert not window.model_combo.isEnabled()
        assert not window.source_mode.isEnabled()
        assert window.source_language.isEnabled()
        assert window.stop_button.isEnabled()
        window.set_transitioning(False)
        assert window.model_combo.isEnabled()
        assert window.source_mode.isEnabled()

    def test_caption_metadata_shows_translation_direction_when_provided(self):
        window = self.make_window()
        window.update_caption([{"id": "lang-line", "source": "hello", "start": 0, "end": 1,
                               "configured_language": "en", "target_language": "zho_Hans", "speaker": 1}])
        assert "EN → ZHO_HANS" in window.caption_cards["lang-line"].meta_label.text()
        assert "EN → ZHO_HANS" in window.history_items["lang-line"].text()

    def test_transition_disables_pause_but_keeps_stop_available(self):
        window = self.make_window()
        window.set_running(True)
        window.set_transitioning(True, "正在切换模型…")
        assert window.source_language.isEnabled()
        assert window.target_language.isEnabled()
        assert not window.model_combo.isEnabled()
        assert not window.pause_button.isEnabled()
        assert window.stop_button.isEnabled()

    def test_toolbar_tools_signal_and_pipeline_snapshot(self):
        window = self.make_window()
        tools = []
        window.tools_requested.connect(lambda: tools.append(True))
        window.tools_button.click()
        assert tools == [True]
        window.update_pipeline({
            "rows": [{"id": "line-1", "source": "hello", "translation": "你好", "start": 1.2,
                      "end": 2.4, "language": "en", "speaker": 0}],
            "draft": "one two", "translation_draft": "一二", "translation_latency_ms": 380,
        })
        assert "翻译草稿" in window.draft_label.text()
        assert "380 ms" in window.pipeline_metrics_label.text()

    def test_native_metrics_do_not_erase_displayed_captions(self):
        window=self.make_window()
        row={'id':'main:a','source':'Hello','translation':'你好','start':0,'end':1,'speaker':1}
        window.update_caption([row])
        window.update_pipeline({'lines':[{'text':'Hello','speaker':1,'start':'0:00:00.00','end':'0:00:01.00'}],
                                'buffer_transcription':'Next','buffer_translation':'下一句',
                                'remaining_time_transcription_processing':.25,
                                'remaining_time_transcription_policy':.4,'remaining_time_diarization':.7})
        assert window.caption_rows['main:a']['source']=='Hello'
        assert window.caption_cards['main:a'].source_text.text()=='Hello'
        assert '下一句' in window.draft_label.text()
        assert '0.25' in window.pipeline_metrics_label.text()

    def test_caption_history_show_speaker_time_language_and_rename_signal(self):
        window = self.make_window()
        window.update_caption([{"id": "a", "source": "hello", "translation": "你好", "start": 1.25,
                               "end": 2.0, "language": "en", "speaker": 1}])
        card = window.caption_cards["a"]
        assert "说话人 1" in card.meta_label.text()
        assert "1.2s" in card.meta_label.text()
        assert "EN" in card.meta_label.text()
        assert "说话人 1" in window.history_items["a"].text()
        requested = []
        window.speaker_rename_requested.connect(lambda speaker, name: requested.append((speaker, name)))
        window._rename_speaker(1, "主持人")
        assert requested == [(1, "主持人")]
        assert "主持人" in card.meta_label.text()
        assert "主持人" in window.history_items["a"].text()

    def test_export_menu_accepts_vtt_and_json(self):
        window = self.make_window()
        window.update_caption([{"id": "a", "source": "hello", "start": 0, "end": 1}])
        emitted = []
        window.export_scope_requested.connect(lambda path, fmt, scope: emitted.append((path, fmt,scope)))
        with patch("app.export_ui.ExportDialog") as dialog:
            dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted
            dialog.return_value.result_values.return_value=("captions.vtt","vtt","visible")
            window.choose_export_format()
        with patch("app.export_ui.ExportDialog") as dialog:
            dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted
            dialog.return_value.result_values.return_value=("captions.json","native_json","all")
            window.choose_export_format()
        assert emitted == [("captions.vtt", "vtt","visible"), ("captions.json", "native_json","all")]

    def test_export_menu_includes_verbose_and_diarized_json(self):
        window = self.make_window()
        window.update_caption([{"id": "a", "source": "hello", "start": 0, "end": 1}])
        emitted = []
        window.export_scope_requested.connect(lambda path, fmt, scope: emitted.append((path, fmt,scope)))
        with patch("app.export_ui.ExportDialog") as dialog:
            dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted
            dialog.return_value.result_values.return_value=("captions.verbose.json","verbose_json","all")
            window.choose_export_format()
        with patch("app.export_ui.ExportDialog") as dialog:
            dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted
            dialog.return_value.result_values.return_value=("captions.diarized.json","diarized_json","all")
            window.choose_export_format()
        assert emitted == [("captions.verbose.json", "verbose_json","all"), ("captions.diarized.json", "diarized_json","all")]

