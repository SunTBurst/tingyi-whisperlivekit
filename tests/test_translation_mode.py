import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from argparse import Namespace
from unittest.mock import patch

from PyQt6.QtCore import QProcess
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QApplication

from app.server import DesktopLifecycleMiddleware, _desktop_audio_processor, build_app
from app.server_manager import ServerManager
from app.session import SessionControl
from app.settings import DEFAULTS


QT_APP = QApplication.instance() or QApplication([])
TOKEN = "translation-prepare-token"


def asgi_request(app, path, *, method="POST", token=TOKEN, body=b"{}", scope_type="http"):
    events = []
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    scope = {"type": scope_type, "path": path, "method": method, "headers": headers,
             "query_string": b"", "http_version": "1.1", "scheme": "http",
             "server": ("localhost", 8000), "client": ("127.0.0.1", 30000)}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(event):
        events.append(event)

    return events, lambda: app(scope, receive, send)


def result(events):
    status = next(event["status"] for event in events if event["type"] == "http.response.start")
    body = next(event["body"] for event in events if event["type"] == "http.response.body")
    return status, json.loads(body)


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in tuple(self.callbacks):
            callback()


class _Reply:
    def __init__(self, payload):
        self.finished = _Signal()
        self._payload = payload

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def readAll(self):
        return self._payload

    def errorString(self):
        return "network failed"

    def attribute(self, _attribute):
        return 200

    def deleteLater(self):
        pass


class _Network:
    def __init__(self, payload=b'{"ready":true}'):
        self.payload = payload
        self.request = None
        self.reply = None

    def post(self, request, body):
        self.request = request
        self.body = bytes(body)
        self.reply = _Reply(self.payload)
        return self.reply


class _ActiveManager(ServerManager):
    @property
    def active(self):
        return True


