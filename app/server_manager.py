"""Own the upstream service process and reuse its loaded models across sessions."""
import json
import os
import secrets
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.settings import ROOT
from app.wlk_config import make_config


def process_environment():
    env = QProcessEnvironment.systemEnvironment()
    env.insert('PYTHONUTF8','1')
    env.insert('PYTHONIOENCODING','utf-8')
    env.insert('PATH', str(ROOT/'runtime/ffmpeg')+os.pathsep+str(ROOT/'.venv/Lib/site-packages/torch/lib')+os.pathsep+os.environ.get('PATH',''))
    env.insert('HF_HOME',str(ROOT/'models/cache'))
    return env


class ServerManager(QObject):
    changed = pyqtSignal(str)
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.network = QNetworkAccessManager(self)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.setProcessEnvironment(process_environment())
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.check_ready)
        self.url=''
        self.fingerprint=None
        self.ready=False
        self.announced=False
        self.pending=[]
        self.next_settings=None
        self.next_signature=None
        self.buffer=b''
        self.started_at=0.
        self.request_path=None
        self.sessions=[]
        self.management_token=None
        self.prepared_translation_providers=set()

    @property
    def active(self):
        return self.process.state()!=QProcess.ProcessState.NotRunning

    def ensure(self,settings,on_ready,on_error=None):
        remote=(settings.get('server_url') or '').strip()
        if remote:
            on_ready(remote.rstrip('/'))
            return
        try:
            config=make_config(settings)
        except Exception as exc:
            if on_error: on_error(str(exc))
            else: self.error.emit(str(exc))
            return
        signature=self.signature(config,settings)
        provider=str(settings.get('translation_provider') or 'nllb').strip().lower()
        if provider in ('local','nllb'):
            provider='nllb'
        elif provider in ('llm','lmstudio'):
            provider='lmstudio'
        needs_translation=(settings.get('translation_mode','local')!='off'
                           and (provider=='lmstudio' or bool(config.target_language)))

        def deliver(url):
            if needs_translation and provider not in self.prepared_translation_providers:
                self.prepare_translation(settings,'local',on_ready,on_error or self.error.emit)
            else:
                on_ready(url)

        if self.active:
            if self.next_settings is not None:
                if signature==self.next_signature:
                    self.pending.append((deliver,on_error))
                else:
                    self._reject(on_error,'原库服务正在切换到另一个配置，请等待完成后再试。')
                return
            if signature==self.fingerprint:
                if self.ready: deliver(self.url)
                else: self.pending.append((deliver,on_error))
                return
            if not self.ready:
                self._reject(on_error,'原库服务仍在加载另一个配置，请等待就绪后再切换。')
                return
            if self.has_active_local_sessions():
                self._reject(on_error,'其他会议正在使用该模型，请先结束这些会议再改变服务模型或处理参数。')
                return
            if not self.prepare_restart():
                self._reject(on_error,'原库服务仍有活动会话或无法确认空闲，暂不能切换模型。')
                return
            self.pending.append((deliver,on_error))
            self.next_settings=dict(settings)
            self.next_signature=signature
            self.stop(restarting=True)
            return
        self.pending.append((deliver,on_error))
        self.launch(settings,config,signature)

    def prepare_translation(self,settings,ready,failed=None,on_error=None):
        """Prepare local translation through the ready service without restarting ASR."""
        settings=dict(settings or {})
        if isinstance(ready,str):
            requested_mode=ready
            ready,failed=failed,on_error
            if requested_mode!='local':
                if failed: failed('仅本地实时翻译需要准备 NLLB 模型。')
                return
            settings['translation_mode']=requested_mode
        if failed is None:
            failed=self.error.emit
        remote=(settings.get('server_url') or '').strip()
        if remote:
            ready(remote.rstrip('/'))
            return
        if not self.ready or not self.url:
            failed('原库服务尚未就绪，暂不能准备实时翻译。')
            return
        provider=str(settings.get('translation_provider') or 'nllb').strip().lower()
        if provider in ('lmstudio','llm'):
            self.prepared_translation_providers.add('lmstudio')
            ready(self.url)
            return
        if not self.management_token:
            failed('原库服务管理认证不可用，暂不能准备实时翻译。')
            return
        try:
            # Compare against the ASR service baseline, which was typically
            # launched with translation off. The per-session target is added
            # only after the translation model has been prepared.
            config_settings={**settings,'translation_mode':'off'}
            config=make_config(config_settings)
            if self.fingerprint and self.signature(config,settings)!=self.fingerprint:
                failed('当前原库服务与会议设置不一致；请先结束其他会议，再按当前配置启动服务。')
                return
        except Exception as exc:
            failed(str(exc))
            return
        sources=[]
        targets=[]
        if settings.get('source_mode')=='both' and settings.get('separate_sources',True):
            sources.extend((settings.get('source_language'),settings.get('mic_language')))
            targets.extend((settings.get('target_language'),settings.get('mic_target_language')))
        else:
            sources.append(settings.get('source_language'))
            targets.append(settings.get('target_language'))
        sources=sorted({str(value).strip() for value in sources if value and str(value).strip().lower()!='auto'})
        targets=sorted({str(value).strip() for value in targets if value})
        if not targets:
            failed('请先选择译文目标语言。')
            return
        payload={'provider':'nllb','source_languages':sources,'target_languages':targets}
        def prepared(url):
            self.prepared_translation_providers.add('nllb')
            ready(url)

        self._post_prepare_translation(payload,prepared,failed)

    def _post_prepare_translation(self,payload,ready,failed):
        request=QNetworkRequest(QUrl(self.url.rstrip('/')+'/desktop/prepare-translation'))
        request.setRawHeader(b'Authorization',('Bearer '+self.management_token).encode('utf-8'))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        reply=self.network.post(request,json.dumps(payload,ensure_ascii=False).encode('utf-8'))

        def finished():
            try:
                raw=bytes(reply.readAll())
                try:
                    result=json.loads(raw.decode('utf-8')) if raw else {}
                except (UnicodeDecodeError,ValueError):
                    result={}
                status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if reply.error()!=QNetworkReply.NetworkError.NoError or (status is not None and not 200<=int(status)<300):
                    message=result.get('detail') or result.get('error') or reply.errorString() or '本地翻译准备失败。'
                    failed(str(message))
                elif not result.get('ready'):
                    failed(str(result.get('error') or '本地翻译服务未确认就绪。'))
                else:
                    ready(self.url)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)

    def _reject(self,on_error,message):
        if on_error:
            on_error(message)
        else:
            self.error.emit(message)

    def has_active_local_sessions(self):
        return any(
            process.state()==QProcess.ProcessState.Running
            and process.property('uses_server') is not False
            for process in self.sessions
        )

    def prepare_restart(self):
        """Ask the local service to atomically close its gate if it is idle."""
        if not self.management_token or not self.ready:
            return False
        request=Request(
            self.url+'/desktop/prepare-restart',
            data=b'',
            headers={'Authorization':'Bearer '+self.management_token},
            method='POST',
        )
        try:
            with urlopen(request,timeout=1.0) as response:
                status=json.load(response)
            return status.get('active_sessions')==0 and status.get('restarting') is True
        except (HTTPError, OSError, ValueError):
            return False

    def launch(self,settings,config=None,signature=None):
        config=config or make_config(settings)
        self.fingerprint=signature or self.signature(config,settings)
        host=config.host if config.host not in ('0.0.0.0','::') else '127.0.0.1'
        if ':' in host and not host.startswith('['): host='['+host+']'
        self.url=f"{'https' if config.ssl_certfile else 'http'}://{host}:{config.port}"
        self.ready=False
        self.prepared_translation_providers=set()
        provider=str(settings.get('translation_provider') or 'nllb').strip().lower()
        if settings.get('translation_mode','local')!='off':
            if provider in ('lmstudio','llm'):
                self.prepared_translation_providers.add('lmstudio')
            elif config.target_language:
                self.prepared_translation_providers.add('nllb')
        self.announced=False
        self.buffer=b''
        self.started_at=time.monotonic()
        self.management_token=secrets.token_urlsafe(32)
        (ROOT/'data').mkdir(exist_ok=True)
        self.request_path=ROOT/'data'/('server-'+uuid.uuid4().hex+'.json')
        managed_settings=dict(settings)
        managed_settings['_management_token']=self.management_token
        self.request_path.write_text(json.dumps(managed_settings,ensure_ascii=False),encoding='utf-8')
        self.changed.emit('正在加载原库服务与模型…')
        program=ROOT/'.venv/Scripts/python.exe'
        speaker_python=ROOT/'runtime/speaker/Scripts/python.exe'
        if config.diarization and config.diarization_backend=='sortformer':
            if not speaker_python.is_file():
                self.fail('说话人运行环境缺失，请在工具中运行说话人环境安装。')
                self.request_path.unlink(missing_ok=True)
                self.request_path=None
                self.management_token=None
                return
            program=speaker_python
        self.process.start(str(program),['-u','-m','app.server','--settings',str(self.request_path)])
        self.timer.start()

    @staticmethod
    def signature(config,settings):
        params=dict(config.__dict__)
        # Both native policies isolate per-session languages. The SimulStreaming
        # tokenizer compatibility hook is installed before any session starts.
        if getattr(config,'backend_policy',None) in ('localagreement','simulstreaming') and not getattr(config,'direct_english_translation',False):
            params.pop('lan',None)
        # Language and translation activation are per-session values. Keep the
        # service fingerprint strict for models and all other engine options.
        params.pop('target_language',None)
        return json.dumps(params,sort_keys=True)+str(settings.get('allow_downloads',False))

    def log(self,data):
        (ROOT/'logs').mkdir(exist_ok=True)
        with (ROOT/'logs/server.log').open('a',encoding='utf-8') as stream:
            stream.write(data)

    def read_output(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            raw,self.buffer=self.buffer.split(b'\n',1)
            try:
                event=json.loads(raw)
                if event.get('type')=='server_ready': self.announced=True
            except (ValueError,AttributeError):
                self.log(raw.decode('utf-8',errors='replace')+'\n')

    def read_errors(self):
        self.log(bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace'))

    def check_ready(self):
        if time.monotonic()-self.started_at>300:
            self.fail('原库服务加载超时，请查看 logs/server.log。')
            self.stop()
            return
        if not self.announced: return
        try:
            with urlopen(self.url+'/health',timeout=.25) as response:
                info=json.load(response)
            if not info.get('ready'): return
        except Exception:
            return
        self.timer.stop()
        self.ready=True
        self.changed.emit('原库服务就绪：'+self.url)
        callbacks,self.pending=self.pending,[]
        for callback,_ in callbacks: callback(self.url)

    def fail(self,message):
        callbacks,self.pending=self.pending,[]
        self.error.emit(message)
        for _,callback in callbacks:
            if callback: callback(message)

    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.timer.stop()
            self.fail('WhisperLiveKit 服务进程无法启动，请修复环境。')
            self.next_settings=None
            self.next_signature=None
            self.management_token=None
            if self.request_path: self.request_path.unlink(missing_ok=True)
            self.request_path=None
            self.stopped.emit()

    def stop(self, *, restarting=False):
        self.timer.stop()
        self.ready=False
        if not restarting:
            # A user/window shutdown must cancel a staged model switch. Only
            # ensure() may deliberately stop once and then relaunch.
            self.next_settings=None
            self.next_signature=None
            self.pending=[]
            self.prepared_translation_providers=set()
        if self.active:
            self.process.write(b'{"cmd":"stop"}\n')
            # Stuck native initialization cannot handle a control message.
            QTimer.singleShot(30000,self.force_stop)
        else: self.stopped.emit()

    def force_stop(self):
        if self.active and not self.ready and self.timer.isActive()==False:
            self.process.kill()

    def finished(self,code,status):
        self.timer.stop()
        self.ready=False
        self.read_output()
        self.read_errors()
        if self.request_path: self.request_path.unlink(missing_ok=True)
        if self.next_settings:
            settings,self.next_settings=self.next_settings,None
            self.next_signature=None
            self.launch(settings)
            return
        if code and self.pending:
            self.fail('原库服务启动失败，请查看 logs/server.log 或检查所选模型的依赖。')
        elif self.pending:
            self.fail('原库服务已停止，待启动会议未能连接。')
        self.management_token=None
        self.next_signature=None
        self.request_path=None
        self.changed.emit('原库服务已停止')
        self.stopped.emit()
