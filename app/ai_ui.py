"""Optional meeting question, summary, and translation dialog for LM Studio."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from app.llm_client import LLMCancelledError, LLMError, LMStudioClient
from app.appearance import watch_theme
from app.dialogs import QFileDialog
from app.settings import ROOT

_LLM_JOB_GATE = threading.BoundedSemaphore(1)


class _WorkerSignals(QObject):
    delta = pyqtSignal(str)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()


class AIModelDialog(QDialog):
    """Independent optional text-AI UI; it never edits original transcript rows."""

    settings_changed = pyqtSignal(dict)

    def __init__(self, settings: dict, get_rows: callable, get_record_path: callable, parent=None):
        super().__init__(parent)
        self.setWindowTitle("会议 AI：问答、摘要与翻译")
        self.resize(760, 720)
        self.settings = dict(settings or {})
        self.get_rows = get_rows
        self.get_record_path = get_record_path
        self.client_factory = LMStudioClient
        self._worker_thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._signals: _WorkerSignals | None = None
        self._closing = False
        self._job_kind = ""
        self._job_context: list[dict] = []
        self._job_prompt = ""
        self._job_input = ""
        self._last_output = ""
        self._last_kind = ""
        self._last_context: list[dict] = []

        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(10)

        connection = QFormLayout()
        self.url_edit = QLineEdit(str(self.settings.get("llm_url") or "http://127.0.0.1:1234/v1"))
        self.url_edit.setObjectName("llmUrl")
        connection.addRow("LM Studio 服务地址", self.url_edit)
        token_row = QHBoxLayout()
        self.llm_token = QLineEdit(str(self.settings.get("llm_api_token") or ""))
        self.llm_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_token.setPlaceholderText("可选；仅在请求头中发送，不写入日志")
        token_row.addWidget(self.llm_token, 1)
        self.connect_button = QPushButton("测试连接并刷新模型")
        self.connect_button.clicked.connect(self.connect_models)
        token_row.addWidget(self.connect_button)
        connection.addRow("可选认证", token_row)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("llmModel")
        model_row.addWidget(self.model_combo, 1)
        model_status = str(self.settings.get("llm_model") or "")
        if model_status:
            self.model_combo.addItem(model_status + "（加载状态未知）", model_status)
        connection.addRow("问答 / 摘要文本模型", model_row)
        self.connection_status = QLabel("模型列表来自服务端；可见不代表当前已加载。")
        self.connection_status.setWordWrap(True)
        connection.addRow("连接状态", self.connection_status)

        limits_row = QHBoxLayout()
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(self._configured_int("llm_timeout", 120, 1, 600))
        limits_row.addWidget(QLabel("超时"))
        limits_row.addWidget(self.timeout_spin)
        self.context_spin = QSpinBox()
        self.context_spin.setRange(1000, 2_000_000)
        self.context_spin.setSingleStep(1000)
        self.context_spin.setSuffix(" 字符上下文上限")
        self.context_spin.setValue(self._configured_int("llm_context_chars", 24000, 1000, 2_000_000))
        limits_row.addWidget(QLabel("范围上限"))
        limits_row.addWidget(self.context_spin, 1)
        connection.addRow("请求限制", limits_row)
        root_layout.addLayout(connection)

        scope_row = QHBoxLayout()
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("当前会议", "current")
        self.scope_combo.addItem("指定时间范围", "time")
        self.scope_combo.addItem("已存会议", "saved")
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        scope_row.addWidget(QLabel("会议范围"))
        scope_row.addWidget(self.scope_combo)
        self.range_start = QLineEdit("00:00:00")
        self.range_end = QLineEdit("23:59:59")
        self.range_start.setInputMask("00:00:00;_")
        self.range_end.setInputMask("00:00:00;_")
        self.range_start.setEnabled(False)
        self.range_end.setEnabled(False)
        scope_row.addWidget(QLabel("从"))
        scope_row.addWidget(self.range_start)
        scope_row.addWidget(QLabel("到"))
        scope_row.addWidget(self.range_end)
        root_layout.addLayout(scope_row)

        self.question_edit = QPlainTextEdit()
        self.question_edit.setPlaceholderText("围绕会议字幕提问。回答会引用 [字幕编号]、时间和参会者；记录中没有的信息会说明未提及。")
        self.question_edit.setMaximumHeight(90)
        root_layout.addWidget(self.question_edit)
        actions = QHBoxLayout()
        self.ask_button = QPushButton("提问")
        self.ask_button.clicked.connect(self.ask)
        self.summary_button = QPushButton("生成摘要")
        self.summary_button.clicked.connect(self.summarize)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.ask_button)
        actions.addWidget(self.summary_button)
        actions.addWidget(self.cancel_button)
        root_layout.addLayout(actions)

        translation_layout = QGridLayout()
        self.translation_text = QPlainTextEdit()
        self.translation_text.setPlaceholderText("可选翻译：在此粘贴需要翻译的内容。")
        self.translation_text.setMaximumHeight(70)
        translation_layout.addWidget(self.translation_text, 0, 0, 1, 5)
        self.source_language = QLineEdit(str(self.settings.get("llm_translation_source") or "自动识别"))
        self.target_language = QLineEdit(str(self.settings.get("llm_translation_target") or "中文"))
        self.translation_button = QPushButton("用 LM Studio 翻译")
        self.translation_button.clicked.connect(self.translate)
        translation_layout.addWidget(QLabel("源语言"), 1, 0)
        translation_layout.addWidget(self.source_language, 1, 1)
        translation_layout.addWidget(QLabel("目标语言"), 1, 2)
        translation_layout.addWidget(self.target_language, 1, 3)
        translation_layout.addWidget(self.translation_button, 1, 4)
        root_layout.addLayout(translation_layout)

        self.result_view = QPlainTextEdit()
        self.result_view.setObjectName("aiResult")
        self.result_view.setReadOnly(True)
        self.result_warning = QLabel("AI 生成内容 · 请核对事实与引用；不属于原始会议记录。")
        self.result_warning.setObjectName("aiReviewWarning")
        self.result_warning.setWordWrap(True)
        root_layout.addWidget(self.result_warning)
        root_layout.addWidget(self.result_view, 1)
        footer = QHBoxLayout()
        self.status_label = QLabel("AI 文本任务独立于原始听写；结果单独保存。")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.copy_button = QPushButton("复制结果")
        self.copy_button.clicked.connect(self.copy_result)
        self.export_button = QPushButton("导出结果")
        self.export_button.clicked.connect(self.export_result)
        footer.addWidget(self.copy_button)
        footer.addWidget(self.export_button)
        root_layout.addLayout(footer)

        self.translation_provider = QComboBox()
        self.translation_provider.addItem("本地 NLLB", "nllb")
        self.translation_provider.addItem("LM Studio", "lmstudio")
        self.translation_provider.setCurrentIndex(self.translation_provider.findData(
            self.settings.get("translation_provider", "nllb")))
        self.fallback_check = QCheckBox("LM Studio 失败时回退到本地 NLLB，并显示回退状态")
        self.fallback_check.setChecked(bool(self.settings.get("llm_fallback", False)))
        translation_options = QHBoxLayout()
        translation_options.addWidget(QLabel("语音翻译后端"))
        translation_options.addWidget(self.translation_provider)
        translation_options.addWidget(self.fallback_check, 1)
        root_layout.addLayout(translation_options)

        self.url_edit.textChanged.connect(self._emit_settings_changed)
        self.llm_token.textChanged.connect(self._emit_settings_changed)
        self.timeout_spin.valueChanged.connect(self._emit_settings_changed)
        self.context_spin.valueChanged.connect(self._emit_settings_changed)
        self.model_combo.currentIndexChanged.connect(self._emit_settings_changed)
        self.translation_provider.currentIndexChanged.connect(self._emit_settings_changed)
        self.fallback_check.toggled.connect(self._emit_settings_changed)
        self._scope_changed()
        watch_theme(self)

    def _configured_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            return min(maximum, max(minimum, int(self.settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    def values(self) -> dict:
        model = self.model_combo.currentData()
        return {
            "llm_url": self.url_edit.text().strip() or "http://127.0.0.1:1234/v1",
            "llm_model": str(model or "").strip(),
            "llm_api_token": self.llm_token.text(),
            "llm_timeout": self.timeout_spin.value(),
            "llm_context_chars": self.context_spin.value(),
            "translation_provider": self.translation_provider.currentData() or "nllb",
            "llm_fallback": self.fallback_check.isChecked(),
        }

    def _emit_settings_changed(self, *_args):
        self.settings_changed.emit(self.values())

    def _scope_changed(self, *_args):
        enabled = self.scope_combo.currentData() == "time"
        self.range_start.setEnabled(enabled)
        self.range_end.setEnabled(enabled)

    def _client(self, *, require_model=True):
        config = self.values()
        if require_model and not config["llm_model"]:
            raise LLMError("请先连接 LM Studio 并选择一个问答 / 摘要文本模型。")
        return self.client_factory(config)

    def connect_models(self):
        try:
            client = self._client(require_model=False)
        except LLMError as exc:
            self.connection_status.setText(str(exc))
            return
        self._start_job("models", lambda cancel, _piece: client.list_models(cancel))

    def _read_rows(self, saved=False) -> list[dict]:
        if saved:
            path = self.get_record_path() if callable(self.get_record_path) else None
            if not path:
                raise ValueError("没有可读取的已存会议记录。")
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("无法读取所选会议记录；原文件未被修改。") from exc
            rows = payload.get("rows", []) if isinstance(payload, dict) else payload
        else:
            rows = self.get_rows() if callable(self.get_rows) else []
            if isinstance(rows, dict):
                rows = rows.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("会议记录的字幕列表格式不正确。")
        return [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _seconds(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "0").strip().replace(",", ".")
        try:
            if ":" in text:
                result = 0.0
                for part in text.split(":"):
                    result = result * 60 + float(part)
                return result
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_clock(value: str) -> float:
        parts = value.strip().split(":")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise ValueError("时间范围请使用 HH:MM:SS 格式。")
        hours, minutes, seconds = map(int, parts)
        if minutes > 59 or seconds > 59:
            raise ValueError("时间范围中的分钟和秒数必须小于 60。")
        return hours * 3600 + minutes * 60 + seconds

    def _selected_rows(self) -> list[dict]:
        mode = self.scope_combo.currentData()
        rows = self._read_rows(saved=(mode == "saved"))
        if mode == "time":
            start = self._parse_clock(self.range_start.text())
            end = self._parse_clock(self.range_end.text())
            if end < start:
                raise ValueError("结束时间不能早于开始时间。")
            rows = [row for row in rows if start <= self._seconds(row.get("start", row.get("time"))) <= end]
        if not rows:
            raise ValueError("所选范围内没有可用于 AI 处理的字幕。")
        return rows

    @staticmethod
    def _citation(row: dict) -> str:
        row_id = str(row.get("id") or row.get("row_id") or "未知编号")
        try:
            seconds = max(0, int(AIModelDialog._seconds(row.get("start", row.get("time")))))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            stamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except (TypeError, ValueError):
            stamp = "未知时间"
        speaker = str(row.get("participant_name") or row.get("speaker_name") or row.get("speaker") or "未知发言人")
        source = str(row.get("source") or row.get("text") or "")
        return f"[{row_id}] {stamp} | {speaker}: {source}"

    def _context_for_question(self, question: str) -> str:
        lines = [self._citation(row) for row in self._selected_rows()]
        context = "\n".join(lines)
        if len(context) + len(question) > self.context_spin.value():
            raise ValueError("该范围超出上下文字符上限；请缩小时间范围后再试，系统不会截掉会议内容。")
        return ("仅根据以下会议字幕回答。重要判断附上 [字幕编号]、时间和发言人；记录未提供的信息请明确说未提及，"
                "原文明说负责人未分配时才说‘未指定’，没有提负责人时说‘未提及’，不得从未决定日期推断负责人未指定。"
                "不要推测负责人、期限或事实。\n\n会议字幕：\n" + context + "\n\n问题：\n" + question.strip())

    def ask(self):
        question = self.question_edit.toPlainText().strip()
        if not question:
            self.status_label.setText("请输入要询问的问题。")
            return
        try:
            rows = self._selected_rows()
            prompt = self._context_for_question(question)
            client = self._client()
        except (LLMError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        messages = [
            {"role": "system", "content": (
                "你是严谨的会议记录助手。只依据提供的字幕回答，并用 [row_id] 引用；"
                "原文明说负责人未分配时才说‘未指定’，没有提负责人时说‘未提及’，不能从未决定日期推断负责人未指定。"
                "字幕未提及的负责人或期限应明确说明未提及。")},
            {"role": "user", "content": prompt},
        ]
        self._job_context = rows
        self._job_prompt = question
        self._job_input = ""
        self._start_job("question", lambda cancel, piece: self._run_chat(client, messages, cancel, piece))

    def _run_chat(self, client, messages, cancel, on_piece):
        result = []
        for piece in client.stream_chat(messages, cancel):
            if cancel.is_set():
                break
            result.append(piece)
            on_piece(piece)
        return "".join(result).strip()

    def summarize(self):
        try:
            rows = self._selected_rows()
            client = self._client()
        except (LLMError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        self._job_context = rows
        self._job_prompt = "会议摘要"
        self._job_input = ""
        self._start_job("summary", lambda cancel, _piece: client.summarize(rows, cancel))

    def translate(self):
        text = self.translation_text.toPlainText().strip()
        if not text:
            self.status_label.setText("请输入需要翻译的内容。")
            return
        try:
            client = self._client()
        except LLMError as exc:
            self.status_label.setText(str(exc))
            return
        source, target = self.source_language.text().strip(), self.target_language.text().strip()
        self._job_context = []
        self._job_prompt = f"{source} → {target}"
        self._job_input = text

        def operation(cancel, on_piece):
            result = client.translate(text, source, target, cancel)
            on_piece(result)
            return result

        self._start_job("translation", operation)

    def _start_job(self, kind: str, operation):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._job_kind = kind
        self._cancel_event = threading.Event()
        # Keep the relay alive independently from the dialog until the worker exits.
        self._signals = _WorkerSignals()
        self._signals.delta.connect(self._append_piece)
        self._signals.result.connect(self._complete_job)
        self._signals.error.connect(self._fail_job)
        self._signals.finished.connect(self._worker_finished)
        if kind != "models":
            self.result_view.clear()
        self._set_busy(True)
        self.status_label.setText("正在连接 LM Studio…" if kind == "models" else "正在处理所选会议范围…")
        signals, cancel = self._signals, self._cancel_event

        def run():
            acquired = False
            try:
                while not cancel.is_set():
                    if _LLM_JOB_GATE.acquire(timeout=0.1):
                        acquired = True
                        break
                if not acquired:
                    raise LLMCancelledError("AI 任务在排队期间已取消。")
                result = operation(cancel, signals.delta.emit)
                signals.result.emit(result)
            except LLMCancelledError:
                signals.error.emit("__cancelled__")
            except Exception as exc:
                signals.error.emit(str(exc) if isinstance(exc, LLMError) else "AI 任务失败，请检查服务和所选范围。")
            finally:
                if acquired:
                    _LLM_JOB_GATE.release()
                signals.finished.emit()

        self._worker_thread = threading.Thread(target=run, name="meeting-ai-" + kind, daemon=True)
        self._worker_thread.start()

    def _append_piece(self, piece: str):
        if not self._closing and piece:
            self.result_view.moveCursor(self.result_view.textCursor().MoveOperation.End)
            self.result_view.insertPlainText(piece)
            self.result_view.ensureCursorVisible()

    def _complete_job(self, result):
        if self._closing:
            return
        if self._cancel_event and self._cancel_event.is_set():
            self.status_label.setText("已取消；原始会议记录未改变。")
            return
        if self._job_kind == "models":
            models = result if isinstance(result, list) else []
            current = self.values().get("llm_model", "")
            with QSignalBlocker(self.model_combo):
                self.model_combo.clear()
                for model in models:
                    model_id = str(model.get("id") or "")
                    if model_id:
                        self.model_combo.addItem(model_id + "（加载状态未知）", model_id)
                if current:
                    index = self.model_combo.findData(current)
                    if index >= 0:
                        self.model_combo.setCurrentIndex(index)
                    elif not models:
                        self.model_combo.addItem(current + "（加载状态未知）", current)
            self.connection_status.setText(f"已读取 {len(models)} 个服务可见模型；当前加载状态仍未知。")
            self.status_label.setText("模型列表已刷新。")
            self._emit_settings_changed()
            return
        text = str(result or "").strip()
        if not text:
            self.status_label.setText("LM Studio 返回了空结果。")
            return
        self._last_output = text
        self._last_kind = self._job_kind
        self._last_context = list(self._job_context)
        if self.result_view.toPlainText().strip() != text:
            self.result_view.setPlainText(text)
        citation_note, citation_state = self._citation_review(text, self._last_context, self._last_kind)
        try:
            artifact = self._save_ai_artifact(self._last_kind, self._job_prompt, text, self._last_context)
        except OSError:
            self.status_label.setText("AI 生成内容 · 请核对。无法写入 records/ai；" + citation_note)
        else:
            self.status_label.setText("AI 生成内容 · 请核对。" + citation_note + " 单独保存：" + str(artifact))

    @staticmethod
    def _citation_review(text: str, rows: list[dict], kind: str) -> tuple[str, str]:
        if kind == "translation":
            return "翻译不基于会议引用；请人工核对译文。", "not_applicable"
        known = {str(row.get("id") or row.get("row_id")) for row in rows
                 if row.get("id") or row.get("row_id")}
        found = set(re.findall(r"\[([^\]\r\n]+)\]", text))
        if not found:
            if kind == "summary" and known:
                missing = sorted(known)
                shown = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
                return f"摘要未引用的片段，请核对：{len(missing)} 条（{shown}）。", "incomplete_coverage"
            return "未检测到字幕引用。", "missing"
        unknown = sorted(found - known)
        if kind == "summary":
            missing = sorted(known - found)
            parts = []
            if missing:
                shown = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
                parts.append(f"摘要未引用的片段，请核对：{len(missing)} 条（{shown}）")
            if unknown:
                parts.append("存在所选范围之外或未知的引用编号：" + "、".join(unknown[:8]) + ("…" if len(unknown) > 8 else ""))
            if parts:
                return "；".join(parts) + "。", "unknown_and_incomplete" if unknown else "incomplete_coverage"
            return "摘要引用编号与所选字幕匹配；仍请核对事实和完整性。", "matched"
        if unknown:
            return "发现所选范围之外或未知的引用编号：" + "、".join(unknown) + "。", "unknown"
        return "引用编号与所选字幕匹配；事实仍需人工核对。", "matched"

    def _save_ai_artifact(self, kind: str, prompt: str, text: str, rows: list[dict]) -> Path:
        folder = ROOT / "records" / "ai"
        folder.mkdir(parents=True, exist_ok=True)
        source_path = self.get_record_path() if callable(self.get_record_path) else None
        meeting = Path(source_path).stem if source_path else "live-meeting"
        safe_meeting = "".join(char if char.isalnum() or char in "-_" else "_" for char in meeting)[:80] or "meeting"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"{safe_meeting}-{stamp}-{uuid.uuid4().hex[:6]}.json"
        payload = {
            "kind": kind,
            "ai_generated": True,
            "review_required": True,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "meeting_record": str(source_path) if source_path else None,
            "scope": self.scope_combo.currentData(),
            "prompt": prompt,
            "input": self._job_input or None,
            "answer": text,
            "citations": [{"id": row.get("id", row.get("row_id")),
                           "start": row.get("start", row.get("time")),
                           "participant": row.get("participant_name") or row.get("speaker_name") or row.get("speaker")}
                          for row in rows],
            "model": self.values().get("llm_model"),
            "citation_review": self._citation_review(text, rows, kind)[1],
            "uncited_source_ids": sorted(
                {str(row.get("id") or row.get("row_id")) for row in rows
                 if row.get("id") or row.get("row_id")}
                - set(re.findall(r"\[([^\]\r\n]+)\]", text))
            ) if kind == "summary" else [],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def _fail_job(self, message: str):
        if self._closing:
            return
        if message == "__cancelled__" or (self._cancel_event and self._cancel_event.is_set()):
            self.status_label.setText("已取消；原始会议记录未改变。")
            return
        if self._job_kind == "models":
            self.connection_status.setText(message)
        self.status_label.setText(message)

    def _worker_finished(self):
        if self._closing:
            return
        self._set_busy(False)
        self._worker_thread = None
        self._cancel_event = None

    def _set_busy(self, active: bool):
        self.connect_button.setEnabled(not active)
        self.ask_button.setEnabled(not active)
        self.summary_button.setEnabled(not active)
        self.translation_button.setEnabled(not active)
        self.cancel_button.setEnabled(active)

    def cancel(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.status_label.setText("正在取消请求…")

    def copy_result(self):
        text = self.result_view.toPlainText()
        if text:
            QApplication.clipboard().setText("【AI生成，请核对】\n" + text)
            self.status_label.setText("AI 结果已复制。")

    def export_result(self):
        text = self.result_view.toPlainText()
        if not text:
            self.status_label.setText("当前没有可导出的 AI 结果。")
            return
        folder = ROOT / "records" / "ai"
        folder.mkdir(parents=True, exist_ok=True)
        suggested = folder / (datetime.now().strftime("meeting-ai-%Y%m%d-%H%M%S.txt"))
        path, _ = QFileDialog.getSaveFileName(self, "导出 AI 结果", str(suggested), "文本文件 (*.txt);;Markdown 文件 (*.md)")
        if not path:
            return
        try:
            Path(path).write_text("【AI生成，请核对】\n" + text + "\n", encoding="utf-8")
        except OSError:
            self.status_label.setText("导出失败；已自动保存的 AI 记录仍保留在 records/ai。")
            return
        self.status_label.setText("AI 结果已导出：" + path)

    def closeEvent(self, event):
        self._closing = True
        if self._cancel_event:
            self._cancel_event.set()
        self._worker_thread = None
        self._signals = None
        super().closeEvent(event)
