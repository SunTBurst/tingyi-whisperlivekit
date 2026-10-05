import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QProcess, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from app.ui import MainWindow
from app.controller import Controller
from app.settings import DEFAULTS


class Server(QObject):
    changed=pyqtSignal(str)
    error=pyqtSignal(str)
    stopped=pyqtSignal()
    def __init__(self): super().__init__(); self.sessions=[]; self.active=True; self.url='http://local'; self.calls=[]
    def ensure(self,settings,ready,failed=None): self.calls.append(settings); ready(self.url)
    def stop(self): self.active=False; self.stopped.emit()


class Process:
    def __init__(self): self.writes=[]; self.props={}
    def state(self): return QProcess.ProcessState.Running
    def write(self,raw): self.writes.append(json.loads(raw))
    def setProperty(self,key,value): self.props[key]=value


def setup_controller():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'input':[],'output':[]})
    server=Server()
    control=Controller(window,server)
    control.process=Process()
    control.running_settings=dict(DEFAULTS)
    window.set_running(True)
    return app,window,control,server


def test_live_language_change_uses_control_pipe_without_starting_another_meeting():
    app,window,control,server=setup_controller()
    try:
        control.apply_config({**DEFAULTS,'source_language':'zh','target_language':'en'})
        assert control.process.writes[-1]['cmd']=='update_languages'
        assert control.process.writes[-1]['settings']['source_language']=='zh'
        assert server.calls==[]
    finally: window.close()


def test_paused_resume_applies_model_and_preserves_existing_rows():
    app,window,control,server=setup_controller()
    try:
        control.rows=[{'id':'old','source':'Already heard','translation':'已听到','start':0,'end':1}]
        control.handle_event({'type':'state','state':'paused'})
        window.settings.update(asr_model='small')
        window.model_combo.setCurrentIndex(window.model_combo.findData('small'))
        control.toggle_pause()
        assert server.calls[-1]['asr_model']=='small'
        assert control.process.writes[-1]['cmd']=='resume'
        assert control.process.writes[-1]['settings']['asr_model']=='small'
        assert control.rows[0]['source']=='Already heard'
    finally: window.close()


def test_language_changed_during_paused_model_loading_uses_latest_choice():
    app,window,control,server=setup_controller()
    callbacks=[]
    server.ensure=lambda settings,ready,failed=None:callbacks.append(ready)
    try:
        control.handle_event({'type':'state','state':'paused'})
        control.toggle_pause()
        window.set_languages({'source_language':'ar','target_language':'en'},emit=True)
        callbacks[0]('http://local')
        payload=control.process.writes[-1]
        assert payload['cmd']=='resume'
        assert payload['settings']['source_language']=='ar'
        assert payload['settings']['target_language']=='en'
    finally: window.close()


def test_language_programmatic_selection_survives_model_change_before_resume():
    app,window,control,server=setup_controller()
    try:
        control.handle_event({'type':'state','state':'running'})
        assert window.set_languages({'source_language':'zh','target_language':'en'},emit=True)
        assert window._config_snapshot()['source_language']=='zh'
        control.handle_event({'type':'state','state':'paused'})
        window.model_combo.setCurrentIndex(window.model_combo.findData('medium'))
        window.source_language.search_edit.setText('no matching language')
        assert window.source_language.currentData()=='zh'
        assert window.set_languages({'source_language':'en','target_language':'zh'},emit=True)
        assert window.source_language.currentData()=='en'
        assert window._config_snapshot()['source_language']=='en'
        control.toggle_pause()
        assert server.calls[-1]['source_language']=='en'
        assert control.process.writes[-1]['settings']['source_language']=='en'
        assert control.process.writes[-1]['settings']['wlk']['lan']=='en'
    finally: window.close()
