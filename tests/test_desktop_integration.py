import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from app.settings import DEFAULTS
from app.ui import MainWindow
from app.controller import Controller


def test_translation_enable_waits_for_model_and_keeps_existing_caption(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow({**DEFAULTS,'translation_mode':'off'},{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.controller.save_settings',lambda value:None)
    pending=[]
    monkeypatch.setattr(controller.server,'prepare_translation',lambda settings,ready,failed:pending.append((ready,failed)),raising=False)
    from PyQt6.QtCore import QProcess
    monkeypatch.setattr(controller.process,'state',lambda:QProcess.ProcessState.Running)
    monkeypatch.setattr(controller,'send_payload',lambda payload:None)
    row={'id':'1','start':0,'end':1,'source':'hello','translation':'','speaker':'1'}
    window.update_caption([row])
    controller.request_translation_enabled(True)
    assert pending and window.settings['translation_mode']=='off'
    assert window.caption_rows['1']['source']=='hello'
    pending[0][0]('http://127.0.0.1:8765')
    assert window.settings['translation_mode']=='local'
    assert controller.running_settings['translation_mode']=='local'
    controller.request_translation_enabled(False)
    assert window.settings['translation_mode']=='off'
    assert window.caption_rows['1']['source']=='hello'
    window.close()


def test_translation_failure_restores_confirmed_state(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow({**DEFAULTS,'translation_mode':'off'},{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.controller.save_settings',lambda value:None)
    errors=[]
    monkeypatch.setattr(window,'show_error',errors.append)
    monkeypatch.setattr(controller.server,'prepare_translation',lambda cfg,ready,failed:failed('模型未安装'),raising=False)
    from PyQt6.QtCore import QProcess
    monkeypatch.setattr(controller.process,'state',lambda:QProcess.ProcessState.Running)
    controller.request_translation_enabled(True)
    assert window.settings['translation_mode']=='off'
    assert errors and '模型未安装' in errors[0] and '听写继续' in errors[0]
    assert not window.subtitle_overlay._translation_preparing
    window.close()


def test_translation_prepare_from_old_meeting_cannot_modify_new_context(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow({**DEFAULTS,'translation_mode':'off'},{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.controller.save_settings',lambda value:None)
    from PyQt6.QtCore import QProcess
    monkeypatch.setattr(controller.process,'state',lambda:QProcess.ProcessState.Running)
    pending=[]
    monkeypatch.setattr(controller.server,'prepare_translation',lambda cfg,ready,failed:pending.append(ready),raising=False)
    controller.request_translation_enabled(True)
    controller._rotate_content_context()
    window.set_languages({'source_language':'zh','target_language':'en'},emit=False)
    pending[0]('http://localhost')
    assert window.settings['translation_mode']=='off'
    assert window.source_language.currentData()=='zh'
    assert window.target_language.currentData()=='en'
    window.close()


def test_translation_can_be_enabled_while_paused_and_invalid_auto_is_explained(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow({**DEFAULTS,'translation_mode':'off'},{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.controller.save_settings',lambda value:None)
    from PyQt6.QtCore import QProcess
    monkeypatch.setattr(controller.process,'state',lambda:QProcess.ProcessState.Running)
    monkeypatch.setattr(controller,'send_payload',lambda payload:None)
    controller.paused=True
    window.set_running(True,paused=True)
    controller.request_translation_enabled(True)
    assert window.settings['translation_mode']=='local'
    controller.request_translation_enabled(False)
    window.set_languages({'source_language':'auto'},emit=False)
    errors=[]
    monkeypatch.setattr(window,'show_error',errors.append)
    controller.request_translation_enabled(True)
    assert window.settings['translation_mode']=='off'
    assert errors and '请选择讲话语言' in errors[0]
    window.close()


def test_background_and_overlay_close_restore_without_tray(monkeypatch):
    from app.background import BackgroundManager
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    manager=BackgroundManager(window,controller,tray_available=False)
    window.show()
    manager.hide_main()
    assert not window.isVisible() and window.subtitle_overlay.isVisible()
    window.subtitle_overlay.close()
    app.processEvents()
    assert window.isVisible()
    manager.dispose()
    window.close()


def test_starting_model_disables_pause_in_both_windows(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.controller.save_settings',lambda value:None)
    monkeypatch.setattr(controller.server,'ensure',lambda cfg,ready,failed:None)
    controller.start(window._config_snapshot())
    assert window.transitioning
    assert not window.pause_button.isEnabled()
    assert not window.subtitle_overlay.pause_button.isEnabled()
    assert not window.subtitle_overlay.translation_toggle.isEnabled()
    controller.starting=False
    window.set_running(False)
    window.close()


def test_idle_close_flushes_subtitle_position_without_waiting_for_debounce(monkeypatch):
    from main import AppWindow
    app=QApplication.instance() or QApplication([])
    window=AppWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    window.controller=controller
    window.closing=False
    saved=[]
    monkeypatch.setattr('app.controller.save_settings',lambda value:saved.append(dict(value)))
    window.subtitle_overlay.show()
    window.subtitle_overlay.move(41,52)
    assert controller._overlay_save_timer.isActive()
    window.close()
    assert saved and saved[-1]['overlay_x']==41 and saved[-1]['overlay_y']==52
    assert not controller._overlay_save_timer.isActive()
