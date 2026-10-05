"""Small, cancellable LM Studio client for OpenAI-compatible local APIs."""

from __future__ import annotations

import json
import errno
import select
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


class LLMError(RuntimeError):
    """A user-displayable LM Studio request failure."""


class LLMCancelledError(LLMError):
    """Raised when a synchronous text operation is explicitly cancelled."""


def _cancelled(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


class _RequestTimedOut(Exception):
    pass


def _check_request(cancel, deadline):
    if _cancelled(cancel):
        raise LLMCancelledError("请求已取消。")
    if time.monotonic() >= deadline:
        raise _RequestTimedOut


def _wait_socket(sock, *, readable, writable, cancel, deadline):
    while True:
        _check_request(cancel, deadline)
        timeout = min(0.1, deadline - time.monotonic())
        try:
            ready_read, ready_write, ready_error = select.select(
                [sock] if readable else [], [sock] if writable else [], [sock], timeout
            )
        except InterruptedError:
            continue
        if ready_error:
            error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            raise OSError(error, "socket operation failed")
        if ready_read or ready_write:
            return


class _SocketHTTPResponse:
    """HTTP/1.1 response reader using raw recv so short polls remain reusable."""

    POLL_INTERVAL = 0.1
    HEADER_LIMIT = 64 * 1024
    BODY_LIMIT = 16 * 1024 * 1024

    def __init__(self, sock, cancel: threading.Event | None, deadline: float):
        self.sock = sock
        self.cancel = cancel
        self.deadline = deadline
        self.buffer = bytearray()
        self.eof = False
        self.status = 0
        self.reason = ""
        self.headers: dict[str, str] = {}

    def _check(self):
        _check_request(self.cancel, self.deadline)

    def _receive(self) -> bytes:
        while True:
            self._check()
            _wait_socket(self.sock, readable=True, writable=False,
                         cancel=self.cancel, deadline=self.deadline)
            try:
                data = self.sock.recv(64 * 1024)
            except (BlockingIOError, ssl.SSLWantReadError):
                continue
            except ssl.SSLWantWriteError:
                _wait_socket(self.sock, readable=False, writable=True,
                             cancel=self.cancel, deadline=self.deadline)
            except OSError as exc:
                self._check()
                raise LLMError("连接 LM Studio 时发生错误，请检查服务状态。") from exc
            if not data:
                self.eof = True
            return data

    def _ensure(self, count: int):
        while len(self.buffer) < count and not self.eof:
            self.buffer.extend(self._receive())

    def _read_until(self, marker: bytes, limit: int) -> bytes:
        while True:
            found = self.buffer.find(marker)
            if found >= 0:
                end = found + len(marker)
                result = bytes(self.buffer[:end])
                del self.buffer[:end]
                return result
            if len(self.buffer) > limit:
                raise LLMError("LM Studio 返回的 HTTP 头过长。")
            if self.eof:
                raise LLMError("LM Studio 返回了不完整的 HTTP 响应。")
            self.buffer.extend(self._receive())

    def _read_exact(self, count: int) -> bytes:
        if count < 0 or count > self.BODY_LIMIT:
            raise LLMError("LM Studio 返回的数据超过大小限制。")
        self._ensure(count)
        if len(self.buffer) < count:
            raise LLMError("LM Studio 返回了不完整的 HTTP 响应体。")
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def begin(self):
        block = self._read_until(b"\r\n\r\n", self.HEADER_LIMIT)
        lines = block[:-4].split(b"\r\n")
        try:
            version, status, reason = lines[0].decode("iso-8859-1").split(" ", 2)
            if not version.startswith("HTTP/"):
                raise ValueError
            self.status = int(status)
            self.reason = reason
            collected = {}
            for line in lines[1:]:
                name, value = line.split(b":", 1)
                key = name.decode("ascii").strip().lower()
                value = value.decode("iso-8859-1").strip()
                collected[key] = collected.get(key, "") + (", " if key in collected else "") + value
            self.headers = collected
        except (UnicodeDecodeError, ValueError) as exc:
            raise LLMError("LM Studio 返回了无效的 HTTP 响应头。") from exc

    def iter_body(self):
        transfer = self.headers.get("transfer-encoding", "").lower()
        if "chunked" in transfer:
            while True:
                size_line = self._read_until(b"\r\n", 128).strip()
                try:
                    size = int(size_line.split(b";", 1)[0], 16)
                except ValueError as exc:
                    raise LLMError("LM Studio 返回了无效的分块响应。") from exc
                if size == 0:
                    while self._read_until(b"\r\n", self.HEADER_LIMIT) != b"\r\n":
                        pass
                    return
                yield self._read_exact(size)
                if self._read_exact(2) != b"\r\n":
                    raise LLMError("LM Studio 返回了无效的分块边界。")
        elif "content-length" in self.headers:
            try:
                remaining = int(self.headers["content-length"])
            except ValueError as exc:
                raise LLMError("LM Studio 返回了无效的响应长度。") from exc
            if remaining < 0 or remaining > self.BODY_LIMIT:
                raise LLMError("LM Studio 返回的数据超过大小限制。")
            while remaining:
                part = self._read_exact(min(remaining, 64 * 1024))
                remaining -= len(part)
                yield part
        else:
            while not self.eof:
                if self.buffer:
                    part = bytes(self.buffer)
                    self.buffer.clear()
                    yield part
                else:
                    part = self._receive()
                    if part:
                        yield part

    def read_body(self, limit: int) -> bytes:
        result = bytearray()
        for part in self.iter_body():
            if len(result) + len(part) > limit:
                result.extend(part[:max(0, limit - len(result))])
                break
            result.extend(part)
        return bytes(result)


def _row_value(row: dict, *keys: str, default=""):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _format_time(value) -> str:
    try:
        seconds = max(0, float(value or 0))
    except (TypeError, ValueError):
        return str(value or "未知时间")
    hours, remainder = divmod(int(seconds), 3600)
    minutes, whole = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}"


