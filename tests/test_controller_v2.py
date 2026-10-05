import asyncio
import os
import threading
import time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication
from app.ui import MainWindow
from app.settings import DEFAULTS
from app.controller import Controller
from app.participants import ParticipantRegistry
from app.records import Journal,read_record


def setup():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    return app,window,controller


def test_controller_applies_deltas_without_erasing_old_rows():
    app,window,controller=setup()
    try:
        controller.handle_event({'type':'captions','delta':True,'rows':[{'id':'a','source':'first','start':0,'end':1}]})
        controller.handle_event({'type':'captions','delta':True,'rows':[{'id':'b','source':'second','start':1,'end':2}]})
        assert len(controller.rows)==2 and set(window.caption_rows)=={'a','b'}
        controller.handle_event({'type':'captions','delta':True,'rows':[{'id':'a','source':'revised','start':0,'end':1}]})
        assert len(controller.rows)==2 and window.caption_rows['a']['source']=='revised'
    finally: window.close()


def test_closed_meeting_participant_rename_updates_persistent_record(tmp_path):
    app,window,controller=setup()
    registry=ParticipantRegistry('m')
    row=registry.decorate({'id':'1','source':'hello','start':0,'end':1,'speaker':1,
                          'speaker_namespace':'main:g0:e0','native':{'speaker':1}})
    journal=Journal(tmp_path,{'save_records':True})
    journal.save([row])
    controller.record_path=str(journal.path)
    controller.handle_event({'type':'captions','rows':[row],'participant_state':registry.to_dict()})
    try:
        with patch('app.controller.save_settings'):
            controller.rename_speaker(row['participant_id'],'新名字')
        saved=read_record(journal.path)
        assert saved['rows'][0]['speaker_name']=='新名字'
        assert saved['rows'][0]['native']['speaker']==1
    finally: window.close()


def test_original_view_survives_participant_rename_and_record_reload(monkeypatch):
    app,window,controller=setup()
    registry=ParticipantRegistry('m')
    row=registry.decorate({'id':'1','source':'corrected','source_original':'original','source_corrected':'corrected',
                           'start':0,'end':1,'speaker':1,'speaker_namespace':'main:g0:e0',
                           'native':{'speaker':1,'translation':'original translation'}})
    window.settings['show_original_text']=True
    controller.participants=registry
    controller.rows=[row]
    window.update_caption(controller.display_rows(controller.rows))
    try:
        controller.apply_participants(registry.to_dict())
        assert window.caption_rows['1']['source']=='original'
        controller.rename_speaker(row['participant_id'],'Alice')
        assert window.caption_rows['1']['source']=='original'
        monkeypatch.setattr('app.controller_meeting_tools.read_record',lambda _path:{
            'rows':controller.rows,'participant_state':controller.participants.to_dict(),'native_snapshot':{}})
        controller.load_record('fake-record.json')
        assert window.caption_rows['1']['source']=='original'
        assert window.caption_cards['1'].source_label.text()=='原始听写'
    finally: window.close()


def test_old_rewrite_callback_cannot_update_new_meeting(monkeypatch):
    from PyQt6.QtCore import QObject,pyqtSignal
    class FakeRewrite(QObject):
        completed=pyqtSignal(list)
        failed=pyqtSignal(str)
        cancelled=pyqtSignal(int,int)
        progress=pyqtSignal(int,int)
        def __init__(self,parent=None):
            super().__init__(parent); self.running=False; self.cancel=threading.Event()
        def start(self,rows,settings): self.running=True
    monkeypatch.setattr('app.record_rewrite.RecordRewriteJob',FakeRewrite)
    app,window,controller=setup()
    old={'id':'old','source':'old corrected','source_original':'old original','source_revision':'r1',
         'source_corrected':'old corrected','target_language':'zh','native':{'translation':'old native'}}
    new={'id':'new','source':'new meeting','source_revision':'r2'}
    controller.rows=[old]
    controller.record_path='old-record.json'
    window.settings['show_original_text']=True
    try:
        controller.retranslate_history([old],dict(DEFAULTS))
        job=controller._rewrite_job
        controller._rotate_content_context()
        controller.rows=[new]
        controller.record_path='new-record.json'
        window.update_caption([new])
        job.completed.emit([{**old,'translation':'late result'}])
        assert set(window.caption_rows)=={'new'}
        assert controller.rows[0]['source']=='new meeting'
    finally: window.close()


def test_retranslation_uses_original_display_and_is_revision_bound(monkeypatch):
    from PyQt6.QtCore import QObject,pyqtSignal
    class FakeRewrite(QObject):
        completed=pyqtSignal(list)
        failed=pyqtSignal(str)
        cancelled=pyqtSignal(int,int)
        progress=pyqtSignal(int,int)
        def __init__(self,parent=None):
            super().__init__(parent); self.running=False; self.cancel=threading.Event()
        def start(self,rows,settings): self.running=True
    monkeypatch.setattr('app.record_rewrite.RecordRewriteJob',FakeRewrite)
    app,window,controller=setup()
    row={'id':'1','source':'corrected','source_original':'original','source_corrected':'corrected',
         'source_revision':'r1','glossary_revision':'g1','target_language':'zh',
         'native':{'translation':'original translation'}}
    controller.rows=[row]
    window.settings['show_original_text']=True
    window.update_caption(controller.display_rows(controller.rows))
    controller.server.ensure=lambda settings,ready,failed=None:ready('http://local')
    try:
        controller.retranslate_history([row],dict(DEFAULTS))
        rewritten={**row,'translation':'rewritten','translation_source_revision':'g1'}
        controller._rewrite_job.completed.emit([rewritten])
        assert window.caption_rows['1']['source']=='original'
        assert window.caption_rows['1']['display_source_mode']=='original'
        assert window.caption_rows['1']['translation']=='original translation'
        assert controller.rows[0]['translation']=='rewritten'
    finally: window.close()