class TranslationModeTests(unittest.TestCase):
    def _build_managed_app(self):
        settings = {**DEFAULTS, "asr_model": "small", "source_language": "en",
                    "translation_mode": "off", "wlk": {"nllb_backend": "ctranslate2",
                                                          "nllb_size": "600M"},
                    "_management_token": TOKEN}
        with patch("app.native_models.configure_local_models"), \
             patch("app.native_timing.configure_silence_timing"):
            application, config = build_app(settings)
        engine = SimpleNamespace(translation_model=None, args=Namespace(target_language=""), config=config)
        application.app.state.transcription_engine = engine
        return application, engine, config

    def test_prepare_endpoint_loads_local_model_and_updates_engine_without_restart(self):
        application, engine, _config = self._build_managed_app()
        with tempfile.TemporaryDirectory() as folder:
            from pathlib import Path
            model_dir = Path(folder)
            for name in ("config.json", "model.bin", "shared_vocabulary.txt", "sentencepiece.bpe.model",
                         "tokenizer.json", "tokenizer_config.json"):
                (model_dir / name).write_bytes(b"local")
            model = object()
            loader_patch = patch("nllw.load_model", return_value=model)
            with patch("app.native_models.NLLB_MODEL_DIR", model_dir), \
                 patch("app.native_models.configure_local_models", return_value=True), \
                 loader_patch as load:
                setattr(load, "_whisperlivekit_local_ct2_wrapper", True)
                body = json.dumps({"source_languages": ["en", "zh"],
                                   "target_languages": ["zh", "en"]}).encode()
                events, call = asgi_request(application, "/desktop/prepare-translation", body=body)
                asyncio.run(call())
                self.assertEqual(result(events)[0], 200)
                self.assertEqual(result(events)[1]["provider"], "nllb")
                self.assertTrue(result(events)[1]["loaded"])
                self.assertIs(engine.translation_model, model)
                self.assertIs(application.app.state.desktop_translation_model, model)
                self.assertEqual(engine.args.target_language, "")
                self.assertEqual(engine.config.target_language, "")
                self.assertFalse(application.app.state.desktop_translation_preparing)
                load.assert_called_once_with(["eng_Latn", "zho_Hans"],
                                             nllb_backend="ctranslate2", nllb_size="600M")

    def test_desktop_audio_processor_isolates_off_on_off_stream_translation(self):
        from argparse import Namespace
        from whisperlivekit.core import TranscriptionEngine

        engine=TranscriptionEngine.__new__(TranscriptionEngine)
        engine.args=Namespace(target_language="zh")
        engine.translation_model=object()
        engine.asr=object()
        engine.config=SimpleNamespace(target_language="")

        class BaseProcessor:
            def __init__(self,**kwargs):
                self.engine=kwargs["transcription_engine"]
                self.translation_queue=bool(self.engine.args.target_language)

        processor_type=_desktop_audio_processor(BaseProcessor,TranscriptionEngine)
        off=processor_type(transcription_engine=engine,target_language="")
        on=processor_type(transcription_engine=engine,target_language="en")
        off_again=processor_type(transcription_engine=engine,target_language="")
        legacy=processor_type(transcription_engine=engine)
        self.assertFalse(off.translation_queue)
        self.assertIsNone(off.engine.translation_model)
        self.assertTrue(on.translation_queue)
        self.assertIs(on.engine.translation_model,engine.translation_model)
        self.assertEqual(on.engine.args.target_language,"en")
        self.assertFalse(off_again.translation_queue)
        self.assertIsNone(off_again.engine.translation_model)
        self.assertTrue(legacy.translation_queue)
        self.assertIs(legacy.engine.translation_model,engine.translation_model)
        self.assertEqual(legacy.engine.args.target_language,"zh")
        self.assertIs(engine.translation_model,on.engine.translation_model)
        self.assertEqual(engine.args.target_language,"zh")

    def test_prepare_endpoint_refuses_missing_local_model_without_downloading(self):
        application, engine, _config = self._build_managed_app()
        with tempfile.TemporaryDirectory() as folder, \
             patch("app.native_models.NLLB_MODEL_DIR", __import__("pathlib").Path(folder)), \
             patch("nllw.load_model") as load:
            body = json.dumps({"source": "en", "target": "zh"}).encode()
            events, call = asgi_request(application, "/desktop/prepare-translation", body=body)
            asyncio.run(call())
            status, payload = result(events)
            self.assertEqual(status, 409)
            self.assertIn("未安装", payload["detail"])
            load.assert_not_called()
            self.assertIsNone(engine.translation_model)

    def test_prepare_endpoint_rejects_missing_management_token(self):
        application, _engine, _config = self._build_managed_app()
        events, call = asgi_request(application, "/desktop/prepare-translation", token=None)
        asyncio.run(call())
        self.assertEqual(result(events)[0], 401)

    def test_session_control_accepts_translation_mode_and_language_options_live(self):
        control = SessionControl()
        control.configure({**DEFAULTS, "translation_mode": "off", "target_language": "zh"})
        before = control.revision
        control.update_options({"translation_mode": "local", "asr_model": "large"})
        revision, current = control.snapshot()
        self.assertEqual(revision, before + 1)
        self.assertEqual(current["translation_mode"], "local")
        self.assertEqual(current["target_language"], "zh")
        self.assertEqual(current["asr_model"], DEFAULTS["asr_model"])

    def test_live_translation_toggle_changes_stream_target_and_preserves_rows(self):
        import numpy as np
        from app.session import run_session

        settings={**DEFAULTS,'source_mode':'system','source_language':'en',
                  'target_language':'zh','translation_mode':'off','server_url':'http://local',
                  'save_records':False,'long_meeting_mode':False}
        control=SessionControl()
        events=[]
        targets=[]

        async def capture(*_args,**_kwargs):
            yield np.ones(1600,dtype=np.float32)
            control.update_options({'translation_mode':'local'})
            yield np.ones(1600,dtype=np.float32)

        async def native(_base,chunks,_language,target,on_snapshot,**_kwargs):
            targets.append(target)
            async for _chunk in chunks:
                index=len(targets)
                on_snapshot({'lines':[{'id':f'row-{index}','text':f'line {index}',
                                       'start':0,'end':.1,'speaker':1,
                                       'translation':'translated' if target else ''}]})

        with patch('app.session.capture_chunks',capture), \
             patch('app.native_client.stream_native',native):
            asyncio.run(run_session(settings,events.append,control))
        final=next(event for event in reversed(events) if event.get('type')=='captions')
        self.assertEqual(targets,['','zh'])
        self.assertEqual([row['source'] for row in final['rows']],['line 1','line 2'])

    def test_off_and_local_translation_share_engine_fingerprint_but_model_change_does_not(self):
        manager = ServerManager()
        base = {**DEFAULTS, "source_language": "en", "target_language": "zh",
                "translation_mode": "off", "asr_model": "small"}
        off = manager.signature(__import__("app.wlk_config", fromlist=["make_config"]).make_config(base), base)
        local_settings = {**base, "translation_mode": "local", "target_language": "fr"}
        local = manager.signature(__import__("app.wlk_config", fromlist=["make_config"]).make_config(local_settings), local_settings)
        changed_settings = {**local_settings, "asr_model": "medium"}
        changed = manager.signature(__import__("app.wlk_config", fromlist=["make_config"]).make_config(changed_settings), changed_settings)
        self.assertEqual(off, local)
        self.assertNotEqual(local, changed)
        manager.deleteLater()

    def test_mode_switch_reuses_shared_service_even_while_a_meeting_is_active(self):
        manager = _ActiveManager()
        off = {**DEFAULTS, "source_language": "en", "target_language": "zh",
               "translation_mode": "off", "asr_model": "small"}
        local = {**off, "translation_mode": "local", "target_language": "fr"}
        from app.wlk_config import make_config
        manager.fingerprint = manager.signature(make_config(off), off)
        manager.ready = True
        manager.url = "http://127.0.0.1:8000"
        manager.prepared_translation_providers={'nllb'}

        class Active:
            def state(self):
                return QProcess.ProcessState.Running
            def property(self, _name):
                return True

        manager.sessions = [Active()]
        callbacks = []
        with patch.object(manager, "stop") as stop:
            manager.ensure(local, callbacks.append, self.fail)
        self.assertEqual(callbacks, [manager.url])
        stop.assert_not_called()
        manager.deleteLater()

    def test_ensure_waits_for_translation_preparation_when_resuming_from_off(self):
        manager = _ActiveManager()
        network = _Network()
        manager.network = network
        off = {**DEFAULTS, "source_language": "en", "target_language": "zh",
               "translation_mode": "off", "asr_model": "small"}
        local = {**off, "translation_mode": "local"}
        from app.wlk_config import make_config
        manager.fingerprint=manager.signature(make_config(off),off)
        manager.ready=True
        manager.url="http://127.0.0.1:8000"
        manager.management_token=TOKEN
        manager.sessions=[]
        callbacks=[]
        with patch.object(manager,"stop") as stop:
            manager.ensure(local,lambda url: callbacks.append(url),self.fail)
            self.assertEqual(callbacks,[])
            self.assertIn('/desktop/prepare-translation',network.request.url().toString())
            network.reply.finished.emit()
        self.assertEqual(callbacks,[manager.url])
        self.assertIn('nllb',manager.prepared_translation_providers)
        stop.assert_not_called()
        manager.deleteLater()

    def test_prepare_translation_posts_authenticated_parameters_and_calls_ready_async(self):
        manager = ServerManager()
        network = _Network()
        manager.network = network
        manager.ready = True
        manager.url = "http://127.0.0.1:8123"
        manager.management_token = TOKEN
        settings = {**DEFAULTS, "server_url": "", "source_mode": "both",
                    "source_language": "en", "mic_language": "zh",
                    "target_language": "zh", "mic_target_language": "en"}
        calls = []
        manager.prepare_translation(settings, "local", lambda url: calls.append(("ready", url)),
                                   lambda error: calls.append(("error", error)))
        self.assertEqual(calls, [])
        self.assertIn("/desktop/prepare-translation", network.request.url().toString())
        self.assertEqual(network.request.rawHeader(b"Authorization"), f"Bearer {TOKEN}".encode())
        payload = json.loads(network.body)
        self.assertEqual(payload["source_languages"], ["en", "zh"])
        self.assertEqual(payload["target_languages"], ["en", "zh"])
        network.reply.finished.emit()
        self.assertEqual(calls, [("ready", manager.url)])
        manager.deleteLater()

    def test_prepare_translation_allows_auto_detection_and_sends_no_fake_source(self):
        manager = ServerManager()
        network = _Network()
        manager.network = network
        manager.ready = True
        manager.url = "http://127.0.0.1:8123"
        manager.management_token = TOKEN
        settings = {**DEFAULTS, "source_language": "auto", "target_language": "zh",
                    "wlk": {}}
        from app.wlk_config import make_config
        baseline={**settings,"translation_mode":"off"}
        manager.fingerprint=manager.signature(make_config(baseline),baseline)
        calls = []
        manager.prepare_translation(settings, calls.append, calls.append)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(network.body)["source_languages"], [])
        manager.deleteLater()

    def test_prepare_translation_reports_local_provider_without_loading_nllb(self):
        manager = ServerManager()
        settings = {**DEFAULTS, "translation_provider": "lmstudio"}
        manager.ready = True
        manager.url = "http://127.0.0.1:8123"
        calls = []
        with patch.object(manager, "_post_prepare_translation") as post:
            manager.prepare_translation(settings, lambda url: calls.append(url), calls.append)
        post.assert_not_called()
        self.assertEqual(calls, [manager.url])
        manager.deleteLater()

    def test_prepare_translation_is_management_authenticated(self):
        async def run():
            upstream = SimpleNamespace(calls=0)

            async def app(scope, receive, send):
                upstream.calls += 1
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"{}"})

            middleware = DesktopLifecycleMiddleware(app, TOKEN)
            events, call = asgi_request(middleware, "/desktop/prepare-translation", token=None)
            await call()
            self.assertEqual(result(events)[0], 401)
            events, call = asgi_request(middleware, "/desktop/prepare-translation")
            await call()
            self.assertEqual(result(events)[0], 200)
            self.assertEqual(upstream.calls, 1)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
