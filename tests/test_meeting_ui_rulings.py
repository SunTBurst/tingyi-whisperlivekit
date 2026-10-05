import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from app.ui import MainWindow, CaptionCard
from app.controller import Controller
from app.participants import ParticipantRegistry

APP = QApplication.instance() or QApplication([])

def make_window(**extra):
    return MainWindow({'source_mode':'both', 'separate_sources':True,
        'source_language':'en', 'target_language':'zh', 'mic_language':'zh',
        'mic_target_language':'en', 'asr_model':'small', 'translation_mode':'off',
        'wlk':{}, **extra}, {'output':[], 'input':[]})

def test_initial_empty_navigation_and_guide():
    w=make_window()
    try:
        assert not w.history_prev_button.isEnabled()
        assert not w.history_next_button.isEnabled()
        assert '开始' in w.empty_caption_label.text()
        assert w.history_panel.isHidden()
        w.open_history()
        assert not w.history_panel.isHidden()
    finally: w.close(); w.deleteLater()

def test_source_levels_and_directions_do_not_overwrite_each_other():
    w=make_window()
    try:
        assert '英语' in w.system_route_button.text()
        assert '麦克风' in w.mic_route_button.text()
        w.set_level(.7, 'system'); w.set_level(.2, 'mic')
        assert w.level_bar.value()==70
        assert w.mic_level_bar.value()==20
        w.swap_languages()
        assert w.settings['mic_language']=='zh'
        assert w.settings['mic_target_language']=='en'
    finally: w.close(); w.deleteLater()

def test_applied_source_routes_are_confirmed_independently():
    w=make_window(translation_mode='local')
    try:
        w.set_running(True)
        w.set_applied_route('system','en','zh')
        assert '已生效' in w.system_route_button.text()
        assert '待应用' in w.mic_route_button.text()
        w.set_applied_route('mic','zh','en')
        assert '已生效' in w.mic_route_button.text()
        assert '系统' in w.status_label.text() and '麦克风' in w.status_label.text()
    finally: w.close(); w.deleteLater()

def test_translation_off_route_does_not_claim_target_and_waits_for_backend_ack():
    w=make_window(translation_mode='local')
    try:
        w.set_running(True)
        w.set_applied_route('system','en','zh')
        w.apply_overlay_preferences({'translation_mode':'off'})
        w._refresh_route_summary()
        assert '仅听写' in w.system_route_button.text()
        assert '待应用' in w.system_route_button.text()
        assert '→ 中文' not in w.system_route_button.text()
        w.set_applied_route('system','en','')
        assert '仅听写' in w.system_route_button.text()
        assert '已生效' in w.system_route_button.text()
    finally: w.close(); w.deleteLater()

def test_overlay_uses_matching_source_draft():
    w=make_window()
    try:
        w.update_caption([{'id':'s','source':'system sentence','audio_source':'system','start':1}])
        w.update_pipeline_metrics({'draft':'system draft'}, source='system')
        w.update_pipeline_metrics({'draft':'microphone draft'}, source='mic')
        assert 'microphone draft' in w.draft_label.text()
        assert 'system draft' in w.subtitle_overlay.draft_label.text()
        assert 'microphone draft' not in w.subtitle_overlay.draft_label.text()
        assert '麦克风' in w.draft_label.text()
    finally: w.close(); w.deleteLater()

def test_dual_clear_removes_both_source_drafts_without_deleting_archive():
    from PyQt6.QtWidgets import QMessageBox
    w=make_window()
    try:
        w.update_caption([{'id':'s','source':'system sentence','audio_source':'system','start':1}])
        w.update_pipeline_metrics({'draft':'system draft'},source='system')
        w.update_pipeline_metrics({'draft':'mic draft'},source='mic')
        with patch('app.ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.confirm_clear()
        assert not w.draft_label.text()
        assert not w.subtitle_overlay.draft_label.text()
        assert not w.pipeline_by_source
    finally: w.close(); w.deleteLater()

def test_idle_empty_manual_save_does_not_create_record(tmp_path):
    w=make_window()
    with patch('app.controller.save_settings'), patch('app.controller_meeting_tools.ROOT', tmp_path):
        c=Controller(w)
        try:
            c.manual_save()
            assert not (tmp_path/'records').exists()
            assert c.record_path is None
            assert '没有' in w.toast_label.text()
        finally: w.close(); w.deleteLater()

def test_export_visible_vs_all_and_native_snapshot_scope(tmp_path):
    w=make_window()
    with patch('app.controller.save_settings'):
        c=Controller(w)
        try:
            c.rows=[{'id':'old','source':'old text','start':0,'end':1}, {'id':'new','source':'new text','start':2,'end':3}]
            c.hidden_ids={'old'}
            c.export(str(tmp_path/'visible.txt'),'txt','visible')
            c.export(str(tmp_path/'all.txt'),'txt','all')
            assert 'old text' not in (tmp_path/'visible.txt').read_text(encoding='utf-8')
            assert 'old text' in (tmp_path/'all.txt').read_text(encoding='utf-8')
            c.export(str(tmp_path/'native.json'),'native_json','visible')
            assert not (tmp_path/'native.json').exists()
        finally: w.close(); w.deleteLater()

def test_new_mic_identity_never_assumes_self_and_existing_name_survives():
    registry=ParticipantRegistry()
    row=registry.decorate({'speaker':1,'audio_source':'mic','speaker_namespace':'mic:1'})
    assert '我' not in row['participant_name']
    assert row['participant_pending']
    registry.rename(row['participant_id'],'我')
    assert registry.decorate(row)['participant_name']=='我'

def test_caption_cards_fit_text_without_reserved_empty_height():
    w=make_window(source_mode='system')
    try:
        w.resize(1024,768); w.show()
        w.update_caption([{'id':'a','source':'A short sentence.','translation':'一句短句。','start':0,'end':1},
                          {'id':'b','source':'Another short sentence.','translation':'另一句短句。','start':1,'end':2}])
        APP.processEvents()
        card=w.caption_cards['b']
        natural=card.layout().heightForWidth(card.width())
        assert card.height()<=natural+20, (card.height(),natural)
    finally: w.close(); w.deleteLater()
