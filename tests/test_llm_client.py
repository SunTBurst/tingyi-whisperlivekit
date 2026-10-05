import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.llm_client import LLMCancelledError, LLMError, LMStudioClient


class FakeLMStudio:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.stream_chunks = ["你好", "，世界"]
        self.stream_delay = 0
        self.headers_delay = 0
        self.connection_close = False
        self.chunked_response = False
        self.hold_request_body = False
        self.body_waiting = threading.Event()
        self.release_body = threading.Event()
        self.http_status = 200
        self.event_error = None
        self.handler_error = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def _send(self, status, payload):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path != "/v1/models":
                    self._send(404, {"error": {"message": "missing"}})
                    return
                self._send(200, {"data": [{"id": "visible-model", "object": "model"}]})

            def do_POST(self):
                if owner.hold_request_body:
                    owner.body_waiting.set()
                    owner.release_body.wait(5)
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                item = {"path": self.path, "headers": dict(self.headers), "body": json.loads(body)}
                owner.requests.append(item)
                if owner.http_status != 200:
                    self._send(owner.http_status, {"error": {"message": "model is not loaded"}})
                    return
                if owner.headers_delay:
                    time.sleep(owner.headers_delay)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    if owner.chunked_response:
                        self.send_header("Transfer-Encoding", "chunked")
                    if owner.connection_close:
                        self.send_header("Connection", "close")
                        self.close_connection = True
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError):
                    return
                if owner.event_error:
                    event = {"error": {"message": owner.event_error}}
                    self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    return
                chunks = owner.stream_chunks
                for index, chunk in enumerate(chunks):
                    if index and owner.stream_delay:
                        time.sleep(owner.stream_delay)
                    event = {"choices": [{"delta": {"content": chunk}, "index": 0}]}
                    try:
                        data = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8")
                        if owner.chunked_response:
                            data = f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n"
                        self.wfile.write(data)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                try:
                    data = b"data: [DONE]\n\n"
                    if owner.chunked_response:
                        data = f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n0\r\n\r\n"
                    self.wfile.write(data)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class LMStudioClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeLMStudio()
        self.addCleanup(self.fake.close)
        self.client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 2})

    def test_lists_server_visible_models_without_claiming_loaded_state(self):
        self.assertEqual(self.client.list_models(), [{"id": "visible-model", "object": "model"}])

    def test_streams_unicode_sse_and_sends_optional_bearer_token(self):
        self.fake.stream_chunks = ["会", "议摘要", "🙂"]
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model",
                                 "llm_api_token": "test-token", "llm_timeout": 2})
        result = "".join(client.stream_chat([{"role": "user", "content": "总结"}], threading.Event()))
        self.assertEqual(result, "会议摘要🙂")
        request = self.fake.requests[0]
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-token")
        self.assertTrue(request["body"]["stream"])

    def test_http_model_error_is_chinese_and_does_not_expose_token(self):
        self.fake.http_status = 400
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model",
                                 "llm_api_token": "secret-value", "llm_timeout": 2})
        with self.assertRaises(LLMError) as caught:
            list(client.stream_chat([{"role": "user", "content": "hi"}]))
        self.assertIn("模型", str(caught.exception))
        self.assertNotIn("secret-value", str(caught.exception))

    def test_sse_error_event_is_reported_as_a_chinese_model_error(self):
        self.fake.event_error = "model is not loaded"
        with self.assertRaises(LLMError) as caught:
            list(self.client.stream_chat([{"role": "user", "content": "hi"}]))
        self.assertIn("模型", str(caught.exception))

    def test_server_echoed_api_token_is_redacted_from_stream_error(self):
        self.fake.event_error = "rejected token test-token"
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model",
                                 "llm_api_token": "test-token", "llm_timeout": 2})
        with self.assertRaises(LLMError) as caught:
            list(client.stream_chat([{"role": "user", "content": "hi"}]))
        self.assertNotIn("test-token", str(caught.exception))

    def test_stream_timeout_has_a_clear_message(self):
        self.fake.stream_delay = 0.6
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 0.25})
        with self.assertRaises(LLMError) as caught:
            list(client.stream_chat([{"role": "user", "content": "hi"}]))
        self.assertIn("超时", str(caught.exception))

    def test_delayed_response_headers_longer_than_half_second_succeed_with_configured_timeout(self):
        self.fake.headers_delay = 0.7
        self.fake.stream_chunks = ["响应正常"]
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 2})
        self.assertEqual("".join(client.stream_chat([{"role": "user", "content": "hello"}])), "响应正常")

    def test_sse_inter_chunk_gap_longer_than_half_second_succeeds(self):
        self.fake.stream_chunks = ["第一片", "第二片"]
        self.fake.stream_delay = 0.65
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 2})
        self.assertEqual("".join(client.stream_chat([{"role": "user", "content": "hello"}])), "第一片第二片")

    def test_chunked_sse_response_is_decoded_without_losing_event_boundaries(self):
        self.fake.chunked_response = True
        self.fake.stream_chunks = ["分块", "传输"]
        self.assertEqual("".join(self.client.stream_chat([{"role": "user", "content": "hello"}])), "分块传输")

    def test_delayed_headers_timeout_within_configured_total_deadline(self):
        self.fake.headers_delay = 1.0
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 0.4})
        started = time.monotonic()
        with self.assertRaises(LLMError) as caught:
            list(client.stream_chat([{"role": "user", "content": "hello"}]))
        elapsed = time.monotonic() - started
        self.assertIn("超时", str(caught.exception))
        self.assertGreaterEqual(elapsed, 0.3)
        self.assertLess(elapsed, 0.9)

    def test_cancel_interrupts_delayed_headers_promptly_even_when_response_will_close(self):
        self.fake.headers_delay = 2.0
        self.fake.connection_close = True
        cancel = threading.Event()
        failures = []

        def consume():
            try:
                list(self.client.stream_chat([{"role": "user", "content": "hello"}], cancel))
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=consume)
        worker.start()
        deadline = time.monotonic() + 1
        while not self.fake.requests and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
        worker.join(timeout=0.4)
        self.assertFalse(worker.is_alive(), "cancellation should interrupt getresponse, not wait for timeout")
        self.assertFalse(failures)

    def test_cancel_interrupts_a_blocked_request_body_send(self):
        self.fake.hold_request_body = True
        cancel = threading.Event()
        failures = []
        payload = "x" * (8 * 1024 * 1024)

        def consume():
            try:
                list(self.client.stream_chat([{"role": "user", "content": payload}], cancel))
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=consume)
        worker.start()
        self.assertTrue(self.fake.body_waiting.wait(1))
        cancel.set()
        worker.join(timeout=0.5)
        self.fake.release_body.set()
        self.assertFalse(worker.is_alive(), "cancellation should interrupt a request send waiting for socket capacity")
        self.assertFalse(failures)

    def test_cancel_interrupts_host_resolution_wait(self):
        entered = threading.Event()
        release = threading.Event()
        cancel = threading.Event()
        failures = []

        def delayed_resolution(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [(2, 1, 6, "", ("127.0.0.1", self.fake.server.server_port))]

        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 5})

        def consume():
            try:
                list(client.stream_chat([{"role": "user", "content": "hello"}], cancel))
            except Exception as exc:
                failures.append(exc)

        with patch("app.llm_client.socket.getaddrinfo", side_effect=delayed_resolution):
            worker = threading.Thread(target=consume)
            worker.start()
            self.assertTrue(entered.wait(1))
            cancel.set()
            worker.join(timeout=0.5)
        release.set()
        self.assertFalse(worker.is_alive(), "cancel should release the caller even if the resolver thread is still waiting")
        self.assertFalse(failures)

    def test_total_deadline_covers_host_resolution(self):
        entered = threading.Event()
        release = threading.Event()
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 0.4})

        def delayed_resolution(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [(2, 1, 6, "", ("127.0.0.1", self.fake.server.server_port))]

        started = time.monotonic()
        with patch("app.llm_client.socket.getaddrinfo", side_effect=delayed_resolution):
            with self.assertRaises(LLMError) as caught:
                list(client.stream_chat([{"role": "user", "content": "hello"}]))
        elapsed = time.monotonic() - started
        release.set()
        self.assertTrue(entered.is_set())
        self.assertIn("超时", str(caught.exception))
        self.assertLess(elapsed, 0.9)

    def test_total_deadline_covers_a_blocked_request_body_send(self):
        self.fake.hold_request_body = True
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model", "llm_timeout": 0.4})
        started = time.monotonic()
        try:
            with self.assertRaises(LLMError) as caught:
                list(client.stream_chat([{"role": "user", "content": "x" * (8 * 1024 * 1024)}]))
        finally:
            self.fake.release_body.set()
        elapsed = time.monotonic() - started
        self.assertTrue(self.fake.body_waiting.is_set())
        self.assertIn("超时", str(caught.exception))
        self.assertLess(elapsed, 0.9)

    def test_cancel_stops_stream_and_closes_server_connection(self):
        self.fake.stream_delay = 0.15
        self.fake.stream_chunks = ["one", "two", "three", "four"]
        cancel = threading.Event()
        received = []

        def consume():
            received.extend(self.client.stream_chat([{"role": "user", "content": "long"}], cancel))

        worker = threading.Thread(target=consume)
        worker.start()
        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertLess(len(received), 4)

    def test_translate_uses_source_and_target_in_prompt(self):
        self.fake.stream_chunks = ["مرحبا"]
        result = self.client.translate("hello", "English", "Arabic")
        self.assertEqual(result, "مرحبا")
        content = self.fake.requests[-1]["body"]["messages"][-1]["content"]
        self.assertIn("English", content)
        self.assertIn("Arabic", content)
        self.assertIn("hello", content)

    def test_summary_chunks_every_row_and_explicitly_splits_long_text(self):
        self.fake.stream_chunks = ["完成"]
        client = LMStudioClient({"llm_url": self.fake.url, "llm_model": "visible-model",
                                 "llm_timeout": 2, "llm_context_chars": 1000})
        rows = [
            {"id": "r-1", "start": 1, "end": 2, "participant_name": "甲", "source": "甲说" + "甲" * 700},
            {"id": "r-2", "start": 4, "end": 5, "speaker_name": "乙", "source": "乙提出待确认事项"},
        ]
        self.assertEqual(client.summarize(rows), "完成")
        combined = "\n".join(json.dumps(req["body"]["messages"], ensure_ascii=False) for req in self.fake.requests)
        self.assertIn("[r-1]", combined)
        self.assertIn("[r-2]", combined)
        self.assertIn("甲", combined)
        self.assertIn("乙", combined)
        self.assertIn("第", combined)
        self.assertGreater(len(self.fake.requests), 1)
        instructions = self.fake.requests[0]["body"]["messages"][0]["content"]
        self.assertIn("逐项保留", instructions)
        self.assertIn("未决定", instructions)
        self.assertIn("未指定", instructions)
        self.assertIn("未提及", instructions)
        self.assertIn("不得从未决定日期推断", instructions)

    def test_empty_model_response_is_an_error(self):
        self.fake.stream_chunks = []
        with self.assertRaises(LLMError):
            self.client.translate("hello", "en", "zh")


if __name__ == "__main__":
    unittest.main()
