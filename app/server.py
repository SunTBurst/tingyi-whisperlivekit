"""Managed entry point for upstream create_app; no replacement API or pipeline."""
import argparse
import asyncio
import copy
import json
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from app.settings import ROOT
sys.path.insert(0,str(ROOT/'upstream'))
from app.wlk_config import make_config


def _session_translation_engine(engine, target_language, target_supplied):
    """Give each WLK stream an engine view with isolated translation options."""
    session_engine=copy.copy(engine)
    # TranscriptionEngine.__new__ is a process-wide singleton, so copy.copy
    # can return the original object unless we allocate a same-type shell.
    if session_engine is engine:
        session_engine=object.__new__(type(engine))
        session_engine.__dict__.update(engine.__dict__)
    session_engine.args=copy.copy(engine.args)
    if target_supplied:
        session_engine.args.target_language=str(target_language or '')
        if not session_engine.args.target_language:
            # A previously prepared shared model must never reactivate for an
            # explicitly translation-off desktop WebSocket.
            session_engine.translation_model=None
    return session_engine


def _desktop_audio_processor(base_class, engine_type):
    if getattr(base_class,'_desktop_session_translation',False):
        return base_class

    class DesktopSessionAudioProcessor(base_class):
        _desktop_session_translation=True

        def __init__(self,*args,**kwargs):
            engine=kwargs.get('transcription_engine')
            if isinstance(engine,engine_type):
                supplied='target_language' in kwargs and kwargs.get('target_language') is not None
                kwargs['transcription_engine']=_session_translation_engine(
                    engine,kwargs.get('target_language'),supplied)
            super().__init__(*args,**kwargs)

    DesktopSessionAudioProcessor.__name__='DesktopSessionAudioProcessor'
    DesktopSessionAudioProcessor.__qualname__='DesktopSessionAudioProcessor'
    return DesktopSessionAudioProcessor


class DesktopLifecycleMiddleware:
    """Management gate for restarting the service without changing WLK routes."""

    _WEBSOCKET_PATHS = frozenset({"/asr", "/v1/listen"})
    _TRANSCRIPTION_PATHS = frozenset({"/v1/audio/transcriptions","/desktop/translate"})

    def __init__(self, app, token):
        self.app = app
        self._token = str(token)
        self.active_sessions = 0
        self.restarting = False

    @staticmethod
    async def _json(send, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, scope):
        import hmac

        candidate = next((value[7:] for name, value in scope.get("headers", [])
                          if name.lower() == b"authorization" and value.lower().startswith(b"bearer ")), b"")
        try:
            supplied = candidate.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return hmac.compare_digest(supplied, self._token)

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        path = scope.get("path", "")
        if kind == "http" and path in (
            "/desktop/status", "/desktop/prepare-restart", "/desktop/prepare-translation"
        ):
            if not self._authorized(scope):
                await self._json(send, 401, {"error": "unauthorized"})
                return
            method = scope.get("method", "GET").upper()
            if path == "/desktop/status":
                if method != "GET":
                    await self._json(send, 405, {"error": "method not allowed"})
                    return
                await self._json(send, 200, {"active_sessions": self.active_sessions,
                                             "restarting": self.restarting})
                return
            if method != "POST":
                await self._json(send, 405, {"error": "method not allowed"})
                return
            if path == "/desktop/prepare-translation":
                if self.restarting:
                    await self._json(send, 503, {"error": "server is restarting"})
                    return
                await self.app(scope, receive, send)
                return
            # The check and gate assignment have no await between them, so no
            # new ASR task can enter between accepting restart and blocking work.
            if self.active_sessions:
                await self._json(send, 409, {"active_sessions": self.active_sessions,
                                             "restarting": self.restarting})
                return
            self.restarting = True
            await self._json(send, 200, {"active_sessions": 0, "restarting": True})
            return

        counted = (
            kind == "websocket" and path in self._WEBSOCKET_PATHS
        ) or (
            kind == "http" and path in self._TRANSCRIPTION_PATHS
            and scope.get("method", "").upper() == "POST"
        )
        if counted and getattr(
            getattr(self.app, "state", None), "desktop_translation_preparing", False
        ):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1013,
                            "reason": "translation model is being prepared"})
            else:
                await self._json(send,503,{"error":"translation model is being prepared"})
            return
        if not counted:
            await self.app(scope, receive, send)
            return
        if self.restarting:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1013,
                            "reason": "server is restarting"})
            else:
                await self._json(send, 503, {"error": "server is restarting"})
            return

        self.active_sessions += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active_sessions -= 1