class LMStudioClient:
    """Talk to LM Studio's local OpenAI-compatible models and chat endpoints."""

    def __init__(self, config: dict):
        config = dict(config or {})
        self.base_url = str(config.get("llm_url") or "http://127.0.0.1:1234/v1").strip().rstrip("/")
        self.model = str(config.get("llm_model") or "").strip()
        self.api_token = str(config.get("llm_api_token") or "").strip()
        try:
            self.timeout = max(0.25, min(600.0, float(config.get("llm_timeout", 120))))
        except (TypeError, ValueError):
            self.timeout = 120.0
        try:
            self.context_chars = max(1000, min(2_000_000, int(config.get("llm_context_chars", 24_000))))
        except (TypeError, ValueError):
            self.context_chars = 24_000

        parts = urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise LLMError("LM Studio 服务地址无效，请填写 http(s)://主机:端口/v1。")
        if parts.username or parts.password:
            raise LLMError("服务地址中不能包含账号或密码，请使用独立认证字段。")
        self._scheme = parts.scheme
        self._host = parts.hostname
        try:
            self._port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as exc:
            raise LLMError("LM Studio 服务端口无效。") from exc
        self._base_path = parts.path.rstrip("/")
        if not self._base_path:
            self._base_path = "/v1"

    def _path(self, suffix: str) -> str:
        return self._base_path + suffix

    def _headers(self, *, json_body=False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self.api_token:
            if "\r" in self.api_token or "\n" in self.api_token:
                raise LLMError("API Token 格式无效。")
            headers["Authorization"] = "Bearer " + self.api_token
        return headers

    def _resolve_addresses(self, deadline, cancel):
        completed = threading.Event()
        result = {}

        def resolve():
            try:
                result["addresses"] = socket.getaddrinfo(
                    self._host, self._port, type=socket.SOCK_STREAM
                )
            except Exception as exc:
                result["error"] = exc
            finally:
                completed.set()

        threading.Thread(target=resolve, name="lmstudio-dns", daemon=True).start()
        while not completed.wait(0.05):
            _check_request(cancel, deadline)
        _check_request(cancel, deadline)
        if "error" in result:
            raise OSError("LM Studio hostname resolution failed") from result["error"]
        return result.get("addresses", [])

    def _connect(self, deadline, cancel):
        addresses = self._resolve_addresses(deadline, cancel)
        pending = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR,
                   getattr(errno, "WSAEWOULDBLOCK", 10035)}
        last_error = None
        for family, socktype, proto, _canonname, address in addresses:
            _check_request(cancel, deadline)
            candidate = socket.socket(family, socktype, proto)
            candidate.setblocking(False)
            try:
                code = candidate.connect_ex(address)
                if code not in (0, getattr(errno, "EISCONN", 0)):
                    if code not in pending:
                        raise OSError(code, "connection failed")
                    while True:
                        _wait_socket(candidate, readable=False, writable=True,
                                     cancel=cancel, deadline=deadline)
                        code = candidate.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if code == 0:
                            break
                        if code in pending:
                            continue
                        raise OSError(code, "connection failed")
                if self._scheme == "https":
                    context = ssl.create_default_context()
                    candidate = context.wrap_socket(
                        candidate, server_hostname=self._host, do_handshake_on_connect=False
                    )
                    candidate.setblocking(False)
                    while True:
                        try:
                            candidate.do_handshake()
                            break
                        except ssl.SSLWantReadError:
                            _wait_socket(candidate, readable=True, writable=False,
                                         cancel=cancel, deadline=deadline)
                        except ssl.SSLWantWriteError:
                            _wait_socket(candidate, readable=False, writable=True,
                                         cancel=cancel, deadline=deadline)
                _check_request(cancel, deadline)
                return candidate
            except (LLMCancelledError, _RequestTimedOut):
                candidate.close()
                raise
            except OSError as exc:
                last_error = exc
                candidate.close()
        if last_error:
            raise last_error
        raise OSError("No usable address for LM Studio")

    @staticmethod
    def _send_all(sock, payload: bytes, cancel, deadline):
        offset = 0
        view = memoryview(payload)
        while offset < len(view):
            _wait_socket(sock, readable=False, writable=True, cancel=cancel, deadline=deadline)
            try:
                sent = sock.send(view[offset:])
            except ssl.SSLWantReadError:
                _wait_socket(sock, readable=True, writable=False, cancel=cancel, deadline=deadline)
                continue
            except (BlockingIOError, ssl.SSLWantWriteError):
                continue
            if not sent:
                raise OSError("Connection closed while sending request")
            offset += sent

    def _open_request(self, method: str, suffix: str, body: bytes | None, cancel):
        deadline = time.monotonic() + self.timeout
        sock = self._connect(deadline, cancel)
        try:
            host = f"[{self._host}]" if ":" in self._host else self._host
            default_port = 443 if self._scheme == "https" else 80
            if self._port != default_port:
                host += f":{self._port}"
            path = self._path(suffix)
            if "\r" in path or "\n" in path:
                raise LLMError("LM Studio 服务地址路径无效。")
            headers = self._headers(json_body=body is not None)
            lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close"]
            lines.extend(f"{name}: {value}" for name, value in headers.items())
            if body is not None:
                lines.append(f"Content-Length: {len(body)}")
            request = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
            self._send_all(sock, request + (body or b""), cancel, deadline)
            response = _SocketHTTPResponse(sock, cancel, deadline)
            response.begin()
            return sock, response
        except Exception:
            sock.close()
            raise

    def _read_error(self, response) -> str:
        try:
            payload = response.read_body(16_384).decode("utf-8", errors="replace")
        except (OSError, LLMError, LLMCancelledError, _RequestTimedOut):
            payload = ""
        message = ""
        try:
            parsed = json.loads(payload)
            error = parsed.get("error", parsed)
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("detail") or "")
            elif error:
                message = str(error)
        except (ValueError, AttributeError):
            message = payload.strip()
        # Never echo credentials if a server happens to include request headers.
        if self.api_token:
            message = message.replace(self.api_token, "[认证信息已隐藏]")
        return self._localized_detail(message)[:500]

    @staticmethod
    def _localized_detail(message: str) -> str:
        folded = message.casefold()
        if "model is not loaded" in folded or "no loaded model" in folded:
            message = "所选模型当前未加载，请在 LM Studio 中加载模型或启用即时加载。"
        elif "unauthorized" in folded or "invalid api key" in folded:
            message = "认证未通过，请检查可选 API Token。"
        elif "not found" in folded and "/v1/" in folded:
            message = "接口路径不存在，请确认服务地址以 /v1 结尾。"
        return message

    def list_models(self, cancel: threading.Event | None = None) -> list[dict]:
        """Return models visible through GET /v1/models (loaded state is unknown)."""
        if _cancelled(cancel):
            raise LLMCancelledError("模型列表请求已取消。")
        sock = None
        try:
            sock, response = self._open_request("GET", "/models", None, cancel)
            if response.status < 200 or response.status >= 300:
                detail = self._read_error(response)
                response._check()
                raise LLMError(f"读取 LM Studio 模型列表失败（HTTP {response.status}）" + (f"：{detail}" if detail else "。"))
            body = response.read_body(_SocketHTTPResponse.BODY_LIMIT)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise LLMError("LM Studio 返回的模型列表不是有效 JSON。") from exc
            models = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(models, list):
                raise LLMError("LM Studio 模型列表格式不正确。")
            response._check()
            return [dict(model) for model in models if isinstance(model, dict) and model.get("id")]
        except _RequestTimedOut as exc:
            raise LLMError("读取 LM Studio 模型列表超时。") from exc
        except LLMCancelledError:
            raise
        except LLMError:
            raise
        except (OSError, TimeoutError) as exc:
            if _cancelled(cancel):
                raise LLMCancelledError("模型列表请求已取消。") from exc
            raise LLMError("无法连接 LM Studio，请检查服务地址和服务状态。") from exc
        finally:
            if sock is not None:
                sock.close()

    def stream_chat(self, messages: list[dict], cancel: threading.Event | None = None):
        """Yield decoded text fragments from a cancellable SSE chat completion."""
        if not self.model:
            raise LLMError("请先连接 LM Studio 并选择一个文本模型。")
        if _cancelled(cancel):
            raise LLMCancelledError("请求已取消。")
        payload = json.dumps({"model": self.model, "messages": messages, "stream": True}, ensure_ascii=False).encode("utf-8")
        sock = None
        try:
            sock, response = self._open_request("POST", "/chat/completions", payload, cancel)
            if response.status < 200 or response.status >= 300:
                detail = self._read_error(response)
                response._check()
                raise LLMError(f"LM Studio 请求失败（HTTP {response.status}）" + (f"：{detail}" if detail else "。"))
            content_type = response.headers.get("content-type", "").lower()
            if "text/event-stream" not in content_type:
                detail = self._read_error(response)
                response._check()
                raise LLMError("LM Studio 未返回流式响应" + (f"：{detail}" if detail else "。"))

            pending = bytearray()
            for data in response.iter_body():
                pending.extend(data)
                while b"\n" in pending:
                    line, _, remainder = pending.partition(b"\n")
                    pending = bytearray(remainder)
                    piece = self._parse_sse_line(bytes(line).rstrip(b"\r"))
                    if piece is None:
                        continue
                    if piece is _DONE:
                        return
                    if piece:
                        yield piece
            if pending:
                piece = self._parse_sse_line(bytes(pending))
                if piece is not None and piece is not _DONE:
                    yield piece
        except LLMCancelledError:
            return
        except _RequestTimedOut as exc:
            raise LLMError("LM Studio 请求超时，请缩小会议范围或延长超时时间。") from exc
        except LLMError:
            raise
        except (OSError, TimeoutError) as exc:
            if _cancelled(cancel):
                return
            raise LLMError("连接 LM Studio 时发生错误，请检查服务状态。") from exc
        finally:
            if sock is not None:
                sock.close()

    def _parse_sse_line(self, line: bytes):
        try:
            text = line.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise LLMError("LM Studio 返回了无法解码的流式数据。") from exc
        if not text or text.startswith(":") or not text.startswith("data:"):
            return None
        data = text[5:].strip()
        if data == "[DONE]":
            return _DONE
        try:
            event = json.loads(data)
        except ValueError as exc:
            raise LLMError("LM Studio 返回了格式不正确的流式数据。") from exc
        if isinstance(event, dict) and event.get("error"):
            error = event["error"]
            detail = error.get("message", "") if isinstance(error, dict) else str(error)
            if self.api_token:
                detail = detail.replace(self.api_token, "[认证信息已隐藏]")
            detail = LMStudioClient._localized_detail(str(detail))
            raise LLMError("LM Studio 生成失败" + (f"：{detail[:500]}" if detail else "。"))
        choices = event.get("choices", []) if isinstance(event, dict) else []
        if not choices:
            return None
        delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
        content = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        return None

    def translate(self, text: str, source: str, target: str, cancel: threading.Event | None = None) -> str:
        prompt = (f"Translate the text from {source} to {target}. Return only the translation, "
                  "preserving meaning, names, punctuation, and line breaks.\n\n" + str(text))
        result = "".join(self.stream_chat([{"role": "user", "content": prompt}], cancel)).strip()
        if _cancelled(cancel):
            raise LLMCancelledError("翻译已取消。")
        if not result:
            raise LLMError("LM Studio 返回了空翻译结果。")
        return result

    @staticmethod
    def _format_row(row: dict, text: str | None = None, part: tuple[int, int] | None = None) -> str:
        row_id = str(_row_value(row, "id", "row_id", default="未知编号"))
        speaker = str(_row_value(row, "participant_name", "speaker_name", "speaker", default="未知发言人"))
        moment = _format_time(_row_value(row, "start", "time", default=""))
        value = str(_row_value(row, "source", "text", default="")) if text is None else text
        continuation = f"（第{part[0]}/{part[1]}段）" if part else ""
        return f"[{row_id}] {moment} | {speaker}{continuation}: {value}"

    def _summary_lines(self, rows: list[dict]) -> list[str]:
        # Keep a substantial reserve for system instructions and generated text.
        line_budget = max(96, self.context_chars // 3)
        lines = []
        for row in rows:
            value = str(_row_value(row, "source", "text", default=""))
            prefix = self._format_row(row, "")
            available = max(24, line_budget - len(prefix))
            pieces = [value[index:index + available] for index in range(0, len(value), available)] or [""]
            for index, piece in enumerate(pieces, start=1):
                part = (index, len(pieces)) if len(pieces) > 1 else None
                lines.append(self._format_row(row, piece, part))
        return lines

    @staticmethod
    def _pack(items: list[str], char_budget: int) -> list[str]:
        chunks, current = [], []
        current_size = 0
        for item in items:
            size = len(item) + (1 if current else 0)
            if current and current_size + size > char_budget:
                chunks.append("\n".join(current))
                current, current_size = [], 0
                size = len(item)
            current.append(item)
            current_size += size
        if current:
            chunks.append("\n".join(current))
        return chunks

    def _summarize_chunk(self, transcript: str, cancel) -> str:
        messages = [
            {"role": "system", "content": (
                "你是会议记录助手。只依据提供的字幕总结，逐项保留每段中明确的决议、负责人、事项、时间或截止时间，"
                "以及尚未决定、尚未指定负责人、仍待确认的事项；不要因其未解决而省略。每项后标注对应的原字幕 [row_id]。"
                "汇总前序摘要时也要保留已标注的重要事项。只有原文明说时才写负责人或期限；原文明说任务无人负责时写‘负责人未指定’，"
                "原文没有提负责人时写‘负责人未提及’，不得从未决定日期推断负责人未指定。"
                "不要补造事实、身份、负责人或期限。")},
            {"role": "user", "content": "请总结以下会议字幕，保留引用编号：\n" + transcript},
        ]
        result = "".join(self.stream_chat(messages, cancel)).strip()
        if _cancelled(cancel):
            raise LLMCancelledError("摘要已取消。")
        if not result:
            raise LLMError("LM Studio 返回了空摘要。")
        return result

    def summarize(self, rows: list[dict], cancel: threading.Event | None = None) -> str:
        """Summarize every supplied row in bounded, explicitly identified chunks."""
        if not rows:
            raise LLMError("当前范围内没有可用于摘要的字幕。")
        summaries = []
        for chunk in self._pack(self._summary_lines(rows), max(128, self.context_chars // 3)):
            if _cancelled(cancel):
                raise LLMCancelledError("摘要已取消。")
            summaries.append(self._summarize_chunk(chunk, cancel))
        while len(summaries) > 1:
            batches = self._pack(summaries, max(256, self.context_chars // 3))
            summaries = [self._summarize_chunk(batch, cancel) for batch in batches]
        if _cancelled(cancel):
            raise LLMCancelledError("摘要已取消。")
        return summaries[0]


_DONE = object()
