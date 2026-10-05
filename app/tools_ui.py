"""User-facing tools for the native WhisperLiveKit service and offline jobs."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QProcess, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QCheckBox,
    QScrollArea,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.server_manager import process_environment
from app.settings import ROOT
from app.dialogs import QFileDialog, QMessageBox, QInputDialog


def _python(*, speaker_runtime: bool = False) -> str:
    if speaker_runtime:
        candidate = ROOT / "runtime" / "speaker" / "Scripts" / "python.exe"
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return str(candidate)
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(candidate if candidate.exists() else sys.executable)


_SPEAKER_CLI_COMMANDS = {"bench", "diagnose", "listen", "run", "serve", "transcribe"}


def _cli_option(arguments: list[str], *flags: str) -> str | None:
    for index, item in enumerate(arguments):
        for flag in flags:
            if item == flag:
                return arguments[index + 1] if index + 1 < len(arguments) else ""
            if item.startswith(flag + "="):
                return item[len(flag) + 1:]
    return None


def _cli_config(arguments: list[str]) -> dict:
    raw = _cli_option(arguments, "--config")
    if not raw:
        return {}
    path = Path(raw)
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if is_file else json.loads(raw)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _cli_uses_speaker_runtime(command: str, arguments: list[str], settings: dict) -> bool:
    """Select NeMo's isolated interpreter only for audio work using Sortformer."""
    if command not in _SPEAKER_CLI_COMMANDS:
        return False
    wlk = settings.get("wlk") or {}
    extra = _cli_config(arguments)
    enabled = bool(extra.get("diarization", wlk.get("diarization", settings.get("diarization", False))))
    if "--diarization" in arguments or "--diarization=true" in arguments:
        enabled = True
    backend = _cli_option(arguments, "--diarization-backend")
    backend = backend or extra.get("diarization_backend") or wlk.get("diarization_backend", "sortformer")
    return enabled and backend == "sortformer"


def _parse_windows_arguments(text: str) -> list[str]:
    """Split a command line while preserving Windows backslashes in paths."""
    result = []
    for match in re.finditer(r'"(?:[^"]|"")*"|\S+', text or ""):
        token = match.group(0)
        if len(token) >= 2 and token[0] == token[-1] == '"':
            token = token[1:-1].replace('""', '"')
        result.append(token)
    return result


def _format_size(value: int | None) -> str:
    if value is None:
        return "未知"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "未知"


