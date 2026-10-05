import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QDialog
from app.ui import MainWindow,SettingsDialog
from app.settings import DEFAULTS
from app.appearance import current_theme,set_theme
from app.theme import style_for

APP=QApplication.instance() or QApplication([])

def window():
    return MainWindow(deepcopy(DEFAULTS),{'output':[],'input':[]})

def test_preview_and_cancel_theme_preserve_running_session_and_custom_subtitle_colors():
    w=window()
    try:
        w.set_running(True)
        w.update_caption([{'id':'a','source':'hello','translation':'你好'}])
        before=deepcopy(w.subtitle_overlay.preferences())
        w.set_appearance_theme('sky',commit=False)
        assert current_theme()=='sky'
        assert w.styleSheet()==style_for('sky')
        assert w.settings['appearance_theme']=='dark'
        assert w.caption_rows['a']['translation']=='你好'
        assert w.subtitle_overlay.preferences()==before
        w.set_appearance_theme('dark',commit=False)
        assert w.running and current_theme()=='dark'
    finally: w.close(); w.deleteLater()

def test_settings_cancel_rolls_back_preview_without_config_submission():
    w=window(); emitted=[]
    w.config_changed.connect(emitted.append)
    try:
        def preview():
            d=next(x for x in APP.topLevelWidgets() if isinstance(x,SettingsDialog) and x.isVisible())
            d.appearance_combo.setCurrentIndex(d.appearance_combo.findData('spring'))
            assert current_theme()=='spring'
            d.reject()
        QTimer.singleShot(0,preview)
        w.open_settings()
        assert current_theme()=='dark'
        assert not emitted
        assert w.settings['appearance_theme']=='dark'
    finally: w.close(); w.deleteLater()

def test_live_settings_save_commits_only_ui_theme_and_keeps_model_locked():
    w=window(); emitted=[]
    w.config_changed.connect(emitted.append)
    try:
        w.set_running(True)
        old_model=w.settings['asr_model']
        def save():
            d=next(x for x in APP.topLevelWidgets() if isinstance(x,SettingsDialog) and x.isVisible())
            assert d.appearance_combo.isEnabled() and not d.model_combo.isEnabled()
            d.appearance_combo.setCurrentIndex(d.appearance_combo.findData('sky'))
            d.accept()
        QTimer.singleShot(0,save)
        w.open_settings()
        assert current_theme()=='sky'
        assert w.settings['appearance_theme']=='sky'
        assert emitted[-1]['appearance_theme']=='sky'
        assert w.settings['asr_model']==old_model
        assert w.running
    finally: w.close(); w.deleteLater(); set_theme('dark',commit=True)

def test_open_export_dialog_updates_when_theme_is_previewed():
    from app.export_ui import ExportDialog
    w=window(); d=ExportDialog(1,1,w)
    try:
        w.set_appearance_theme('spring',commit=False)
        assert d.styleSheet()==style_for('spring')
        assert d.format_combo.currentData()=='txt'
    finally: d.close(); d.deleteLater(); w.close(); w.deleteLater(); set_theme('dark',commit=True)

def test_theme_choice_persists_and_legacy_settings_keep_dark(tmp_path,monkeypatch):
    import app.settings as settings
    monkeypatch.setattr(settings,'DATA',tmp_path)
    assert settings.load_settings()['appearance_theme']=='dark'
    settings.save_settings({**deepcopy(DEFAULTS),'appearance_theme':'spring'})
    assert settings.load_settings()['appearance_theme']=='spring'
