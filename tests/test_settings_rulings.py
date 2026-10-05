import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from app.config_ui import AdvancedConfigPanel
from app.language_picker import LanguagePicker, display_label
from app.ui import SettingsDialog


_APP = QApplication.instance() or QApplication([])


def _app():
    return _APP


def test_live_session_locks_recording_and_translation_provider_but_keeps_language_editable():
    _app()
    dialog = SettingsDialog(
        {"save_records": True, "translation_provider": "lmstudio", "llm_model": "qwen-local"},
        {"output": [], "input": []}, session_active=True,
    )
    try:
        assert not dialog.save_records.isEnabled()
        assert dialog.save_records.isChecked()
        assert "暂停后修改" in dialog.save_records.toolTip()
        assert not dialog.translation_provider.isEnabled()
        assert dialog.translation_provider.currentData() == "lmstudio"
        assert "qwen-local" in dialog.translation_model_status.text()
        assert "翻译已关闭" not in dialog.translation_model_status.text()
        assert dialog.source_language_combo.isEnabled()
        values = dialog.values()
        assert values["translation_provider"] == "lmstudio"
        assert values["translation_mode"] == "local"
    finally:
        dialog.close()


def test_language_controls_follow_main_audio_mode_and_preserve_inactive_mic_value():
    _app()
    mic_only = SettingsDialog(
        {"source_mode": "mic", "source_language": "en", "mic_language": "ar", "separate_sources": True},
        {"output": [], "input": []},
    )
    try:
        assert mic_only.primary_language_label.text() == "麦克风听写语言"
        assert mic_only.source_language_combo.currentData() == "en"
        assert not mic_only.mic_language.isEnabled()
        assert not mic_only.mic_target_language.isEnabled()
        assert mic_only.values()["mic_language"] == "ar"
    finally:
        mic_only.close()

    both = SettingsDialog(
        {"source_mode": "both", "separate_sources": True}, {"output": [], "input": []},
    )
    try:
        assert both.primary_language_label.text() == "主音源听写语言"
        assert both.mic_language.isEnabled()
        both.separate_sources.setChecked(False)
        assert not both.mic_language.isEnabled()
    finally:
        both.close()


def test_missing_selected_device_stays_selected_and_is_marked_until_user_changes_it():
    _app()
    dialog = SettingsDialog(
        {"mic_device": "USB Mic"}, {"output": [], "input": ["Other Mic"]},
    )
    try:
        index = dialog.mic_device.findData("USB Mic")
        assert index >= 0
        assert "未连接" in dialog.mic_device.itemText(index)
        dialog._apply_device_candidates({"output": [], "input": ["New Mic"]})
        assert dialog.mic_device.currentData() == "USB Mic"
        assert dialog.mic_device.findData("New Mic") >= 0
    finally:
        dialog.close()


def test_device_refresh_reads_candidates_asynchronously_and_keeps_current_selection():
    _app()
    dialog = SettingsDialog({"mic_device": "USB Mic"}, {"output": [], "input": ["USB Mic"]})
    try:
        with patch("app.audio.list_devices", return_value={"output": ["Speakers"], "input": ["New Mic"]}):
            dialog.refresh_devices()
            deadline = time.monotonic() + 2
            while dialog._device_refresh_thread is not None and time.monotonic() < deadline:
                _app().processEvents()
                time.sleep(0.005)
        assert dialog._device_refresh_thread is None
        assert dialog.mic_device.currentData() == "USB Mic"
        assert "未连接" in dialog.mic_device.currentText()
        assert dialog.mic_device.findData("New Mic") >= 0
    finally:
        dialog.close()


def test_advanced_search_filters_visibility_without_dropping_values_or_fields():
    _app()
    schema = [
        {"name": "lan", "label": "识别语言", "group": "语言", "type": "str", "default": "en"},
        {"name": "font_size", "label": "字体大小", "group": "外观", "type": "int", "default": 24},
    ]
    panel = AdvancedConfigPanel(schema, {"lan": "ar", "font_size": 31})
    try:
        panel.show()
        _app().processEvents()
        panel.search_edit.setText("识别语言")
        assert not panel.widgets["lan"].isHidden()
        assert panel.widgets["font_size"].isHidden()
        assert panel.values() == {"lan": "ar", "font_size": 31}
        panel.search_edit.clear()
        assert not panel.widgets["font_size"].isHidden()
    finally:
        panel.close()


def test_language_short_label_disambiguates_chinese_script_codes_while_popup_keeps_full_choices():
    _app()
    assert display_label("zh-Hans") != display_label("zh-Hant")
    picker = LanguagePicker([("中文（简体）", "zh-Hans"), ("中文（繁體）", "zh-Hant")], "zh-Hans")
    try:
        assert picker.currentData() == "zh-Hans"
        assert picker.lineEdit().text() == "简体中文"
        assert "zh-Hans" in picker.itemText(picker.findData("zh-Hans"))
        assert "zh-Hant" in picker.itemText(picker.findData("zh-Hant"))
        assert "zh-Hans" in picker.toolTip()
    finally:
        picker.close()

def test_unchanged_settings_keep_language_codes_and_never_save_display_labels():
    dialog = SettingsDialog({'source_language':'en','target_language':'zh','wlk':{}},{'output':[],'input':[]})
    try:
        values=dialog.values()
        assert values['source_language']=='en'
        assert values['target_language']=='zh'
        assert values['wlk']['lan']=='en'
        assert values['wlk']['target_language']=='zh'
    finally: dialog.close()

def test_replaced_advanced_language_field_keeps_code_and_search_visibility():
    panel=AdvancedConfigPanel([{'name':'lan','label':'听写语言','group':'语言','type':'str','choices':['en','ar'],'default':'en'}],{})
    picker=LanguagePicker([('英语','en'),('阿拉伯语','ar')],'en')
    try:
        panel.replace_field('lan',picker)
        assert panel.values()['lan']=='en'
        panel.search_edit.setText('not-matched')
        assert picker.isHidden()
        picker.commit_code('ar')
        panel.search_edit.clear()
        assert not picker.isHidden()
        assert panel.values()['lan']=='ar'
    finally: panel.close()

def test_arabic_script_choices_have_different_compact_labels():
    assert display_label('arb_Arab')!=display_label('arb_Latn')
