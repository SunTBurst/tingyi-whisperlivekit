"""Desktop-only glossary, participant, recovery and optional meeting AI flows."""
from pathlib import Path
import json
from datetime import datetime

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtWidgets import QPushButton,QMenu

from app.participants import ParticipantRegistry
from app.settings import ROOT,save_settings
from app.records import read_record,update_record,Journal
from app.appearance import watch_theme


class MeetingToolsMixin:
    def setup_meeting_tools(self):
        self.participants=ParticipantRegistry()
        self.last_saved_at=None
        existing=getattr(self.window,'tools_button',None)
        self.meeting_button=existing or QPushButton('会议工具')
        self.meeting_button.setText('会议工具')
        self.meeting_menu=QMenu(self.meeting_button)
        watch_theme(self.meeting_menu)
        self.meeting_menu.addAction('常用词库 / 模板导入导出',self.show_glossary)
        self.meeting_menu.addAction('重新应用当前词库并更新译文',self.reprocess_glossary)
        self.meeting_menu.addAction('取消历史文字重译',self.cancel_history_rewrite)
        self.original_view_action=self.meeting_menu.addAction('显示 / 导出原始听写（保留纠错版）')
        self.original_view_action.setCheckable(True)
        self.original_view_action.setChecked(bool(self.window.settings.get('show_original_text',False)))
        self.original_view_action.toggled.connect(self.set_original_view)
        self.meeting_menu.addAction('本次会议参会者 / 名称关联',self.show_participants)
        self.meeting_menu.addAction('会议 AI：问答 / 摘要 / 翻译',self.show_ai)
        self.meeting_menu.addAction('手动保存当前会议',self.manual_save)
        self.meeting_menu.addAction('查看未正常结束的会议',self.show_recovery)
        self.long_mode_action=self.meeting_menu.addAction('长会议模式：增量保存与分页显示')
        self.long_mode_action.setCheckable(True)
        self.long_mode_action.setChecked(bool(self.window.settings.get('long_meeting_mode',True)))
        self.long_mode_action.toggled.connect(self.set_long_mode)
        self.meeting_button.setToolTip('打开完整工具箱。词库、参会者、会议问答、记录与模型管理都在这里，无需逐项加载。')
        if existing is None:
            self.meeting_button.clicked.connect(self.show_tools)
            layout=getattr(self.window,'utility_layout',self.window.title_bar.layout())
            layout.insertWidget(max(0,layout.count()-1),self.meeting_button)
        self.refresh_meeting_menu()

    def refresh_meeting_menu(self):
        if hasattr(self,'long_mode_action'):
            self.long_mode_action.setEnabled(not self.active or self.paused)

    def send_payload(self,payload):
        if self.process.state()!=QProcess.ProcessState.NotRunning:
            self.process.write((json.dumps(payload,ensure_ascii=False)+'\n').encode('utf-8'))

    def cancel_history_rewrite(self):
        job=getattr(self,'_rewrite_job',None)
        if job is not None and (job.running or getattr(self,'_rewrite_pending',False)):
            job.cancel.set()

    def display_rows(self,rows):
        if not self.window.settings.get('show_original_text'): return rows
        return [{**row,'source':row.get('source_original',row['source']),
                 'translation':row.get('native',{}).get('translation','') if row.get('source_original') is not None else row.get('translation',''),
                 'translation_pending':False,'translation_stale':False,'translation_error':'',
                 'display_source_mode':'original'} for row in rows]

    def set_original_view(self,enabled):
        self.window.settings['show_original_text']=bool(enabled)
        save_settings(self.window.settings)
        self.window.update_caption(self.display_rows([row for row in self.rows if row['id'] not in self.hidden_ids]))

    def set_long_mode(self,enabled):
        cfg={**self.window._config_snapshot(),'long_meeting_mode':bool(enabled)}
        self.apply_config(cfg)
        self.window.toast('长会议模式将在开始或暂停后继续时应用')

    def show_glossary(self):
        from app.glossary_ui import GlossaryDialog
        dialog=GlossaryDialog(self.window.settings,self.window)
        if dialog.exec():
            values=dialog.values()
            self.apply_config({**self.window._config_snapshot(),**values})
            self.window.toast('词库用于后续新字幕；历史内容可主动重新应用')

    def reprocess_glossary(self):
        cfg=self.window._config_snapshot()
        if self.active:
            self.send_payload({'cmd':'reprocess_glossary','glossary_enabled':cfg.get('glossary_enabled',False),
                               'glossary_rules':cfg.get('glossary_rules',[])})
        else:
            from app.glossary import Glossary
            glossary=Glossary(cfg.get('glossary_rules',[]),enabled=cfg.get('glossary_enabled',False))
            from app.session_postprocess import source_revision
            revised=[]
            for row in self.rows:
                updated=glossary.decorate(row)
                updated['source_revision']=source_revision(updated,cfg)
                revised.append(updated)
            self.rows=revised
            self.window.update_caption(self.display_rows([row for row in self.rows if row['id'] not in self.hidden_ids]))
            self.persist_participants(include_rows=True)
            self.retranslate_history([row for row in self.rows if row.get('translation_stale') or row.get('translation_pending')],cfg)

    def retranslate_history(self,rows,cfg):
        if not rows:
            self.window.toast('词库已应用，没有需要更新的译文'); return
        from app.record_rewrite import RecordRewriteJob
        if getattr(self,'_rewrite_job',None) and (self._rewrite_job.running or getattr(self,'_rewrite_pending',False)):
            old_token=getattr(self,'_rewrite_token',None)
            if old_token==getattr(self,'_content_token',0):
                self.window.toast('历史重译正在进行，可先取消'); return
            self._rewrite_job.cancel.set()
            self.window.toast('正在结束上一条记录的重译，请稍后重试'); return
        job=RecordRewriteJob(self)
        self._rewrite_job=job
        token=getattr(self,'_content_token',0)
        self._rewrite_token=token
        self._rewrite_pending=True
        def is_current_job():
            return getattr(self,'_content_token',0)==token and getattr(self,'_rewrite_job',None) is job
        job.progress.connect(lambda current,total:self.window.set_status(f'历史文字重译 {current}/{total}','working') if is_current_job() else None)
        def complete(results):
            if not is_current_job(): return
            accepted=[]
            for result in results:
                current=self._row_cache.get(result['id'])
                if current and current.get('source_revision')==result.get('source_revision'):
                    self._row_cache[result['id']]=result; accepted.append(result)
            self.window.apply_caption_changes(self.display_rows(accepted),[])
            self.persist_participants(include_rows=True)
            failures=sum(bool(row.get('translation_error')) for row in accepted)
            self.window.set_status('历史重译完成'+(f'，{failures} 条未完成，已保留原文' if failures else ''),'idle')
        def cancelled(done,total):
            if is_current_job():
                self.window.set_status(f'历史重译已取消，完成 {done}/{total} 条','idle')
        job.completed.connect(complete)
        job.cancelled.connect(cancelled)
        job.failed.connect(lambda message:self.window.show_error(message) if is_current_job() else None)
        def start(url):
            if not is_current_job(): return
            self._rewrite_pending=False
            if job.cancel.is_set():
                job.cancelled.emit(0,len(rows)); return
            job.start(rows,{**cfg,'server_url':url})
        def start_failed(message):
            if not is_current_job(): return
            self._rewrite_pending=False
            self.window.show_error(message)
        if cfg.get('translation_provider')=='lmstudio' and not cfg.get('llm_fallback'):
            start(cfg.get('server_url',''))
        else: self.server.ensure(cfg,start,start_failed)

    def ensure_participants(self):
        if not self.participants.bindings:
            self.rows=[self.participants.decorate(row) for row in self.rows]

    def show_participants(self):
        from app.meeting_ui import ParticipantsDialog
        self.ensure_participants()
        dialog=ParticipantsDialog(self.participants,self.rows,self.window)
        dialog.changed.connect(self.apply_participants)
        dialog.exec()

    def apply_participants(self,state):
        self.participants=ParticipantRegistry(state=state)
        self.rows=[self.participants.decorate(row) for row in self.rows]
        self.window.update_caption(self.display_rows([row for row in self.rows if row['id'] not in self.hidden_ids]))
        if self.active: self.send_payload({'cmd':'set_participants','state':state})
        else: self.persist_participants()

    def persist_participants(self,include_rows=False):
        if not self.record_path: return
        try:
            saved=read_record(self.record_path)
            rows=self.rows if include_rows else [self.participants.decorate(row) for row in saved.get('rows',[])]
            update_record(self.record_path,rows=rows,participant_state=self.participants.to_dict(),snapshot=self.native_snapshot)
        except Exception as exc:
            self.window.show_error('历史记录修改未能保存：'+str(exc))

    def rename_speaker(self,speaker,name):
        self.ensure_participants()
        pid=speaker if isinstance(speaker,str) and speaker in self.participants.participants else None
        if pid is None:
            pid=next((row.get('participant_id') for row in reversed(self.rows) if row.get('speaker')==speaker),None)
        try: self.participants.rename(pid,name)
        except ValueError as exc:
            self.window.show_error(str(exc)); return
        self.rows=[self.participants.decorate(row) for row in self.rows]
        self.window.update_caption(self.display_rows([row for row in self.rows if row['id'] not in self.hidden_ids]))
        if self.active: self.send_payload({'cmd':'rename_participant','participant_id':pid,'name':name})
        else: self.persist_participants()

    def show_ai(self):
        from app.ai_ui import AIModelDialog
        previous=getattr(self,'_ai_dialog',None)
        if previous and previous.isVisible():
            previous.raise_(); previous.activateWindow(); return
        token=getattr(self,'_content_token',0)
        get_rows=lambda:[dict(row) for row in self.rows] if getattr(self,'_content_token',0)==token else []
        get_record_path=lambda:self.record_path if getattr(self,'_content_token',0)==token else None
        dialog=AIModelDialog(self.window.settings,get_rows,get_record_path,self.window)
        self._ai_dialog=dialog
        dialog.translation_provider.setEnabled(not self.active or self.paused)
        dialog.translation_provider.setToolTip('实时翻译后端在暂停后修改；问答模型独立于语音识别')
        dialog.settings_changed.connect(lambda values:self.apply_config({**self.window._config_snapshot(),**values})
                                        if getattr(self,'_content_token',0)==token and self._ai_dialog is dialog else None)
        dialog.show()

    def manual_save(self):
        if self.active:
            self.send_payload({'cmd':'manual_save'})
            return
        if not self.rows and not self.record_path:
            self.window.toast('当前没有已确认的字幕可保存；开始听写后再保存。')
            return
        try:
            if self.record_path:
                update_record(self.record_path,rows=self.rows,participant_state=self.participants.to_dict(),snapshot=self.native_snapshot)
            else:
                journal=Journal(ROOT/'records',{**self.window.settings,'save_records':True,'long_meeting_mode':True})
                journal.save_changes(self.rows,snapshot=self.native_snapshot,extra={'status':'stopped','participant_state':self.participants.to_dict()})
                self.record_path=str(journal.path)
                journal.close()
            self.window.toast('当前会议文字已手动保存')
        except Exception as exc: self.window.show_error('保存失败：'+str(exc))

    def load_record(self,path):
        record=read_record(path)
        self._rotate_content_context()
        self.participants=ParticipantRegistry(state=record.get('participant_state'))
        self.rows=[self.participants.decorate(row) for row in record.get('rows',[])]
        self.window.export_total_count=len(self.rows)
        self.native_snapshot=record.get('native_snapshot',{})
        self.record_path=str(path)
        self.hidden_ids.clear()
        self.window.speaker_names.clear()
        self.window.update_caption(self.display_rows(self.rows),'')
        self.window.set_status('正在查看：'+Path(path).stem,'idle')
        self._show_recovery_warnings(record.get('recovery_warnings'))

    def _show_recovery_warnings(self,warnings):
        if not warnings: return
        row_ids=list(warnings.get('corrupted_row_ids') or [])
        event_ids=list(warnings.get('corrupted_event_ids') or [])
        identifiers=[]
        if row_ids: identifiers.append('损坏字幕ID：'+', '.join(map(str,row_ids)))
        if event_ids: identifiers.append('损坏事件ID：'+', '.join(map(str,event_ids)))
        message=(f'已恢复可确认的数据；发现 {len(row_ids)} 条损坏字幕、{len(event_ids)} 条损坏事件。'
                 +(' '+ '；'.join(identifiers) if identifiers else '')
                 +' 损坏条目仍保留在原记录数据库中，未删除或覆盖。')
        self.window.show_error(message)

    def continue_record(self,path):
        if self.active:
            self.window.toast('请先结束当前会议'); return
        try:
            record=read_record(path)
        except (OSError,ValueError,KeyError) as exc:
            self.window.show_error('会议恢复检查失败：'+str(exc)); return
        # Preserve damaged header bytes before publishing a repaired manifest.
        try: json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except ValueError:
            import shutil
            backup=Path(str(path)+'.corrupt-'+datetime.now().strftime('%Y%m%d%H%M%S')+'.bak')
            shutil.copy2(path,backup)
        self.start({**self.window._config_snapshot(),'resume_record':str(path)})
        self._show_recovery_warnings(record.get('recovery_warnings'))

    def show_recovery(self,automatic=False):
        if self.active: return
        from app.meeting_store import recoverable_meetings
        from app.meeting_ui import RecoveryDialog
        items=recoverable_meetings(ROOT/'records')
        if not items:
            if not automatic: self.window.toast('没有未正常结束的会议')
            return
        if automatic:
            # Startup should offer recovery without blocking all meeting controls.
            self.meeting_button.setText(f'会议工具 · 待恢复 {len(items)}')
            self.window.toast(f'发现 {len(items)} 条未正常结束的会议，可在会议工具中查看“异常会议恢复”')
            return
        dialog=RecoveryDialog(items,self.window)
        if dialog.exec() and dialog.selected_path:
            if dialog.mode=='continue': self.continue_record(dialog.selected_path)
            else: self.load_record(dialog.selected_path)
