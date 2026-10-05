"""GUI bridge to the isolated local speech process."""
import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QPushButton, QVBoxLayout, QHBoxLayout
from app.dialogs import QMessageBox

from app.records import export_rows, read_record
from app.settings import ROOT, save_settings
from app.server_manager import ServerManager, process_environment
from app.wlk_config import make_config
from app.controller_meeting_tools import MeetingToolsMixin
from app.icons import set_button_icon


class Controller(MeetingToolsMixin,QObject):
    session_finished = pyqtSignal()
    shutdown_finished = pyqtSignal()

    def __init__(self, window, shared_server=None):
        super().__init__(window)
        self.window = window
        self.owns_server = shared_server is None
        self.server = shared_server or ServerManager(self)
        self.children = []
        self.server.changed.connect(lambda text:self.window.set_status(text,'working'))
        self.server.error.connect(self.window.show_error)
        self.server.stopped.connect(self.server_stopped)
        self.starting = False
        self.resuming = False
        self.closing = False
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('PATH', str(ROOT / '.venv/Lib/site-packages/torch/lib') + os.pathsep + os.environ.get('PATH', ''))
        self.process.setProcessEnvironment(process_environment())
        self.server.sessions.append(self.process)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_error_log)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.buffer = b''
        self.rows = []
        self.hidden_ids = set()
        self._content_token = 0
        self.paused = False
        self.failed = False
        self.record_path = None
        self.running_settings = dict(window.settings)
        self.native_snapshot = {}
        self._pending_launch = None
        self.process.started.connect(self.send_start)
        window.start_requested.connect(self.start)
        window.pause_requested.connect(self.toggle_pause)
        window.stop_requested.connect(lambda: self.send_command('stop'))
        window.config_changed.connect(self.apply_config)
        self._translation_request=0
        self._overlay_save_timer=QTimer(self)
        self._overlay_save_timer.setSingleShot(True)
        self._overlay_save_timer.setInterval(350)
        self._overlay_save_timer.timeout.connect(self.flush_overlay_preferences)
        if hasattr(window,'translation_enabled_requested'):
            window.translation_enabled_requested.connect(self.request_translation_enabled)
        if hasattr(window,'overlay_preferences_changed'):
            window.overlay_preferences_changed.connect(self.save_overlay_preferences)
        window.export_requested.connect(self.export)
        if hasattr(window,'export_scope_requested'):
            window.export_scope_requested.connect(self.export)
        window.clear_requested.connect(self.clear_view)
        if hasattr(window,'tools_requested'):
            window.tools_requested.connect(self.show_tools)
        if hasattr(window,'speaker_rename_requested'):
            window.speaker_rename_requested.connect(self.rename_speaker)
        self.saved_button = QPushButton('历史会议')
        set_button_icon(self.saved_button,'history')
        self.saved_button.setToolTip('查看之前保存的会议；活动会议中不会覆盖当前记录，请先结束会议再载入')
        self.saved_button.clicked.connect(self.show_saved_records)
        layout=getattr(window,'utility_layout',window.title_bar.layout())
        layout.insertWidget(max(0,layout.count()-1),self.saved_button)
        self.setup_meeting_tools()

    def _rotate_content_context(self):
        """Invalidate asynchronous work tied to the previous meeting or record."""
        self._content_token += 1
        self._translation_request+=1
        self._set_translation_preparing(False)
        self.window.pipeline_by_source.clear()
        self.window.pipeline_snapshot.clear()
        self.window.applied_routes.clear()
        self.window.applied_route_values.clear()
        self.window._caption_view_end=None
        self.window._refresh_route_summary()
        if hasattr(self.window,'apply_overlay_preferences'):
            self.window.apply_overlay_preferences({'translation_mode':self.window.settings.get('translation_mode','local')})
        rewrite = getattr(self, '_rewrite_job', None)
        if rewrite is not None:
            rewrite.cancel.set()
        self._rewrite_pending = False
        dialog = getattr(self, '_ai_dialog', None)
        if dialog is not None:
            dialog.close()
            self._ai_dialog = None
        return self._content_token

    @property
    def rows(self):
        return sorted(self._row_cache.values(),key=lambda row:(row.get('start',0),row['id']))

    @rows.setter
    def rows(self,values):
        self._row_cache={row['id']:row for row in values}

    @property
    def active(self):
        return self.starting or self.resuming or self.process.state() != QProcess.ProcessState.NotRunning

    @property
    def has_processes(self):
        tools=getattr(self,'_tools_dialog',None)
        job=getattr(tools,'_active_job',None)
        tool_work=bool(tools and (tools._batch_start_pending or (job and job.state()!=QProcess.ProcessState.NotRunning)))
        return self.active or self.text_work_active or tool_work or (self.owns_server and (self.server.active or any(c.has_processes for _,c in self.children)))

    @property
    def text_work_active(self):
        job=getattr(self,'_rewrite_job',None)
        dialog=getattr(self,'_ai_dialog',None)
        thread=getattr(dialog,'_worker_thread',None)
        return bool((job and job.running) or (thread and thread.is_alive()))

    def start(self, settings, audio_file=None, realtime=True):
        if self.active:
            return
        self._rotate_content_context()
        self.buffer = b''
        self.rows = []
        self.hidden_ids.clear()
        self.failed = False
        self.paused = False
        self.record_path = None
        self.native_snapshot = {}
        from app.participants import ParticipantRegistry
        self.participants=ParticipantRegistry()
        self.window.speaker_names.clear()
        self.running_settings = dict(settings)
        self.window.caption_rows.clear()
        from app.participants import ParticipantRegistry
        self.participants=ParticipantRegistry()
        self.window.speaker_names.clear()
        self.window.update_caption([], '')
        self.window.set_elapsed(0)
        self.window.set_level(0)
        self.window.set_running(True)
        self.transition(True)
        self.window.set_status('正在启动本地模型…', 'working')
        save_settings(settings)
        self.starting = True
        def launch(url):
            if not self.starting: return
            self.starting = False
            local_settings={**self.running_settings,'server_url':url}
            self._pending_launch = {'cmd':'start', 'settings':local_settings, 'audio_file':str(audio_file) if audio_file else None, 'realtime':realtime}
            self.process.start(str(ROOT/'.venv/Scripts/python.exe'), ['-u','-m','app.backend'])
            self.process.setProperty('uses_server',True)
        def failed(message):
            self.starting=False
            self.failed=True
            self.window.set_running(False)
            self.session_finished.emit()
            if self.closing:
                if self.owns_server: self.finish_shutdown()
                else: self.shutdown_finished.emit()
        self.server.ensure(settings,launch,failed)
        self.refresh_meeting_menu()

    def send_start(self):
        if self._pending_launch:
            self.process.write((json.dumps(self._pending_launch, ensure_ascii=False)+'\n').encode('utf-8'))
            self._pending_launch = None

    def send_command(self, command):
        if command=='stop':
            self.resuming=False
            self._translation_request+=1
            self._set_translation_preparing(False)
            self.window.apply_overlay_preferences({'translation_mode':self.window.settings.get('translation_mode','local')})
        if command=='stop' and self.starting:
            self.starting=False
            self.window.set_running(False)
            self.session_finished.emit()
            if self.closing: self.server.stop()
            return
        if self.active:
            self.process.write((json.dumps({'cmd':command})+'\n').encode())

    def transition(self,active,message=''):
        if hasattr(self.window,'set_transitioning'):
            self.window.set_transitioning(active,message)
        elif message: self.window.set_status(message,'working')

    def apply_config(self,settings):
        language_keys=('source_language','target_language','mic_language','mic_target_language')
        option_keys=('glossary_enabled','glossary_rules','llm_url','llm_model','llm_api_token',
                     'llm_timeout','llm_context_chars','llm_fallback','translation_mode')
        option_changed=any(settings.get(key)!=self.running_settings.get(key) for key in option_keys)
        changed=any(settings.get(k)!=self.running_settings.get(k) for k in language_keys)
        if self.active and not self.paused and changed:
            try:
                make_config(settings)
            except (ValueError,TypeError) as exc:
                if hasattr(self.window,'set_languages'): self.window.set_languages(self.running_settings,emit=False)
                self.window.show_error(str(exc))
                return
            self.running_settings.update({k:settings[k] for k in language_keys if k in settings})
            if self.process.state()!=QProcess.ProcessState.NotRunning:
                self.process.write((json.dumps({'cmd':'update_languages','settings':self.running_settings},ensure_ascii=False)+'\n').encode('utf-8'))
                self.window.set_status('正在切换语言，已生成的字幕与译文将保留…','working')
        self.window.settings.update(settings)
        self.window._refresh_runtime_summary()
        self.window._refresh_route_summary()
        save_settings(settings)
        if self.active and option_changed:
            self.running_settings.update({key:settings[key] for key in option_keys if key in settings})
            self.send_payload({'cmd':'update_options','settings':settings})
        if hasattr(self.window,'apply_overlay_preferences'):
            self.window.apply_overlay_preferences({'translation_mode':self.window.settings.get('translation_mode','local')})

    def save_overlay_preferences(self,preferences):
        self.window.settings.update({key:value for key,value in preferences.items() if key.startswith('overlay_')})
        self._overlay_save_timer.start()

    def flush_overlay_preferences(self):
        self._overlay_save_timer.stop()
        overlay=getattr(self.window,'subtitle_overlay',None)
        if overlay is not None:
            self.window.settings.update(overlay.preferences())
        save_settings(self.window.settings)

    def request_translation_enabled(self,enabled):
        """Confirm the actual translation pipeline before changing the checkbox."""
        self._translation_request+=1
        self._set_translation_preparing(False)
        token=self._translation_request
        old=self.window.settings.get('translation_mode','local')
        if self.starting or self.resuming or self.window.stop_pending or self.window.transitioning:
            self.window.apply_overlay_preferences({'translation_mode':old})
            self.window.toast('正在切换或结束会议，请稍后再调整翻译')
            return
        desired='local' if enabled else 'off'
        cfg={**self.window._config_snapshot(),'translation_mode':desired}
        try: make_config(cfg)
        except (ValueError,TypeError) as exc:
            self.window.apply_overlay_preferences({'translation_mode':old})
            self.window.show_error(str(exc))
            return
        context=self._content_token
        was_active=self.active
        was_paused=self.paused
        def confirm(url=''):
            if token!=self._translation_request or context!=self._content_token or self.closing: return
            if was_active and (not self.active or self.window.stop_pending or self.window.transitioning or self.paused!=was_paused):
                self.window.apply_overlay_preferences({'translation_mode':old})
                self._set_translation_preparing(False)
                return
            latest={**self.window._config_snapshot(),'translation_mode':desired}
            try: make_config(latest)
            except (ValueError,TypeError) as exc:
                failed(str(exc))
                return
            self.apply_config(latest)
            self._set_translation_preparing(False)
            self.running_settings['translation_mode']=desired
            if self.active:
                self.window.set_status('会议已暂停' if self.paused else '正在聆听', 'paused' if self.paused else 'running')
            self.window.toast('已开启翻译，将从后续语音开始生效' if enabled else '已关闭翻译，继续听写原文')
        def failed(message):
            if token!=self._translation_request or self.closing: return
            self.window.apply_overlay_preferences({'translation_mode':old})
            self._set_translation_preparing(False)
            self.window.show_error('翻译未开启，原文听写继续。请暂停后检查翻译引擎和模型。'+str(message))
        if enabled and old=='off' and self.active and not self.paused:
            self._set_translation_preparing(True)
            self.window.set_status('正在准备翻译模型，听写继续…','working')
            self.server.prepare_translation(cfg,confirm,failed)
        else: confirm()

    def _set_translation_preparing(self,value):
        if hasattr(self.window,'set_translation_preparing'):
            self.window.set_translation_preparing(value)

    def toggle_pause(self):
        if not self.active or self.starting or self.resuming or self.closing or self.window.stop_pending or self.window.transitioning: return
        self._translation_request+=1
        self._set_translation_preparing(False)
        self.window.apply_overlay_preferences({'translation_mode':self.window.settings.get('translation_mode','local')})
        if not self.paused:
            self.transition(True,'正在完成暂停前的字幕与翻译…')
            self.send_command('pause')
            return
        settings=self.window._config_snapshot()
        self.resuming=True
        self.transition(True,'正在应用暂停后的设置…')
        def resumed(url):
            if not self.resuming or self.closing or self.window.stop_pending:
                self.resuming=False
                return
            latest=self.window._config_snapshot()
            try:
                make_config(latest)
            except (ValueError,TypeError) as exc:
                failed(str(exc))
                return
            self.resuming=False
            self.running_settings=dict(latest)
            self.process.setProperty('uses_server',True)
            payload={'cmd':'resume','settings':{**latest,'server_url':url}}
            self.process.write((json.dumps(payload,ensure_ascii=False)+'\n').encode('utf-8'))
        def failed(message):
            if not self.resuming or self.closing or self.window.stop_pending:
                self.resuming=False
                return
            self.resuming=False
            self.transition(False)
            self.window.set_running(True,True)
            self.window.show_error(message)
        self.server.ensure(settings,resumed,failed)

    def read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.write_log(line.decode('utf-8', errors='replace'))
                continue
            self.handle_event(event)

    def handle_event(self, event):
        kind = event.get('type')
        if kind == 'captions':
            if event.get('participant_state'):
                from app.participants import ParticipantRegistry
                self.participants=ParticipantRegistry(state=event['participant_state'])
            if event.get('delta'):
                changed=event.get('rows',[])
                removed=event.get('removed_ids',[])
                for row in changed: self._row_cache[row['id']]=row
                for rid in removed: self._row_cache.pop(rid,None)
                self.window.apply_caption_changes(self.display_rows([row for row in changed if row['id'] not in self.hidden_ids]),removed,
                    None if 'pipelines' in event else event.get('draft',''))
                old_streams=self.native_snapshot.get('streams',{})
                self.native_snapshot.update(event.get('native_snapshot',{}))
                self.native_snapshot['streams']={**old_streams,**event.get('native_snapshot',{}).get('streams',{})}
            else:
                self.rows=event.get('rows',[])
                self.native_snapshot=event.get('native_snapshot',{})
                self.window.update_caption(self.display_rows([r for r in self.rows if r['id'] not in self.hidden_ids]),event.get('draft',''))
            self.window.export_total_count=len(self._row_cache)
            self.window.update_pipeline_metrics(event.get('pipeline',{}), source=event.get('pipeline_source') or event.get('source'), pipelines=event.get('pipelines'))
        elif kind=='pipeline':
            self.window.update_pipeline_metrics(event.get('pipeline',{}), source=event.get('pipeline_source') or event.get('source'), pipelines=event.get('pipelines'))
        elif kind=='save_status':
            self.last_saved_at=event.get('saved_at')
            self.saved_button.setToolTip('最近保存：'+str(self.last_saved_at)+' · '+str(event.get('rows',0))+' 条')
        elif kind in ('audio_gap','audio_backlog','text_backlog'):
            if event.get('message'):
                source={'system':'系统声音','mic':'麦克风'}.get(event.get('source'),'当前音源')
                message=str(event['message'])
                if kind=='audio_gap':
                    message=f'{source}采音出现中断；请暂停后检查设备。'+message
                self.window.set_status(message,'error' if kind=='audio_gap' else 'working')
            elif event.get('seconds'): self.window.pipeline_metrics_label.setText('音频积压约 '+str(event['seconds'])+' 秒')
            elif event.get('count'): self.window.pipeline_metrics_label.setText('待完成文字翻译：'+str(event['count'])+' 条')
        elif kind == 'level':
            self.window.set_level(event['value'],event.get('source'))
        elif kind == 'elapsed':
            self.window.set_elapsed(event['seconds'])
        elif kind == 'status':
            self.window.set_status(event['message'], 'working')
        elif kind == 'state':
            state = event.get('state')
            if state in ('running', 'paused'):
                self.paused = state == 'paused'
                self.process.setProperty('uses_server',not self.paused)
                self.transition(False)
                self.refresh_meeting_menu()
                # A pending stop keeps controls frozen even if a late state arrives.
                pending = self.window.stop_pending
                self.window.set_running(True, self.paused)
                if pending:
                    self.window.stop_pending = True
                    self.window._refresh_controls()
            elif state == 'stopped':
                self.window.set_status('会议已结束，记录已保存' if self.record_path else '会议已结束', 'idle')
        elif kind == 'record':
            self.record_path = event['path']
        elif kind == 'settings_applied':
            if not self.window.stop_pending:
                self.window.set_applied_route(str(event.get('source') or 'main'),str(event.get('language','')),str(event.get('target_language','') or ''))
        elif kind in ('error', 'warning'):
            self.failed = kind == 'error'
            self.window.show_error(event['message'])

    def write_log(self, text):
        log_path = ROOT / 'logs/backend.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(text.rstrip()+'\n')

    def read_error_log(self):
        self.write_log(bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace'))

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.starting=False
            self.resuming=False
            self.failed = True
            self.process.setProperty('uses_server',False)
            self.transition(False)
            self.window.set_running(False)
            self.window.show_error('后台无法启动，请运行修复环境.ps1或查看logs目录')
            self.session_finished.emit()
            if self.closing:
                if self.owns_server: self.finish_shutdown()
                else: self.shutdown_finished.emit()

    def finished(self, exit_code, exit_status):
        self.starting=False
        self.resuming=False
        self._set_translation_preparing(False)
        self.process.setProperty('uses_server',False)
        self.transition(False)
        self.read_output()
        self.read_error_log()
        self.window.set_running(False)
        self.refresh_meeting_menu()
        self.window.set_level(0)
        if exit_code and not self.failed:
            self.window.show_error('听写已停止：后台意外退出。请检查模型与设备后重新开始；已保存文字可在“历史会议”中查看。')
        self.session_finished.emit()
        if self.closing:
            self.finish_shutdown()

    def rename_speaker(self,speaker,name):
        return MeetingToolsMixin.rename_speaker(self,speaker,name)

    def show_tools(self):
        from app.tools_ui import ToolsDialog
        if getattr(self,'_tools_dialog',None) is None:
            self._tools_dialog=ToolsDialog(self)
        dialog=self._tools_dialog
        dialog.tabs.setCurrentIndex(0)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def request_shutdown(self):
        self.closing=True
        self._translation_request+=1
        self._set_translation_preparing(False)
        self.flush_overlay_preferences()
        if getattr(self,'_tools_dialog',None): self._tools_dialog.close()
        if getattr(self,'_rewrite_job',None): self._rewrite_job.cancel.set()
        if getattr(self,'_ai_dialog',None): self._ai_dialog.close()
        if self.owns_server:
            for window,child in self.children:
                window.close()
        if self.active: self.send_command('stop')
        else: self.finish_shutdown()

    def finish_shutdown(self):
        if any(child.has_processes for _,child in self.children) or self.text_work_active:
            QTimer.singleShot(100,self.finish_shutdown)
        elif self.owns_server: self.server.stop()
        else: self.shutdown_finished.emit()

    def server_stopped(self):
        if self.closing and not self.active: self.shutdown_finished.emit()

    def new_window(self):
        from copy import deepcopy
        from main import AppWindow
        window=AppWindow(deepcopy(self.window._config_snapshot()),self.window.devices)
        child=Controller(window,shared_server=self.server)
        window.background_button.hide()
        window.background_button.setEnabled(False)
        window.background_button.setToolTip('独立会议窗暂不支持后台运行；可以使用独立字幕窗')
        window.controller=child
        window.closing=False
        child.shutdown_finished.connect(lambda:window.close() if window.closing else None)
        self.children.append((window,child))
        window.setWindowTitle('听译 · 独立会议')
        window.show()
        return window

    def clear_view(self):
        self.hidden_ids.update(r['id'] for r in self.rows)

    def export(self, path, format, scope='visible'):
        try:
            if scope not in ('visible','all'):
                raise ValueError('请选择本次显示范围或整场会议')
            if format in ('native_json','verbose_json','diarized_json') and scope!='all' and self.hidden_ids:
                raise ValueError('原始JSON含完整多路快照，请在导出窗口选择整场会议。')
            rows=self.rows if scope=='all' else [row for row in self.rows if row['id'] not in self.hidden_ids]
            if not rows:
                raise ValueError('所选范围没有可导出的字幕')
            export_rows(rows, path, format,snapshot=self.native_snapshot,
                        source_mode='original' if self.window.settings.get('show_original_text') else 'corrected')
            self.window.toast('已导出到 '+str(path))
        except (OSError, ValueError) as exc:
            self.window.show_error('导出失败：'+str(exc))

    def show_saved_records(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle('历史会议')
        dialog.resize(650, 450)
        from app.appearance import watch_theme
        watch_theme(dialog)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('选择会议可恢复字幕查看、复制及导出；文件保存在 records 文件夹'))
        listing = QListWidget()
        paths = sorted((ROOT / 'records').glob('*.json'), reverse=True)
        for path in paths:
            listing.addItem(path.stem)
        layout.addWidget(listing)
        actions = QHBoxLayout()
        open_button = QPushButton('查看会议')

        def open_record():
            index = listing.currentRow()
            if index < 0:
                return
            if self.active:
                self.window.toast('请先结束当前会议，再查看已保存会议')
                return
            try:
                self.load_record(paths[index])
                dialog.accept()
            except (OSError, ValueError, KeyError) as exc:
                QMessageBox.warning(dialog, '读取失败', str(exc))

        open_button.clicked.connect(open_record)
        listing.itemDoubleClicked.connect(lambda _:open_record())
        actions.addWidget(open_button)
        continue_button=QPushButton('接续本次会议')
        def resume_selected():
            index=listing.currentRow()
            if index>=0:
                self.continue_record(paths[index]); dialog.accept()
        continue_button.clicked.connect(resume_selected)
        actions.addWidget(continue_button)
        close_button = QPushButton('关闭')
        close_button.clicked.connect(dialog.reject)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        dialog.exec()