def build_app(settings, *, management=True):
    management_token = settings.pop("_management_token", None)
    config = make_config(settings)
    from app.native_models import configure_local_models
    configure_local_models(config)
    if config.backend_policy=='simulstreaming':
        from app.native_asr import configure_session_tokenizers
        configure_session_tokenizers()
    elif config.backend_policy=='localagreement':
        from app.native_timing import configure_silence_timing
        configure_silence_timing()
    from whisperlivekit import basic_server
    from whisperlivekit.basic_server import create_app
    from whisperlivekit.core import TranscriptionEngine
    from whisperlivekit.timed_objects import FrontData
    # Upstream's web serialization omits tokens while REST already has them.
    # Preserve the original payload and add exact model word times for archives.
    original = FrontData.to_dict
    if not getattr(original,'_desktop_tokens',False):
        def with_tokens(self):
            data = original(self)
            native_lines = [line for line in self.lines if line.text or line.speaker == -2]
            for item,line in zip(data['lines'],native_lines):
                tokens = getattr(line,'tokens',None)
                if tokens:
                    item['tokens'] = [{'text':t.text,'start':t.start,'end':t.end,
                                       'probability':getattr(t,'probability',None)} for t in tokens]
            return data
        with_tokens._desktop_tokens = True
        FrontData.to_dict = with_tokens
    app = create_app(config)
    basic_server.AudioProcessor=_desktop_audio_processor(basic_server.AudioProcessor,TranscriptionEngine)
    from fastapi import Request,HTTPException
    text_lock=asyncio.Lock()

    @app.post('/desktop/translate')
    async def translate_text(request:Request):
        api_token=config.api_token or os.environ.get('WLK_API_TOKEN')
        if api_token:
            import hmac
            supplied=request.headers.get('authorization','')
            if not hmac.compare_digest(supplied,'Bearer '+api_token):
                raise HTTPException(401,'Unauthorized')
        try: data=await request.json()
        except ValueError: raise HTTPException(400,'请求必须为 JSON 对象')
        if not isinstance(data,dict): raise HTTPException(400,'请求必须为 JSON 对象')
        text=str(data.get('text') or '')
        source=str(data.get('source') or '')
        target=str(data.get('target') or '')
        if not text or len(text)>16000 or not source or source=='auto' or not target:
            raise HTTPException(400,'文字翻译需要确定的源/目标语言及不超过16000字的文本')
        async with text_lock:
            model=getattr(request.app.state,'desktop_translation_model',None)
            if model is None or not hasattr(model,'get_tokenizer'):
                from nllw import load_model
                model=await asyncio.to_thread(load_model,[source],nllb_backend=config.nllb_backend,nllb_size=config.nllb_size)
                request.app.state.desktop_translation_model=model
            from app.text_translation import translate_with_model
            try:
                result=await asyncio.to_thread(translate_with_model,model,text,source,target,data.get('glossary_rules') or [])
            except (ValueError,TypeError) as exc:
                raise HTTPException(400,str(exc))
            return {**result,'model':'NLLB '+str(getattr(model,'nllb_size',config.nllb_size)),
                    'source':source,'target':target}

    def valid_nllb_languages(values):
        from nllw.languages import convert_to_nllb_code
        converted=[]
        for value in values:
            code=str(value or '').strip()
            if not code or code.lower()=='auto':
                continue
            try:
                nllb_code=convert_to_nllb_code(code)
            except (KeyError,TypeError,ValueError):
                nllb_code=None
            if not nllb_code:
                raise HTTPException(400,f'本地翻译不支持识别语言：{code}')
            converted.append(nllb_code)
        return list(dict.fromkeys(converted))

    @app.post('/desktop/prepare-translation')
    async def prepare_translation(request:Request):
        if not management_token:
            raise HTTPException(404,'此接口仅供桌面管理服务使用。')
        import hmac
        if not hmac.compare_digest(request.headers.get('authorization',''),
                                   'Bearer '+str(management_token)):
            raise HTTPException(401,'Unauthorized')
        try:
            data=await request.json()
        except ValueError:
            raise HTTPException(400,'请求必须为 JSON 对象')
        if not isinstance(data,dict):
            raise HTTPException(400,'请求必须为 JSON 对象')
        provider=str(data.get('provider') or 'nllb').strip().lower()
        if provider in ('lmstudio','llm'):
            return {'ready':True,'provider':'lmstudio','loaded':False}
        if provider not in ('nllb','local'):
            raise HTTPException(400,'不支持的实时翻译提供方。')
        engine=getattr(request.app.state,'transcription_engine',None)
        if engine is None:
            raise HTTPException(503,'WhisperLiveKit 服务尚未就绪。')
        if getattr(config,'translation_backend','nllb')!='nllb':
            raise HTTPException(409,'当前服务配置的实时翻译后端不是本地 NLLB。')

        source_languages=data.get('source_languages')
        if 'source_languages' in data and not isinstance(source_languages,list):
            raise HTTPException(400,'source_languages 必须为语言代码数组。')
        if 'source_languages' not in data:
            source_languages=[data.get('source') or config.lan]
        target_languages=data.get('target_languages')
        if 'target_languages' in data and not isinstance(target_languages,list):
            raise HTTPException(400,'target_languages 必须为语言代码数组。')
        if 'target_languages' not in data:
            target_languages=[data.get('target') or config.target_language]
        if not target_languages or not any(str(value or '').strip() for value in target_languages):
            raise HTTPException(400,'请先选择译文目标语言。')
        nllb_sources=valid_nllb_languages(source_languages)
        if not nllb_sources:
            # Auto-detection does not have tokenizer codes to preload. Seed the
            # installed shared model with a valid language; session creation
            # still receives its own language/target parameters.
            fallback=str(getattr(config,'lan','') or '')
            if not fallback or fallback.lower()=='auto':
                fallback='en'
            nllb_sources=valid_nllb_languages([fallback])
        valid_nllb_languages(target_languages)

        application=request.app
        prepare_count=getattr(application.state,'desktop_translation_prepare_count',0)+1
        application.state.desktop_translation_prepare_count=prepare_count
        application.state.desktop_translation_preparing=True
        try:
            async with text_lock:
                model=getattr(engine,'translation_model',None)
                if model is None:
                    model=getattr(application.state,'desktop_translation_model',None)
                loaded=False
                if model is None:
                    if str(getattr(config,'nllb_backend','')).lower()!='ctranslate2' or str(getattr(config,'nllb_size','')).upper()!='600M':
                        raise HTTPException(409,'本地未安装当前配置的 NLLB。请使用已安装的 CTranslate2 NLLB 600M 模型。')
                    from app.native_models import NLLB_MODEL_DIR, _PATCH_ATTR, configure_local_models
                    required=('config.json','model.bin','shared_vocabulary.txt','sentencepiece.bpe.model',
                              'tokenizer.json','tokenizer_config.json')
                    if not NLLB_MODEL_DIR.is_dir() or any(not (NLLB_MODEL_DIR/name).is_file() for name in required):
                        raise HTTPException(409,'本地 NLLB 600M 模型未安装；已阻止下载，请在模型管理中先安装。')
                    if not configure_local_models(config):
                        raise HTTPException(503,'本地 NLLB 加载器未就绪；已阻止联网下载。')
                    from nllw import load_model
                    if not getattr(load_model,_PATCH_ATTR,False):
                        raise HTTPException(503,'当前 NLLB 加载器不是本地文件加载器；已阻止联网下载。')
                    try:
                        model=await asyncio.to_thread(load_model,nllb_sources,
                            nllb_backend=config.nllb_backend,nllb_size=config.nllb_size)
                    except Exception as exc:
                        raise HTTPException(503,'本地 NLLB 加载失败：'+str(exc))
                    engine.translation_model=model
                    loaded=True
                else:
                    engine.translation_model=model
                application.state.desktop_translation_model=model
                return {'ready':True,'provider':'nllb','loaded':loaded,
                        'target_languages':target_languages}
        finally:
            remaining=max(0,getattr(application.state,'desktop_translation_prepare_count',1)-1)
            application.state.desktop_translation_prepare_count=remaining
            application.state.desktop_translation_preparing=remaining>0

    @asynccontextmanager
    async def lifespan(application):
        engine = await asyncio.to_thread(TranscriptionEngine,config=config)
        # Retain Faster-Whisper's language metadata that its stock adapter drops.
        if config.backend_policy=='localagreement' and getattr(engine.asr,'backend_choice','')=='faster-whisper':
            from app.asr import LanguageAwareASR
            engine.asr = LanguageAwareASR(engine.asr)
        application.state.transcription_engine = engine
        application.state.desktop_translation_model = engine.translation_model
        print(json.dumps({'type':'server_ready','port':config.port}),flush=True)
        yield
    app.router.lifespan_context = lifespan
    if management and management_token:
        lifecycle=DesktopLifecycleMiddleware(app, management_token)
        app.state.desktop_lifecycle=lifecycle
        app = lifecycle
    return app,config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', required=True)
    parser.add_argument('--standalone', action='store_true', help='Keep original Web server available independently of the desktop')
    args = parser.parse_args()
    request_path = Path(args.settings)
    settings = json.loads(request_path.read_text(encoding='utf-8'))
    request_path.unlink(missing_ok=True)
    os.environ['PATH'] = str(ROOT/'runtime/ffmpeg')+os.pathsep+str(ROOT/'.venv/Lib/site-packages/torch/lib')+os.pathsep+os.environ.get('PATH','')
    os.environ['HF_HOME'] = str(ROOT/'models/cache')
    if not settings.get('allow_downloads',False):
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['TRANSFORMERS_OFFLINE']='1'
    logging.basicConfig(stream=sys.stderr,level=logging.INFO)
    app,config = build_app(settings, management=not args.standalone)
    import uvicorn
    options = {'host':config.host,'port':config.port,'log_level':'info','lifespan':'on'}
    for key in ('ssl_certfile','ssl_keyfile','forwarded_allow_ips'):
        if getattr(config,key): options[key]=getattr(config,key)
    server = uvicorn.Server(uvicorn.Config(app,**options))
    # Use the same Windows pipe reader as the original desktop backend: no
    # blocking CRT stdin read during native numerical-library initialization.
    from app.backend import control_messages
    def commands():
        for message in control_messages(sys.stdin):
            if message.get('cmd')=='stop':
                server.should_exit = True
                return
        server.should_exit = True
    if not args.standalone:
        threading.Thread(target=commands,daemon=True,name='ServerCommands').start()
    asyncio.run(server.serve())


if __name__=='__main__':
    main()