def test_rewrite_job_emits_cancelled_progress_instead_of_completed(monkeypatch):
    from app.record_rewrite import RecordRewriteJob
    from PyQt6.QtCore import Qt
    started=threading.Event(); release=threading.Event()
    async def slow_translate(row,settings,cancel):
        started.set()
        await asyncio.to_thread(release.wait,1)
        return {'translation':'done'}
    monkeypatch.setattr('app.record_rewrite.translate_row',slow_translate)
    app=QApplication.instance() or QApplication([])
    job=RecordRewriteJob()
    completed=[]; cancelled=[]; complete_event=threading.Event(); cancel_event=threading.Event()
    job.completed.connect(lambda rows:(completed.extend(rows),complete_event.set()))
    job.cancelled.connect(lambda done,total:(cancelled.append((done,total)),cancel_event.set()),Qt.ConnectionType.DirectConnection)
    rows=[{'id':str(index),'target_language':'zh'} for index in range(3)]
    job.start(rows,dict(DEFAULTS))
    assert started.wait(1)
    job.cancel.set(); release.set()
    assert cancel_event.wait(2)
    assert not complete_event.is_set()
    assert cancelled==[(1,3)]


def test_resume_failure_after_stop_does_not_restore_paused_window():
    app,window,control=setup()
    server=control.server
    class RunningProcess:
        def __init__(self): self.writes=[]; self.properties={}
        def state(self): return QProcess.ProcessState.Running
        def write(self,payload): self.writes.append(payload)
        def setProperty(self,key,value): self.properties[key]=value
    control.process=RunningProcess()
    failures=[]
    callbacks=[]
    server.ensure=lambda settings,ready,failed=None:callbacks.append(failed)
    window.show_error=failures.append
    try:
        control.handle_event({'type':'state','state':'paused'})
        control.toggle_pause()
        assert control.resuming
        window._request_stop()
        assert window.stop_pending and not control.resuming
        callbacks[0]('service failed after stop')
        assert window.stop_pending
        assert not failures
    finally: window.close()


def test_continue_record_reports_corruption_counts_and_ids_without_editing_file(tmp_path,monkeypatch):
    app,window,controller=setup()
    path=tmp_path/'recoverable.json'
    path.write_text('{"header":"bad"}',encoding='utf-8')
    warnings={'corrupted_row_ids':['r-2'],'corrupted_event_ids':['e-4','e-8'],
              'note':'damaged rows remain in original database'}
    monkeypatch.setattr('app.controller_meeting_tools.read_record',lambda _path:{'recovery_warnings':warnings})
    starts=[]; messages=[]
    controller.start=lambda settings:starts.append(settings)
    window.show_error=messages.append
    try:
        before=path.read_bytes()
        controller.continue_record(path)
        assert path.read_bytes()==before
        assert starts and starts[0]['resume_record']==str(path)
        assert 'r-2' in messages[-1] and 'e-4' in messages[-1] and '\u635f\u574f\u6761\u76ee\u4ecd\u4fdd\u7559\u5728\u539f\u8bb0\u5f55\u6570\u636e\u5e93\u4e2d' in messages[-1]
    finally: window.close()


def test_open_record_reports_recovery_warning_ids(monkeypatch):
    app,window,controller=setup()
    messages=[]
    monkeypatch.setattr('app.controller_meeting_tools.read_record',lambda _path:{
        'rows':[],'participant_state':{},'native_snapshot':{},
        'recovery_warnings':{'corrupted_row_ids':['bad-row'],'corrupted_event_ids':[]}})
    window.show_error=messages.append
    try:
        controller.load_record('recoverable.json')
        assert any('bad-row' in message and '\u635f\u574f\u5b57\u5e55ID' in message for message in messages)
    finally: window.close()


def test_old_ai_settings_callback_and_scope_cannot_affect_new_record(monkeypatch):
    from PyQt6.QtCore import QObject,pyqtSignal
    class FakeAI(QObject):
        settings_changed=pyqtSignal(dict)
        def __init__(self,settings,get_rows,get_path,parent=None):
            super().__init__(parent); self.get_rows=get_rows; self.get_path=get_path; self.translation_provider=self
            self.get_record_path=get_path
            self._closing=False; self.enabled=[]; self.shown=False
        def setEnabled(self,value): self.enabled.append(value)
        def setToolTip(self,_value): pass
        def show(self): self.shown=True
        def close(self): self._closing=True
    monkeypatch.setattr('app.ai_ui.AIModelDialog',FakeAI)
    app,window,controller=setup()
    controller.rows=[{'id':'old','source':'old'}]
    controller.record_path='old.json'
    try:
        controller.show_ai()
        dialog=controller._ai_dialog
        assert dialog.get_rows()==[{'id':'old','source':'old'}]
        controller._rotate_content_context()
        controller.rows=[{'id':'new','source':'new'}]
        controller.record_path='new.json'
        emitted=[]
        controller.apply_config=lambda values:emitted.append(values)
        dialog.settings_changed.emit({'llm_model':'late result'})
        assert dialog.get_rows()==[] and dialog.get_record_path() is None
        assert not emitted
    finally: window.close()
