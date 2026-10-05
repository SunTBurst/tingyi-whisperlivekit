import asyncio
import io
import json
import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QProcess
from PyQt6.QtWidgets import QApplication

from app.server import DesktopLifecycleMiddleware
from app.server_manager import ServerManager


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QT_APP = QApplication.instance() or QApplication([])
TOKEN = "lifecycle-test-token"


def asgi_request(app, path, *, method="GET", token=TOKEN, scope_type="http", hold=None):
    events = []
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    scope = {"type": scope_type, "path": path, "method": method, "headers": headers,
             "query_string": b"", "http_version": "1.1", "scheme": "http",
             "server": ("localhost", 8000), "client": ("127.0.0.1", 30000)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event):
        events.append(event)

    async def run():
        await app(scope, receive, send)

    return events, run


def response(events):
    start = next(event for event in events if event["type"] == "http.response.start")
    body = next(event["body"] for event in events if event["type"] == "http.response.body")
    return start["status"], json.loads(body)


class BlockingASGI:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, scope, receive, send):
        self.entered.set()
        await self.release.wait()
        if scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
        else:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


class LifecycleMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_rest_request_blocks_prepare_and_then_gate_rejects_new_work(self):
        upstream = BlockingASGI()
        app = DesktopLifecycleMiddleware(upstream, TOKEN)
        _, start_rest = asgi_request(app, "/v1/audio/transcriptions", method="POST")
        active = asyncio.create_task(start_rest())
        await upstream.entered.wait()

        events, status_call = asgi_request(app, "/desktop/status")
        await status_call()
        self.assertEqual(response(events), (200, {"active_sessions": 1, "restarting": False}))

        events, prepare_call = asgi_request(app, "/desktop/prepare-restart", method="POST")
        await prepare_call()
        self.assertEqual(response(events), (409, {"active_sessions": 1, "restarting": False}))

        upstream.release.set()
        await active
        events, prepare_call = asgi_request(app, "/desktop/prepare-restart", method="POST")
        await prepare_call()
        self.assertEqual(response(events), (200, {"active_sessions": 0, "restarting": True}))
        events, denied_call = asgi_request(app, "/asr", scope_type="websocket")
        await denied_call()
        self.assertEqual(events, [{"type": "websocket.close", "code": 1013,
                                  "reason": "server is restarting"}])

    async def test_management_routes_require_the_private_bearer_token(self):
        app = DesktopLifecycleMiddleware(BlockingASGI(), TOKEN)
        events, call = asgi_request(app, "/desktop/status", token=None)
        await call()
        self.assertEqual(response(events), (401, {"error": "unauthorized"}))

    async def test_websocket_session_is_counted_until_disconnect(self):
        upstream = BlockingASGI()
        app = DesktopLifecycleMiddleware(upstream, TOKEN)
        _, start_ws = asgi_request(app, "/asr", scope_type="websocket")
        active = asyncio.create_task(start_ws())
        await upstream.entered.wait()
        events, prepare_call = asgi_request(app, "/desktop/prepare-restart", method="POST")
        await prepare_call()
        self.assertEqual(response(events)[0], 409)
        upstream.release.set()
        await active
        events, status_call = asgi_request(app, "/desktop/status")
        await status_call()
        self.assertEqual(response(events)[1]["active_sessions"], 0)

    async def test_unrelated_routes_do_not_block_restart(self):
        app = DesktopLifecycleMiddleware(BlockingASGI(), TOKEN)
        events, call = asgi_request(app, "/health")
        task = asyncio.create_task(call())
        await app.app.entered.wait()
        status_events, status_call = asgi_request(app, "/desktop/status")
        await status_call()
        self.assertEqual(response(status_events)[1]["active_sessions"], 0)
        app.app.release.set()
        await task


class FakeManager(ServerManager):
    def __init__(self):
        super().__init__()
        self.fake_active = True

    @property
    def active(self):
        return self.fake_active


class FakeSessionProcess:
    def __init__(self, state, uses_server=True):
        self._state = state
        self._uses_server = uses_server

    def state(self):
        return self._state

    def property(self, name):
        return self._uses_server if name == "uses_server" else None


class ServerManagerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()

    def tearDown(self):
        self.manager.timer.stop()
        if self.manager.process.state() != QProcess.ProcessState.NotRunning:
            self.manager.process.kill()
            self.manager.process.waitForFinished(1000)

    @staticmethod
    def config(backend="whisper"):
        return SimpleNamespace(backend=backend, lan="en", target_language="zh",
                               backend_policy="simulstreaming", direct_english_translation=False,
                               host="127.0.0.1", port=8000, ssl_certfile=None,
                               diarization=False, diarization_backend="sortformer")

    def test_different_model_is_rejected_while_first_server_is_still_loading(self):
        first_ready = lambda _url: None
        first_error = lambda _message: None
        self.manager.fingerprint = self.manager.signature(self.config("whisper"), {})
        self.manager.pending = [(first_ready, first_error)]
        errors = []
        with patch("app.server_manager.make_config", return_value=self.config("faster-whisper")), \
             patch.object(self.manager, "stop") as stop:
            self.manager.ensure({}, lambda _url: self.fail("must not deliver old callback to new server"), errors.append)
        self.assertEqual(self.manager.pending, [(first_ready, first_error)])
        self.assertEqual(len(errors), 1)
        stop.assert_not_called()

    def test_simul_language_change_reuses_service_used_by_another_meeting(self):
        config=self.config()
        config.model_size='small'
        self.manager.fingerprint=self.manager.signature(config,{})
        self.manager.ready=True
        self.manager.url='http://127.0.0.1:8000'
        self.manager.prepared_translation_providers={'nllb'}
        self.manager.sessions=[FakeSessionProcess(QProcess.ProcessState.Running,True)]
        selected=self.config()
        selected.model_size='small'
        selected.lan='zh'
        selected.target_language='en'
        ready=[]
        with patch('app.server_manager.make_config',return_value=selected), \
             patch.object(self.manager,'stop') as stop:
            self.manager.ensure({},ready.append,self.fail)
        self.assertEqual(ready,[self.manager.url])
        stop.assert_not_called()
        selected.model_size='medium'
        self.assertNotEqual(self.manager.signature(selected,{}),self.manager.fingerprint)

    def test_old_fingerprint_is_not_queued_after_restart_has_been_approved(self):
        old_config = self.config("whisper")
        next_config = self.config("faster-whisper")
        self.manager.ready = False
        self.manager.fingerprint = self.manager.signature(old_config, {})
        self.manager.next_settings = {"asr_model": "small"}
        self.manager.next_signature = self.manager.signature(next_config, {})
        queued = [(lambda _url: None, lambda _message: None)]
        self.manager.pending = queued[:]
        errors = []
        with patch("app.server_manager.make_config", return_value=old_config):
            self.manager.ensure({}, lambda _url: self.fail("old fingerprint must not bind to new service"), errors.append)
        self.assertEqual(self.manager.pending, queued)
        self.assertEqual(len(errors), 1)

    def test_only_running_sessions_that_still_use_the_server_block_restart(self):
        self.manager.sessions = [
            FakeSessionProcess(QProcess.ProcessState.Running, True),
            FakeSessionProcess(QProcess.ProcessState.Running, False),
            FakeSessionProcess(QProcess.ProcessState.NotRunning, True),
        ]
        self.assertTrue(self.manager.has_active_local_sessions())
        self.manager.sessions = [
            FakeSessionProcess(QProcess.ProcessState.Running, False),
            FakeSessionProcess(QProcess.ProcessState.NotRunning, True),
        ]
        self.assertFalse(self.manager.has_active_local_sessions())

    def test_restart_token_is_sent_only_as_a_bearer_header(self):
        self.manager.ready = True
        self.manager.url = "http://127.0.0.1:8000"
        self.manager.management_token = TOKEN
        response_body = io.BytesIO(b'{"active_sessions":0,"restarting":true}')
        with patch("app.server_manager.urlopen", return_value=response_body) as open_url:
            self.assertTrue(self.manager.prepare_restart())
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, request.full_url)

    def test_failed_to_start_clears_restart_reservation_and_emits_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            request_path = Path(folder) / "settings.json"
            self.manager.request_path = request_path
            request_path.write_text("{}", encoding="utf-8")
            self.manager.pending = [(lambda _url: None, lambda _message: None)]
            self.manager.next_settings = {"asr_model": "small"}
            stopped = []
            self.manager.stopped.connect(lambda: stopped.append(True))
            self.manager.process_error(QProcess.ProcessError.FailedToStart)
            self.assertEqual(self.manager.pending, [])
            self.assertIsNone(self.manager.next_settings)
            self.assertFalse(request_path.exists())
            self.assertEqual(stopped, [True])

    def test_user_stop_cancels_a_staged_model_switch(self):
        self.manager.fake_active = False
        self.manager.next_settings = {"asr_model": "small"}
        self.manager.next_signature = "small-signature"
        self.manager.pending = [(lambda _url: self.fail("shutdown must not launch pending session"), None)]
        stopped = []
        self.manager.stopped.connect(lambda: stopped.append(True))
        self.manager.stop()
        self.assertIsNone(self.manager.next_settings)
        self.assertIsNone(self.manager.next_signature)
        self.assertEqual(self.manager.pending, [])
        self.assertEqual(stopped, [True])


if __name__ == "__main__":
    unittest.main()