class ToolsDialog(QDialog):
    """Service, file, model and original CLI tools in one Chinese dialog."""

    def __init__(self, controller, parent=None):
        self.controller = controller
        self.window = controller.window
        super().__init__(parent or self.window)
        self.setWindowTitle("工具箱 · WhisperLiveKit")
        self.resize(1020, 760)
        from app.appearance import watch_theme
        watch_theme(self)
        self.settings = self.window._config_snapshot()
        self._network_manager = QNetworkAccessManager(self)
        self._network_replies: dict[Any, str] = {}
        self._network_manager.finished.connect(self._probe_finished)
        self._closing = False
        self._batch_start_pending = False
        self._batch_generation = 0
        self._batch_request_path: Path | None = None
        self._processes: list[QProcess] = []
        self._process_labels: dict[QProcess, str] = {}
        self._process_buffers: dict[QProcess, bytearray] = {}
        self._request_files: set[Path] = set()
        self._active_job: QProcess | None = None
        self._pending_reinstall_name: str | None = None
        root_layout = QVBoxLayout(self)
        title = QLabel("工具箱")
        title.setObjectName("title")
        root_layout.addWidget(title)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)
        self._build_overview_tab()
        self._build_service_tab()
        self._build_files_tab()
        self._build_models_tab()
        self._build_cli_tab()
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root_layout.addLayout(buttons)
        server = self.controller.server
        server.changed.connect(self._server_changed)
        server.error.connect(self._server_error)
        self._server_changed("服务已就绪" if server.ready else ("服务正在运行" if server.active else "本地服务尚未启动"))
        self.refresh_models()

    def _build_overview_tab(self):
        page=QWidget()
        outer=QVBoxLayout(page)
        intro=QLabel('所有工具入口已显示。点击即可打开；本地模型与服务只在需要时启动。')
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        groups=QVBoxLayout(body)
        self.overview_actions={}
        grid=QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        groups.addLayout(grid)
        def open_tab(name):
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i)==name:
                    self.tabs.setCurrentIndex(i)
                    return
        sections=[('会议与文字',[
            ('glossary','常用词库', '导入、导出词库模板，纠正常见误识别词。',self.controller.show_glossary),
            ('participants','参会者与说话人','给说话人命名、关联身份，处理同一人的重复编号。',self.controller.show_participants),
            ('ai','会议问答与摘要','使用已配置的 LM Studio 本地模型理解当前会议。',self.controller.show_ai),
            ('reapply','重新应用词库','更新已有记录的纠错文字与译文，保留原始听写。',self.controller.reprocess_glossary),
            ('cancel_rewrite','取消历史重译','停止正在进行的历史译文更新，保留已完成内容。',self.controller.cancel_history_rewrite),
        ]),('记录与恢复',[
            ('records','已保存会议','打开本机保存的会议记录，查看或导出。',self.controller.show_saved_records),
            ('manual_save','立即保存','将当前会议内容立即保存到本机。',self.controller.manual_save),
            ('recovery','异常会议恢复','查看中断或未正常结束的会议，恢复已保存内容。',lambda:self.controller.show_recovery()),
            ('export','导出当前记录','选择文字、字幕或结构化数据格式，将当前记录导出。',self.window.choose_export_format),
        ]),('字幕与模型',[
            ('subtitle','显示字幕悬浮窗','单独显示实时字幕；关闭字幕窗不会停止会议。',self._show_subtitle),
            ('subtitle_style','字幕外观','调整字幕窗大小、背景、字体、颜色与显示模式。',self._show_subtitle_settings),
            ('models','模型管理','查看已安装模型、模型目录，按需要安装本地模型。',lambda:open_tab('模型')),
        ]),('原厂库工具',[
            ('files','音频文件与批量转写','导入音频文件，转写或翻译，查看处理结果。',lambda:open_tab('文件')),
            ('service','服务与原网页','管理本地服务，打开原厂网页、扩展说明和新会议窗口。',lambda:open_tab('服务')),
            ('diagnostics','诊断与原库命令','检查环境、基准测试，并使用原厂库的命令工具。',lambda:open_tab('原库工具')),
        ])]
        index=0
        for title,items in sections:
            for key,label,description,callback in items:
                cell=QWidget()
                layout=QVBoxLayout(cell)
                layout.setContentsMargins(6,4,6,4)
                layout.setSpacing(4)
                button=QPushButton(label)
                button.setToolTip(description)
                button.clicked.connect(lambda checked=False,action=callback:action())
                detail=QLabel(title+' · '+description)
                detail.setWordWrap(True)
                detail.setObjectName('muted')
                layout.addWidget(button)
                layout.addWidget(detail)
                grid.addWidget(cell,index//3,index%3)
                self.overview_actions[key]=button
                index+=1
        options=QGroupBox('当前会议的显示与保存')
        layout=QVBoxLayout(options)
        for action in (self.controller.original_view_action,self.controller.long_mode_action):
            checkbox=QCheckBox(action.text())
            checkbox.setChecked(action.isChecked())
            checkbox.setEnabled(action.isEnabled())
            checkbox.toggled.connect(action.setChecked)
            action.toggled.connect(checkbox.setChecked)
            action.changed.connect(lambda target=checkbox,source=action:target.setEnabled(source.isEnabled()))
            layout.addWidget(checkbox)
        groups.addWidget(options)
        groups.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll,1)
        self.tabs.addTab(page,'全部工具')

    def _show_subtitle(self):
        overlay=getattr(self.window,'subtitle_overlay',None)
        if overlay is not None:
            overlay.show()
            overlay.raise_()
        else:
            self.window.toggle_compact_mode()

    def _show_subtitle_settings(self):
        self.window.show_overlay_settings()

    def _build_service_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.service_status = QLabel("本地服务尚未启动")
        self.service_url = QLabel("尚无服务地址")
        self.service_url.setTextInteractionFlags(self.service_url.textInteractionFlags() | self.service_url.textInteractionFlags().TextSelectableByMouse)
        form.addRow("运行状态", self.service_status)
        form.addRow("服务地址", self.service_url)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.start_server_button = QPushButton("启动 / 连接")
        self.start_server_button.clicked.connect(self.ensure_server)
        self.stop_server_button = QPushButton("停止本机服务")
        self.stop_server_button.clicked.connect(self.stop_server)
        self.open_web_button = QPushButton("打开原网页")
        self.open_web_button.clicked.connect(self.open_web)
        actions.addWidget(self.start_server_button)
        actions.addWidget(self.stop_server_button)
        actions.addWidget(self.open_web_button)
        layout.addLayout(actions)
        links = QHBoxLayout()
        self.extension_info_button = QPushButton("浏览器扩展安装说明")
        self.extension_info_button.clicked.connect(self.show_extension_info)
        self.extension_folder_button = QPushButton("打开扩展目录")
        self.extension_folder_button.clicked.connect(self.open_extension_folder)
        self.new_window_button = QPushButton("新建会议窗口")
        self.new_window_button.clicked.connect(self.new_meeting_window)
        links.addWidget(self.extension_info_button)
        links.addWidget(self.extension_folder_button)
        links.addWidget(self.new_window_button)
        layout.addLayout(links)
        probes = QHBoxLayout()
        self.health_button = QPushButton("检查健康状态")
        self.health_button.clicked.connect(lambda: self.probe_endpoint("/health"))
        self.models_endpoint_button = QPushButton("读取 /v1/models")
        self.models_endpoint_button.clicked.connect(lambda: self.probe_endpoint("/v1/models"))
        probes.addWidget(self.health_button)
        probes.addWidget(self.models_endpoint_button)
        layout.addLayout(probes)
        self.service_output = QPlainTextEdit()
        self.service_output.setReadOnly(True)
        self.service_output.setMaximumBlockCount(3000)
        layout.addWidget(self.service_output, 1)
        self.tabs.addTab(page, "服务")

    def _build_files_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.import_file_button = QPushButton("选择一个音频文件并开始识别")
        self.import_file_button.clicked.connect(self.import_file)
        layout.addWidget(self.import_file_button)
        select_row = QHBoxLayout()
        self.batch_add_button = QPushButton("添加多个文件")
        self.batch_add_button.clicked.connect(self.add_batch_files)
        self.batch_remove_button = QPushButton("移除所选")
        self.batch_remove_button.clicked.connect(self.remove_batch_file)
        self.batch_clear_button = QPushButton("清空列表")
        self.batch_clear_button.clicked.connect(lambda: self.batch_list.clear())
        select_row.addWidget(self.batch_add_button)
        select_row.addWidget(self.batch_remove_button)
        select_row.addWidget(self.batch_clear_button)
        layout.addLayout(select_row)
        self.batch_list = QListWidget()
        self.batch_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.batch_list, 1)
        form = QFormLayout()
        self.batch_output_dir = QLineEdit(str(ROOT / "records" / "transcribed"))
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.batch_output_dir, 1)
        choose_output = QPushButton("选择目录")
        choose_output.clicked.connect(self.choose_output_dir)
        output_layout.addWidget(choose_output)
        self.batch_format = QComboBox()
        for label, value in (("结构化 JSON（推荐）", "verbose_json"), ("文本", "text"), ("JSON", "json"),
                             ("说话人 JSON", "diarized_json"), ("SRT 字幕", "srt"), ("VTT 字幕", "vtt")):
            self.batch_format.addItem(label, value)
        self.batch_language = QLineEdit(str(self.settings.get("source_language", "en")))
        self.batch_context = QLineEdit(str(self.settings.get("context", ""))[:1000])
        self.batch_context.setPlaceholderText("术语提示，最多 1000 字符")
        form.addRow("输出目录", output_row)
        form.addRow("输出格式", self.batch_format)
        form.addRow("识别语言", self.batch_language)
        form.addRow("术语上下文", self.batch_context)
        layout.addLayout(form)
        run_row = QHBoxLayout()
        self.batch_run_button = QPushButton("开始批量转写")
        self.batch_run_button.clicked.connect(self.start_batch)
        self.batch_cancel_button = QPushButton("取消批量任务")
        self.batch_cancel_button.setEnabled(False)
        self.batch_cancel_button.clicked.connect(self.cancel_batch)
        run_row.addWidget(self.batch_run_button)
        run_row.addWidget(self.batch_cancel_button)
        layout.addLayout(run_row)
        self.batch_output = QPlainTextEdit()
        self.batch_output.setReadOnly(True)
        self.batch_output.setMaximumBlockCount(3000)
        layout.addWidget(self.batch_output, 1)
        self.tabs.addTab(page, "文件")

    def _build_models_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.model_filter = QComboBox()
        for label, value in (("已安装模型", "installed"), ("可安装模型", "available"), ("外部服务", "external")):
            self.model_filter.addItem(label, value)
        self.model_filter.currentIndexChanged.connect(self.refresh_models)
        layout.addWidget(self.model_filter)
        self.model_list = QListWidget()
        self.model_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.model_list.currentItemChanged.connect(lambda *_: self._show_model_details())
        layout.addWidget(self.model_list, 2)
        self.model_details = QLabel("选择模型查看文件、依赖和服务状态。")
        self.model_details.setObjectName("muted")
        self.model_details.setWordWrap(True)
        layout.addWidget(self.model_details)
        actions = QGridLayout()
        self.models_refresh_button = QPushButton("刷新")
        self.models_refresh_button.clicked.connect(self.refresh_models)
        self.model_download_button = QPushButton("下载 / 重装所选模型")
        self.model_download_button.clicked.connect(self.download_selected_model)
        self.model_open_button = QPushButton("打开所在文件夹")
        self.model_open_button.clicked.connect(self.open_selected_model_folder)
        self.model_copy_button = QPushButton("复制路径")
        self.model_copy_button.clicked.connect(self.copy_selected_model_path)
        self.model_register_button = QPushButton("登记已有目录")
        self.model_register_button.clicked.connect(self.register_external_directory)
        self.model_use_button = QPushButton("使用所选模型")
        self.model_use_button.clicked.connect(self.use_selected_model)
        self.model_remove_button = QPushButton("移除所选模型")
        self.model_remove_button.clicked.connect(self.remove_selected_model)
        self.cancel_job_button = QPushButton("取消当前任务")
        self.cancel_job_button.setEnabled(False)
        self.cancel_job_button.clicked.connect(self.cancel_current_job)
        self.install_speaker_button = QPushButton("说话人依赖安装说明")
        self.install_speaker_button.clicked.connect(self.open_speaker_setup)
        for index,button in enumerate((self.models_refresh_button, self.model_download_button, self.model_open_button, self.model_copy_button,
                       self.model_register_button, self.model_use_button, self.model_remove_button, self.cancel_job_button,
                       self.install_speaker_button)):
            actions.addWidget(button,index//3,index%3)
        layout.addLayout(actions)
        self.backend_list = QListWidget()
        layout.addWidget(QLabel("本机引擎依赖状态"))
        layout.addWidget(self.backend_list, 2)
        self.model_output = QPlainTextEdit()
        self.model_output.setReadOnly(True)
        self.model_output.setMaximumBlockCount(3000)
        layout.addWidget(self.model_output, 2)
        self.tabs.addTab(page, "模型")

    def _build_cli_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.cli_command = QComboBox()
        for command in ("bench", "diagnose", "check", "models", "transcribe", "listen", "run", "pull", "rm"):
            self.cli_command.addItem(command, command)
        self.cli_arguments = QLineEdit()
        self.cli_arguments.setPlaceholderText('例如 --file "C:\\audio files\\meeting.wav"')
        form.addRow("原库命令", self.cli_command)
        form.addRow("参数", self.cli_arguments)
        layout.addLayout(form)
        self.cli_preset_button = QPushButton("填入当前配置")
        self.cli_preset_button.clicked.connect(self.fill_cli_preset)
        self.cli_run_button = QPushButton("运行命令")
        self.cli_run_button.clicked.connect(self.run_cli)
        self.cli_cancel_button = QPushButton("取消命令")
        self.cli_cancel_button.setEnabled(False)
        self.cli_cancel_button.clicked.connect(self.cancel_current_job)
        actions = QHBoxLayout()
        actions.addWidget(self.cli_preset_button)
        actions.addWidget(self.cli_run_button)
        actions.addWidget(self.cli_cancel_button)
        layout.addLayout(actions)
        self.cli_output = QPlainTextEdit()
        self.cli_output.setReadOnly(True)
        self.cli_output.setMaximumBlockCount(8000)
        layout.addWidget(self.cli_output, 1)
        self.tabs.addTab(page, "原库工具")

    def _server_changed(self, text: str):
        server = self.controller.server
        self.service_status.setText(str(text))
        self.service_url.setText(server.url or "尚无服务地址")
        self.stop_server_button.setEnabled(bool(server.active and not (self.settings.get("server_url") or "").strip()))
        self.open_web_button.setEnabled(bool(server.url))
        self._show_model_details()

    def _server_error(self, message: str):
        self.service_output.appendPlainText("错误：" + str(message))
        self.service_status.setText("服务错误：" + str(message))

    def ensure_server(self):
        self.service_status.setText("正在启动或连接服务…")
        self.controller.server.ensure(self.settings, self._server_ready, self._server_error)

    def _server_ready(self, url: str):
        self.service_url.setText(str(url))
        self.service_status.setText("服务已就绪")
        self.open_web_button.setEnabled(True)
        self.service_output.appendPlainText("服务可用：" + str(url))

    def stop_server(self):
        server = self.controller.server
        if server.active and not (self.settings.get("server_url") or "").strip():
            server.stop()

    def open_web(self):
        url = self.controller.server.url
        if url:
            QDesktopServices.openUrl(QUrl(url.rstrip("/") + "/"))

    def probe_endpoint(self, endpoint: str):
        url = self.controller.server.url
        if not url:
            self.service_output.appendPlainText("请先启动或连接服务。")
            return
        token = (self.settings.get("wlk") or {}).get("api_token")
        endpoint_url = url.rstrip("/") + endpoint
        request = QNetworkRequest(QUrl(endpoint_url))
        request.setTransferTimeout(5000)
        if token:
            request.setRawHeader(b"Authorization", ("Bearer " + token).encode("utf-8"))
        self.service_output.appendPlainText("请求 " + endpoint_url)
        reply = self._network_manager.get(request)
        self._network_replies[reply] = endpoint_url

    def _probe_finished(self, reply):
        url = self._network_replies.pop(reply, "服务请求")
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        content_type = reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)
        raw = bytes(reply.readAll())
        if reply.error():
            result = {"error": reply.errorString(), "status": status}
        else:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = raw.decode("utf-8", errors="replace")
            result = {"status": status, "content_type": content_type, "body": body}
        self.service_output.appendPlainText(f"\n{url}\n{json.dumps(result, ensure_ascii=False, indent=2)}")
        reply.deleteLater()

    def show_extension_info(self):
        QMessageBox.information(self, "浏览器扩展", "扩展源文件位于 upstream/chrome-extension。请在 Chrome 扩展管理页启用开发者模式，选择“加载已解压的扩展程序”，然后选中该目录。")

    def open_extension_folder(self):
        path = ROOT / "upstream" / "chrome-extension"
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.service_output.appendPlainText(f"扩展目录不存在：{path}")

    def new_meeting_window(self):
        callback = getattr(self.controller, "new_window", None)
        if callback:
            callback()
        else:
            self.service_output.appendPlainText("当前控制器未提供新建会议窗口功能。")

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", str(ROOT), "音频文件 (*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.aac *.wma);;所有文件 (*.*)")
        if not path:
            return
        self.controller.start(self.window._config_snapshot(), path, False)
        self.accept()

    def add_batch_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加待转写音频", str(ROOT), "音频文件 (*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.aac *.wma);;所有文件 (*.*)")
        existing = {self.batch_list.item(index).text() for index in range(self.batch_list.count())}
        for path in paths:
            if path not in existing:
                self.batch_list.addItem(path)
                existing.add(path)

    def remove_batch_file(self):
        for item in self.batch_list.selectedItems():
            self.batch_list.takeItem(self.batch_list.row(item))

    def choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择转写结果目录", self.batch_output_dir.text())
        if path:
            self.batch_output_dir.setText(path)

    def start_batch(self):
        paths = [self.batch_list.item(index).text() for index in range(self.batch_list.count())]
        if not paths:
            self.batch_output.appendPlainText("请先添加要转写的文件。")
            return
        if self._batch_start_pending or (self._active_job and self._active_job.state() != QProcess.ProcessState.NotRunning):
            self.batch_output.appendPlainText("已有工具任务正在运行，请等待或先取消。")
            return
        self._batch_start_pending = True
        self.batch_run_button.setEnabled(False)
        self.batch_output.appendPlainText(f"正在启动服务并转写 {len(paths)} 个文件…")
        # Calling ensure for every batch handles stopped local services and
        # external server URLs through the same validated connection path.
        self.controller.server.ensure(
            self.settings,
            lambda url, selected=list(paths), run_id=self._batch_generation: self._launch_batch(url, selected, run_id),
            self._batch_server_error,
        )

    def _batch_server_error(self, message: str):
        self._batch_start_pending = False
        self.batch_run_button.setEnabled(True)
        self.batch_output.appendPlainText("服务错误：" + str(message))

    def _launch_batch(self, base: str, paths: list[str], generation: int):
        if self._closing or generation != self._batch_generation:
            return
        self._batch_start_pending = False
        request_data = {
            "base": base,
            "paths": paths,
            "output_dir": self.batch_output_dir.text().strip(),
            "response_format": self.batch_format.currentData(),
            "language": self.batch_language.text().strip(),
            "context": self.batch_context.text().strip()[:1000],
            "token": (self.settings.get("wlk") or {}).get("api_token"),
        }
        data_dir = ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._batch_request_path = data_dir / f"batch-request-{uuid.uuid4().hex}.json"
        self._batch_request_path.write_text(json.dumps(request_data, ensure_ascii=False), encoding="utf-8")
        self.batch_output.appendPlainText(f"服务已连接：{base}\n开始批量转写 {len(paths)} 个文件。")
        process = self._start_process(["-u", "-m", "app.batch_job", "--request", str(self._batch_request_path)], self.batch_output, "批量转写")
        if process:
            self.batch_cancel_button.setEnabled(True)
        else:
            self._batch_request_path.unlink(missing_ok=True)
            self._batch_request_path = None
            self.batch_run_button.setEnabled(True)

    def cancel_batch(self):
        process = self._active_job
        if self._batch_start_pending:
            self._batch_start_pending = False
            self._batch_generation += 1
            self.batch_run_button.setEnabled(True)
            self.batch_output.appendPlainText("已取消等待服务连接的批量任务。")
        elif process and self._process_labels.get(process) == "批量转写":
            process.kill()
            self.batch_output.appendPlainText("正在取消批量任务…")

    def refresh_models(self):
        from app.model_manager import backend_availability, installed_models
        selected_name = (self._selected_model() or {}).get("name")
        mode = self.model_filter.currentData() if hasattr(self, "model_filter") else "installed"
        availability = {item["name"]: item["available"] for item in backend_availability()}
        self.model_list.clear()
        models = installed_models()
        if mode == "installed":
            models = [model for model in models if model.get("installed") and model.get("source") != "external"]
        elif mode == "available":
            models = [model for model in models if not model.get("installed") and model.get("source") != "external"]
        else:
            models = [model for model in models if model.get("source") == "external"]
        models.sort(key=lambda model: (str(model.get("kind") or ""), str(model.get("name") or "")))
        for model in models:
            backend = str(model.get("backend") or "")
            model["dependencies_installed"] = availability.get(backend)
            state = "文件存在" if model.get("files_present") else "文件缺失"
            suffix = " · 原库管理" if model.get("managed_by") else ""
            source = " · 外部目录" if model.get("source") == "external" else ""
            item = QListWidgetItem(f"{model['name']} · {state}{source}{suffix}")
            item.setData(256, model)
            self.model_list.addItem(item)
            if model.get("name") == selected_name:
                self.model_list.setCurrentItem(item)
        self.backend_list.clear()
        for backend in backend_availability():
            state = "可用" if backend["available"] else "未安装"
            warnings = "；".join(backend.get("warnings") or [])
            description = f" · {warnings}" if warnings else ""
            self.backend_list.addItem(f"{backend['name']} · {state}{description}\n  {backend['install']}")
        self._show_model_details()

    def _selected_model(self):
        item = self.model_list.currentItem()
        return item.data(256) if item else None

    def _show_model_details(self):
        model = self._selected_model()
        if not model:
            if hasattr(self, "model_details"):
                self.model_details.setText("当前分类没有模型。可登记一个已存在的外部模型目录。")
                server = getattr(self.controller, "server", None)
                self.model_remove_button.setEnabled(not bool(server and server.active))
                self.model_use_button.setEnabled(False)
                self.model_open_button.setEnabled(False)
                self.model_copy_button.setEnabled(False)
            return
        size = model.get("size_bytes")
        size_text = _format_size(size) if size is not None else "未知"
        path = model.get("local_path") or model.get("path") or "未知路径"
        files = ", ".join(model.get("files") or []) or "未发现模型文件"
        deps = model.get("dependencies_installed")
        deps_text = "可用" if deps is True else ("缺失" if deps is False else "未知")
        valid_text = "通过" if model.get("validated") else ("待验证" if model.get("files_present") else "未验证")
        server = getattr(self.controller, "server", None)
        if server and server.active:
            active_wlk = self.settings.get("wlk") or {}
            configured_path = active_wlk.get("model_dir") or active_wlk.get("model_path")
            same_path = bool(configured_path and str(Path(str(configured_path)).resolve(strict=False)) == str(Path(str(path)).resolve(strict=False)))
            same_size = bool(model.get("kind") == "asr" and active_wlk.get("model_size") == self.settings.get("asr_model"))
            loaded_text = "活动服务配置指向此模型" if same_path or same_size else "服务活动中，当前配置未指向此模型"
        else:
            loaded_text = "当前无活动服务（未加载）"
        self.model_details.setText(
            f"用途：{model.get('kind') or '未知'}　格式/后端：{model.get('format') or model.get('backend') or '未知'}　大小：{size_text}\n"
            f"路径：{path}\n文件：{files}\n文件存在：{'是' if model.get('files_present') else '否'}　校验：{valid_text}　依赖：{deps_text}　使用状态：{loaded_text}"
        )
        local_path = model.get("local_path") or model.get("path")
        self.model_open_button.setEnabled(bool(local_path and Path(local_path).exists()))
        self.model_copy_button.setEnabled(bool(local_path))
        self.model_download_button.setEnabled(model.get("source") != "external" and model.get("kind") != "speaker")
        self.model_remove_button.setEnabled(model.get("source") != "external" and bool(model.get("installed")) and not bool(server and server.active))
        self.model_use_button.setEnabled(bool(model.get("installed") and model.get("validated") and model.get("kind") in {"asr", "native-whisper"}))

    def open_selected_model_folder(self):
        model = self._selected_model() or {}
        path = model.get("local_path") or model.get("path")
        if path and Path(path).exists():
            folder = Path(path).parent if Path(path).is_file() else Path(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self.model_output.appendPlainText("模型目录不可用或未登记路径。")

    def copy_selected_model_path(self):
        model = self._selected_model() or {}
        path = model.get("local_path") or model.get("path")
        if path:
            QApplication.clipboard().setText(str(path))
            self.model_output.appendPlainText("已复制模型路径。")
        else:
            self.model_output.appendPlainText("该来源未提供模型路径。")

    def register_external_directory(self):
        path = QFileDialog.getExistingDirectory(self, "登记已有模型目录", str(ROOT))
        if not path:
            return
        default_name = Path(path).name
        name, accepted = QInputDialog.getText(self, "登记外部模型", "模型名称", text=default_name)
        if not accepted:
            return
        kind, accepted = QInputDialog.getItem(self, "模型用途", "用途", ["asr", "translation", "speaker", "text"], 0, False)
        if not accepted:
            return
        default_backend = {"asr": "faster-whisper", "translation": "nllw/ctranslate2", "speaker": "nemo-sortformer", "text": "unknown"}[kind]
        backend, accepted = QInputDialog.getText(self, "模型后端", "后端", text=default_backend)
        if not accepted or not backend.strip():
            return
        try:
            from app.model_registry import register_external_model, validate_external_model
            record = register_external_model(path, name=name, kind=kind, backend=backend)
            status = validate_external_model(record)
            self.model_output.appendPlainText("已登记外部路径；文件不会复制或删除。" + str(status.get("validation_message") or ""))
            self.model_filter.setCurrentIndex(self.model_filter.findData("external"))
            self.refresh_models()
        except (OSError, ValueError) as exc:
            self.model_output.appendPlainText("登记失败：" + str(exc))

    def use_selected_model(self):
        model = self._selected_model() or {}
        if not model or not model.get("installed") or not model.get("validated"):
            self.model_output.appendPlainText("所选模型文件尚未通过格式检查，不能应用。")
            return
        if model.get("kind") not in {"asr", "native-whisper"}:
            self.model_output.appendPlainText("当前设置只能应用语音识别模型；其他用途不会写入识别配置。")
            return
        if model.get("dependencies_installed") is False:
            self.model_output.appendPlainText("所选模型的运行依赖不可用，不能应用。")
            return
        if getattr(self.window, "running", False) and not getattr(self.window, "paused", False):
            self.model_output.appendPlainText("请先暂停会议，再更换模型。")
            return
        path = str(model.get("local_path") or model.get("path") or "")
        kind = str(model.get("kind") or "")
        wlk = dict((self.window.settings.get("wlk") or {}))
        backend = str(model.get("backend") or wlk.get("backend") or "faster-whisper")
        wlk["backend"] = backend
        name = str(model.get("name") or "")
        if kind in {"asr", "native-whisper"}:
            size = name.removeprefix("whisper-").removeprefix("native-whisper-")
            if size and size != name:
                wlk["model_size"] = size
                self.window.settings["asr_model"] = size
                model_combo = getattr(self.window, "model_combo", None)
                if model_combo is not None:
                    model_combo.blockSignals(True)
                    try:
                        index = model_combo.findData(size)
                        if index < 0:
                            model_combo.addItem(name or size, size)
                            index = model_combo.findData(size)
                        model_combo.setCurrentIndex(index)
                    finally:
                        model_combo.blockSignals(False)
            if backend == "whisper" and Path(path).is_file():
                wlk["model_path"] = path
                wlk["model_dir"] = None
            else:
                wlk["model_dir"] = path
                wlk["model_path"] = None
        else:
            wlk["model_dir"] = path
        self.window.settings["wlk"] = wlk
        snapshot = self.window._config_snapshot() if hasattr(self.window, "_config_snapshot") else dict(self.window.settings)
        if hasattr(self.window, "settings"):
            self.window.settings.update(snapshot)
        signal = getattr(self.window, "config_changed", None)
        if signal is not None:
            signal.emit(dict(snapshot))
        self.model_output.appendPlainText(f"已将 {name or path} 设为后续会议使用模型。")

    def download_selected_model(self):
        model = self._selected_model()
        if not model:
            self.model_output.appendPlainText("请先选择一个模型。")
            return
        if model.get("managed_by") == "wlk pull":
            command = ["-u", "-m", "app.native_cli", "--settings", self._write_cli_settings(), "pull", model["name"]]
        elif model.get("source") == "external":
            self.model_output.appendPlainText("外部目录只登记和引用；请在来源服务管理该模型文件。")
            return
        else:
            if model.get("installed") and model.get("local_path"):
                answer = QMessageBox.question(
                    self, "重新安装模型", f"将移除并重新下载 {model['name']}。如果下载失败，原文件不会保留。继续吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self._pending_reinstall_name = str(model["name"])
                self._start_process(["-u", "-m", "app.model_job", "remove", model["local_path"]], self.model_output, "重装模型")
                return
            command = ["-u", "-m", "app.model_job", "download", model["name"]]
        self._start_process(command, self.model_output, "模型任务")

    def remove_selected_model(self):
        model = self._selected_model()
        if not model or model.get("source") == "external" or not model.get("installed") or not model.get("local_path"):
            self.model_output.appendPlainText("请选择已安装且有明确本地路径的模型。")
            return
        if self.controller.server.active:
            self.model_output.appendPlainText("服务运行期间不能移除模型，请先停止本机服务。")
            return
        self._start_process(["-u", "-m", "app.model_job", "remove", model["local_path"]], self.model_output, "移除模型")

    def open_speaker_setup(self):
        self._start_process(["-u", str(ROOT / "scripts" / "setup_speaker.py"), "--all"], self.model_output, "安装说话人依赖")

    def fill_cli_preset(self):
        model = str(self.settings.get("wlk", {}).get("model_size") or self.settings.get("asr_model", "medium"))
        backend = str(self.settings.get("wlk", {}).get("backend") or "faster-whisper")
        language = str(self.settings.get("source_language", "auto"))
        self.cli_command.setCurrentIndex(self.cli_command.findData("bench"))
        self.cli_arguments.setText(f'--quick --model {model} --backend {backend} --languages {language}')

    def _write_cli_settings(self):
        directory = ROOT / "data"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"cli-request-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        self._request_files.add(path)
        return str(path)

    def run_cli(self):
        command = self.cli_command.currentData()
        args = _parse_windows_arguments(self.cli_arguments.text())
        if command == "bench" and _cli_option(args, "--config") is None:
            try:
                from app.wlk_config import config_values
                args.extend(["--config", json.dumps(config_values(self.settings), ensure_ascii=False)])
            except Exception as exc:
                self.cli_output.appendPlainText("生成基准测试配置失败：" + str(exc))
                return
        use_speaker_runtime = _cli_uses_speaker_runtime(command, args, self.settings)
        try:
            program = _python(speaker_runtime=use_speaker_runtime)
        except FileNotFoundError:
            self.cli_output.appendPlainText("Sortformer CLI 需要说话人隔离环境，请先运行“安装说话人依赖”。")
            return
        self._start_process(
            ["-u", "-m", "app.native_cli", "--settings", self._write_cli_settings(), command, *args],
            self.cli_output,
            "原库命令",
            program=program,
        )

    def _start_process(self, args: list[str], output: QPlainTextEdit, label: str, *, program: str | None = None):
        if self._active_job and self._active_job.state() != QProcess.ProcessState.NotRunning:
            output.appendPlainText("已有工具进程正在运行，请等待或先取消。")
            return None
        process = QProcess(self.controller)
        process.setWorkingDirectory(str(ROOT))
        process.setProcessEnvironment(process_environment())
        self._process_buffers[process] = bytearray()
        process.readyReadStandardOutput.connect(lambda p=process: self._append_process_output(p, output, False))
        process.readyReadStandardError.connect(lambda p=process: self._append_process_output(p, output, True))
        process.finished.connect(lambda code, status, p=process: self._process_finished(p, output, label, code))
        process.errorOccurred.connect(lambda error, p=process: self._process_error(p, output, label, error))
        self._processes.append(process)
        self._process_labels[process] = label
        self._active_job = process
        self.cancel_job_button.setEnabled(label in {"模型任务", "移除模型", "重装模型", "安装说话人依赖"})
        self.cli_cancel_button.setEnabled(label == "原库命令")
        if label == "批量转写":
            self.batch_cancel_button.setEnabled(True)
        output.appendPlainText(f"开始：{label}")
        process.start(program or _python(), args)
        return process

    def _append_process_output(self, process: QProcess, output: QPlainTextEdit, stderr: bool):
        if self._closing:
            if stderr:
                process.readAllStandardError()
            else:
                process.readAllStandardOutput()
            return
        data = bytes(process.readAllStandardError() if stderr else process.readAllStandardOutput())
        if data:
            if stderr:
                output.appendPlainText(data.decode("utf-8", errors="replace").rstrip())
                return
            buffer = self._process_buffers.setdefault(process, bytearray())
            buffer.extend(data)
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                self._process_buffers[process] = buffer = bytearray(remainder)
                self._write_process_line(process, output, raw.decode("utf-8", errors="replace").rstrip())

    def _write_process_line(self, process, output, line):
        if not line:
            return
        label = self._process_labels.get(process)
        if label in {"批量转写", "模型任务", "移除模型", "安装说话人依赖"}:
            try:
                event = json.loads(line)
            except ValueError:
                output.appendPlainText(line)
                return
            if label == "批量转写":
                stage = event.get("stage") or event.get("state") or "进度"
                if stage == "complete":
                    output.appendPlainText("批量转写完成：\n" + "\n".join(map(str, event.get("files", []))))
                elif stage == "failed":
                    output.appendPlainText("转写失败：" + str(event.get("message", "未知错误")))
                else:
                    output.appendPlainText(f"{stage}：{event.get('file') or event.get('name') or event.get('message') or ''}")
            else:
                output.appendPlainText(json.dumps(event, ensure_ascii=False))
        else:
            output.appendPlainText(line)

    def _process_error(self, process, output, label, error):
        if not self._closing:
            output.appendPlainText(f"{label}启动失败：{error}")
        if process.state() == QProcess.ProcessState.NotRunning:
            self._process_finished(process, output, label, -1)

    def _process_finished(self, process: QProcess, output: QPlainTextEdit, label: str, exit_code: int):
        buffer = self._process_buffers.pop(process, bytearray())
        if buffer and not self._closing:
            self._write_process_line(process, output, bytes(buffer).decode("utf-8", errors="replace").rstrip())
        if not self._closing:
            output.appendPlainText(f"{label}结束（退出码 {exit_code}）。")
        if process in self._processes:
            self._processes.remove(process)
        self._process_labels.pop(process, None)
        if self._active_job is process:
            self._active_job = None
        self.cancel_job_button.setEnabled(False)
        self.cli_cancel_button.setEnabled(False)
        if label == "批量转写":
            self.batch_cancel_button.setEnabled(False)
            self.batch_run_button.setEnabled(True)
            self._batch_start_pending = False
        process.deleteLater()
        if self._batch_request_path:
            self._batch_request_path.unlink(missing_ok=True)
            self._batch_request_path = None
        for path in tuple(self._request_files):
            path.unlink(missing_ok=True)
            self._request_files.discard(path)
        if not self._closing and label == "重装模型" and exit_code == 0 and self._pending_reinstall_name:
            name = self._pending_reinstall_name
            self._pending_reinstall_name = None
            self._start_process(["-u", "-m", "app.model_job", "download", name], self.model_output, "模型任务")
        elif label == "重装模型":
            self._pending_reinstall_name = None
        if not self._closing and label in {"模型任务", "移除模型", "重装模型", "安装说话人依赖"}:
            self.refresh_models()

    def _stop_owned_jobs(self):
        self._closing = True
        self._batch_start_pending = False
        self._batch_generation += 1
        for reply in tuple(self._network_replies):
            reply.abort()
            reply.deleteLater()
        self._network_replies.clear()
        for process in tuple(self._processes):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            if process in self._processes:
                self._processes.remove(process)
            self._process_labels.pop(process, None)
            self._process_buffers.pop(process, None)
            process.deleteLater()
        for path in self._request_files:
            path.unlink(missing_ok=True)
        self._request_files.clear()
        if self._batch_request_path:
            self._batch_request_path.unlink(missing_ok=True)
            self._batch_request_path = None

    def done(self, result):
        self._active_job=None
        self.batch_run_button.setEnabled(True)
        self.batch_cancel_button.setEnabled(False)
        self.cancel_job_button.setEnabled(False)
        self.cli_cancel_button.setEnabled(False)
        self._stop_owned_jobs()
        super().done(result)

    def showEvent(self,event):
        # The complete tool window is reused; closing cancels owned jobs only.
        self._closing=False
        self.settings=self.window._config_snapshot()
        super().showEvent(event)

    def closeEvent(self, event):
        self._stop_owned_jobs()
        self._active_job=None
        self.batch_run_button.setEnabled(True)
        self.batch_cancel_button.setEnabled(False)
        self.cancel_job_button.setEnabled(False)
        self.cli_cancel_button.setEnabled(False)
        super().closeEvent(event)

    def cancel_current_job(self):
        process = self._active_job
        if process and process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            output = self.cli_output if self.cli_cancel_button.isEnabled() else self.model_output
            output.appendPlainText("正在取消当前任务…")
