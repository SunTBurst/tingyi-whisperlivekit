"""PyQt6 interface for the local meeting caption application."""

from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
import ast
import sys
from typing import Any

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from app.language_picker import LanguageField, LanguagePicker, display_label
from app.theme import STYLE, THEME_CHOICES, normalize_theme, palette_for, style_for
from app.appearance import current_theme, set_theme, watch_theme
from app.icons import app_icon, set_button_icon, swap_icon
from app.dialogs import QFileDialog, QMessageBox, QInputDialog
from app.interaction import attach_help
from app.subtitle_overlay import SubtitleOverlay
from app.device_refresh import DeviceRefreshBridge, start_device_refresh


APP_ROOT = Path(__file__).resolve().parent.parent
RECORDS_DIR = APP_ROOT / "records"

_LANGUAGE_NAMES_ZH = {
    "en": "英语", "zh": "中文", "es": "西班牙语", "ru": "俄语", "ko": "韩语", "fr": "法语",
    "ja": "日语", "pt": "葡萄牙语", "tr": "土耳其语", "pl": "波兰语", "ca": "加泰罗尼亚语",
    "nl": "荷兰语", "ar": "阿拉伯语", "sv": "瑞典语", "it": "意大利语", "id": "印尼语",
    "hi": "印地语", "fi": "芬兰语", "vi": "越南语", "he": "希伯来语", "uk": "乌克兰语",
    "el": "希腊语", "ms": "马来语", "cs": "捷克语", "ro": "罗马尼亚语", "da": "丹麦语",
    "hu": "匈牙利语", "ta": "泰米尔语", "no": "挪威语", "th": "泰语", "ur": "乌尔都语",
    "hr": "克罗地亚语", "bg": "保加利亚语", "lt": "立陶宛语", "la": "拉丁语", "mi": "毛利语",
    "ml": "马拉雅拉姆语", "cy": "威尔士语", "sk": "斯洛伐克语", "te": "泰卢固语", "fa": "波斯语",
    "lv": "拉脱维亚语", "bn": "孟加拉语", "sr": "塞尔维亚语", "az": "阿塞拜疆语", "sl": "斯洛文尼亚语",
    "kn": "卡纳达语", "et": "爱沙尼亚语", "mk": "马其顿语", "br": "布列塔尼语", "eu": "巴斯克语",
    "is": "冰岛语", "hy": "亚美尼亚语", "ne": "尼泊尔语", "mn": "蒙古语", "bs": "波斯尼亚语",
    "kk": "哈萨克语", "sq": "阿尔巴尼亚语", "sw": "斯瓦希里语", "gl": "加利西亚语", "mr": "马拉地语",
    "pa": "旁遮普语", "si": "僧伽罗语", "km": "高棉语", "sn": "绍纳语", "yo": "约鲁巴语",
    "so": "索马里语", "af": "南非荷兰语", "oc": "奥克语", "ka": "格鲁吉亚语", "be": "白俄罗斯语",
    "tg": "塔吉克语", "sd": "信德语", "gu": "古吉拉特语", "am": "阿姆哈拉语", "yi": "意第绪语",
    "lo": "老挝语", "uz": "乌兹别克语", "fo": "法罗语", "ht": "海地克里奥尔语", "ps": "普什图语",
    "tk": "土库曼语", "nn": "新挪威语", "mt": "马耳他语", "sa": "梵语", "lb": "卢森堡语",
    "my": "缅甸语", "bo": "藏语", "tl": "他加禄语", "mg": "马达加斯加语", "as": "阿萨姆语",
    "tt": "鞑靼语", "haw": "夏威夷语", "ln": "林加拉语", "ha": "豪萨语", "ba": "巴什基尔语",
    "jw": "爪哇语", "su": "巽他语", "yue": "粤语",
}


def _literal_language_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LANGUAGES" for t in n.targets))
        return ast.literal_eval(node.value)
    except (OSError, SyntaxError, ValueError, StopIteration):
        return {}


def _whisper_language_catalog() -> list[tuple[str, str]]:
    """Expose only languages accepted by the Whisper ASR source-language menu."""
    whisper_path = APP_ROOT / "upstream/whisperlivekit/whisper/tokenizer.py"
    whisper_languages = _literal_language_map(whisper_path)
    catalog = {"auto": "自动识别", "zh": "中文", "en": "英语", "ar": "阿拉伯语", "ja": "日语", "ko": "韩语"}
    for code, name in whisper_languages.items():
        catalog[code] = _LANGUAGE_NAMES_ZH.get(code, str(name).title())
    return [("自动识别", "auto"), *((label, code) for code, label in sorted(catalog.items()) if code != "auto")]


def _nllb_language_catalog() -> list[tuple[str, str]]:
    """Read NLLB output codes without importing torch or translation models."""
    catalog: dict[str, str] = {}
    for base in sys.path:
        nllb_path = Path(base) / "nllw" / "languages.py"
        if not nllb_path.is_file():
            continue
        raw = _literal_language_map(nllb_path)
        for item in raw:
            name = str(item.get("name") or "")
            language_code = str(item.get("language_code") or "")
            label = _LANGUAGE_NAMES_ZH.get(language_code, name or language_code)
            for code in (str(item.get("nllb") or ""), language_code):
                if code:
                    catalog.setdefault(code, label)
        if catalog:
            break
    if not catalog:
        catalog = {code: label for label, code in _whisper_language_catalog() if code != "auto"}
    catalog.setdefault("zh", "中文（简体）")
    for alias in ("zh-CN", "zh-Hans", "zh-SG", "cmn", "cmn-Hans"):
        catalog.setdefault(alias, "中文（简体）")
    for alias in ("zh-TW", "zh-Hant", "zh-HK", "cmn-Hant"):
        catalog.setdefault(alias, "中文（繁體）")
    return sorted(((label, code) for code, label in catalog.items()), key=lambda item: (item[0], item[1]))


def _language_catalog() -> list[tuple[str, str]]:
    """Combined catalog retained for callers that need to inspect both sets."""
    combined = {code: label for label, code in _whisper_language_catalog()}
    combined.update({code: label for label, code in _nllb_language_catalog()})
    return [(label, code) for code, label in sorted(combined.items())]


def _ensure_language_catalogs() -> None:
    global LANGUAGES, TARGET_LANGUAGES
    if LANGUAGES is None:
        LANGUAGES = _whisper_language_catalog()
    if TARGET_LANGUAGES is None:
        TARGET_LANGUAGES = _nllb_language_catalog()


LANGUAGES: list[tuple[str, str]] | None = None
TARGET_LANGUAGES: list[tuple[str, str]] | None = None

def _add_combo_items(combo: QComboBox, values: list[tuple[str, Any]]) -> None:
    for label, value in values:
        combo.addItem(label, value)


def _set_combo_data(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _language_control(picker: LanguagePicker) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(picker)
    layout.addWidget(picker.status_label)
    return wrapper


class SettingsDialog(QDialog):
    """Chinese settings for meeting display and the underlying WLK pipeline."""

    def __init__(self, settings: dict[str, Any], devices: dict[str, list[str]], parent=None,
                 session_active: bool = False, session_paused: bool = False):
        super().__init__(parent)
        _ensure_language_catalogs()
        self.setWindowTitle("设置")
        self.setMinimumSize(760, 650)
        self.resize(900, 760)
        watch_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)
        title = QLabel("会议与识别设置")
        title.setObjectName("title")
        layout.addWidget(title)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        basic_page = QWidget()
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_scroll = QScrollArea()
        basic_scroll.setWidgetResizable(True)
        basic_content = QWidget()
        basic_content_layout = QVBoxLayout(basic_content)
        basic_content_layout.setContentsMargins(8, 8, 8, 8)
        self.common_tabs = QTabWidget()
        basic_content_layout.addWidget(self.common_tabs)
        forms: dict[str, QFormLayout] = {}
        for key, title_text in (("devices", "设备与语言"), ("display", "记录与字幕"), ("pipeline", "识别与翻译")):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(14, 14, 14, 14)
            page_layout.setSpacing(12)
            category_form = QFormLayout()
            category_form.setHorizontalSpacing(18)
            category_form.setVerticalSpacing(13)
            page_layout.addLayout(category_form)
            page_layout.addStretch(1)
            self.common_tabs.addTab(page, title_text)
            forms[key] = category_form
        device_form = forms["devices"]
        display_form = forms["display"]
        form = forms["pipeline"]
        basic_scroll.setWidget(basic_content)
        basic_layout.addWidget(basic_scroll, 1)
        self.basic_form = form
        self.output_device = QComboBox()
        self.mic_device = QComboBox()
        for combo, options, key in (
            (self.output_device, devices.get("output", []), "output_device"),
            (self.mic_device, devices.get("input", []), "mic_device"),
        ):
            self._populate_device_combo(combo, options, settings.get(key))
        self.device_refresh_button = QPushButton("刷新设备")
        self.device_refresh_status = QLabel("")
        self.device_refresh_status.setObjectName("muted")
        device_action_row = QWidget()
        device_action_layout = QHBoxLayout(device_action_row)
        device_action_layout.setContentsMargins(0, 0, 0, 0)
        device_action_layout.addWidget(self.device_refresh_button)
        device_action_layout.addWidget(self.device_refresh_status, 1)
        self.device_refresh_button.clicked.connect(self.refresh_devices)
        self.model_combo = QComboBox()
        for label, value in [("Tiny · 轻量", "tiny"), ("Tiny EN", "tiny.en"), ("Base", "base"), ("Base EN", "base.en"),
                             ("Small", "small"), ("Small EN", "small.en"), ("Medium", "medium"), ("Medium EN", "medium.en"),
                             ("Large v1", "large-v1"), ("Large v2", "large-v2"), ("Large v3", "large-v3"), ("Large v3 Turbo", "large-v3-turbo")]:
            self.model_combo.addItem(label, value)
        _set_combo_data(self.model_combo, settings.get("asr_model", "small"))
        from app.model_presentation import populate_model_combo
        populate_model_combo(self.model_combo, settings, settings.get('asr_model','small'))
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(18)
        self.translation_combo = QComboBox()
        self.translation_combo.addItem("本地翻译", "local")
        self.translation_combo.addItem("仅转写", "off")
        _set_combo_data(self.translation_combo, settings.get("translation_mode", "local"))
        self.translation_provider = QComboBox()
        self.translation_provider.addItem("本地 NLLB", "nllb")
        self.translation_provider.addItem("LM Studio", "lmstudio")
        _set_combo_data(self.translation_provider, settings.get("translation_provider", "nllb"))
        model_name = str(settings.get("llm_model") or "").strip()
        self.translation_model_status = QLabel(
            f"问答/摘要模型：{model_name}" if model_name else "问答/摘要模型尚未配置；NLLB 翻译不依赖该模型。"
        )
        self.translation_model_status.setObjectName("muted")
        self.font_spin = QSpinBox()
        self.font_spin.setRange(16, 48)
        self.font_spin.setSuffix(" px")
        self.font_spin.setValue(int(settings.get("font_size", 24)))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(15, 100)
        legacy_opacity = round(float(settings.get("opacity", 0.94)) * 100)
        self.opacity_slider.setValue(int(settings.get("overlay_background_opacity", legacy_opacity)))
        self.opacity_label = QLabel(f"{self.opacity_slider.value()}%")
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(self.opacity_slider, 1)
        opacity_layout.addWidget(self.opacity_label)
        self.opacity_slider.valueChanged.connect(lambda value: self.opacity_label.setText(f"{value}%"))
        self.opacity_slider.setToolTip("快捷调节字幕窗背景不透明度；完整颜色、字体和显示选项请在字幕窗外观中调整。")
        self.subtitle_appearance_button = QPushButton("打开字幕窗外观设置")
        self.subtitle_appearance_button.clicked.connect(self._open_overlay_appearance)
        self.always_on_top = QCheckBox("字幕窗保持在其他窗口上方")
        self.always_on_top.setChecked(bool(settings.get("overlay_always_on_top", settings.get("always_on_top", True))))
        self.save_records = QCheckBox("自动保存会议记录")
        self.save_records.setChecked(bool(settings.get("save_records", True)))
        self.source_mode_value = str(settings.get("source_mode", "system") or "system")
        wlk_initial = settings.get("wlk", {}) or {}
        self.server_url = QLineEdit(str(settings.get("server_url", "") or ""))
        self.server_url.setPlaceholderText("留空使用本机识别服务")
        self.allow_downloads = QCheckBox("允许首次使用时联网下载缺失的模型")
        self.allow_downloads.setChecked(bool(settings.get("allow_downloads", False)))
        self.backend_combo = QComboBox()
        backend_options = [("自动选择", "auto"), ("Faster Whisper", "faster-whisper"), ("OpenAI Whisper", "whisper"), ("MLX Whisper", "mlx-whisper"), ("FunASR", "funasr"), ("Canary", "canary"), ("Qwen3 Streaming", "qwen3-streaming"), ("Voxtral HF", "voxtral"), ("Voxtral MLX", "voxtral-mlx"), ("Qwen3 vLLM", "qwen3-vllm"), ("Qwen3 vLLM Metal", "qwen3-vllm-metal")]
        _add_combo_items(self.backend_combo, backend_options)
        if sys.platform != "darwin":
            for value in ("mlx-whisper", "voxtral-mlx", "qwen3-vllm-metal"):
                index = self.backend_combo.findData(value)
                item = self.backend_combo.model().item(index)
                if item is not None:
                    item.setText(self.backend_combo.itemText(index) + "（仅 macOS）")
                    item.setEnabled(False)
        self.policy_combo = QComboBox()
        _add_combo_items(self.policy_combo, [("SimulStreaming · 低延迟", "simulstreaming"), ("LocalAgreement · 稳定文本", "localagreement")])
        self.diarization = QCheckBox("识别说话人")
        self.diarization_backend = QComboBox()
        _add_combo_items(self.diarization_backend, [("Sortformer", "sortformer"), ("Diart", "diart")])
        self.max_speakers = QComboBox()
        _add_combo_items(self.max_speakers, [("自动", None), ("1 位", 1), ("2 位", 2), ("3 位", 3), ("4 位", 4)])
        self.model_path = QLineEdit("")
        self.model_path.setPlaceholderText("可选：本地模型文件路径")
        self.model_dir = QLineEdit(str(wlk_initial.get("model_dir") or ""))
        self.model_dir.setPlaceholderText("可选：模型目录；留空按模型规格自动查找")
        self.model_path_browse = QPushButton("浏览")
        self.model_path_browse.clicked.connect(self.browse_model_path)
        model_path_row = QWidget()
        model_path_layout = QHBoxLayout(model_path_row)
        model_path_layout.setContentsMargins(0, 0, 0, 0)
        model_path_layout.addWidget(self.model_path, 1)
        model_path_layout.addWidget(self.model_path_browse)
        self.model_dir_browse = QPushButton("选择目录")
        self.model_dir_browse.clicked.connect(self.browse_model_dir)
        model_dir_row = QWidget()
        model_dir_layout = QHBoxLayout(model_dir_row)
        model_dir_layout.setContentsMargins(0, 0, 0, 0)
        model_dir_layout.addWidget(self.model_dir, 1)
        model_dir_layout.addWidget(self.model_dir_browse)
        self.translation_backend = QComboBox()
        _add_combo_items(self.translation_backend, [("NLLB", "nllb"), ("AlignAtt", "alignatt"), ("MLX LLM 翻译", "mlx-llm-mt")])
        self.nllb_backend = QComboBox()
        _add_combo_items(self.nllb_backend, [("Transformers", "transformers"), ("CTranslate2", "ctranslate2")])
        self.nllb_size = QComboBox()
        _add_combo_items(self.nllb_size, [("600M · 轻量", "600M"), ("1.3B", "1.3B"), ("3.3B · 高质量", "3.3B")])
        for combo, key, default in (
            (self.backend_combo, "backend", "faster-whisper"), (self.policy_combo, "backend_policy", "localagreement"),
            (self.diarization_backend, "diarization_backend", "sortformer"),
            (self.translation_backend, "translation_backend", "nllb"), (self.nllb_backend, "nllb_backend", "ctranslate2"),
            (self.nllb_size, "nllb_size", "600M"),
        ):
            _set_combo_data(combo, wlk_initial.get(key, default))
        self.diarization.setChecked(bool(wlk_initial.get("diarization", False)))
        _set_combo_data(self.max_speakers, wlk_initial.get("sortformer_max_speakers"))
        self.model_path.setText(str(wlk_initial.get("model_path") or ""))
        self.context_edit = QTextEdit()
        self.context_edit.setPlaceholderText("可选：术语、专有名词或背景说明（最多 1000 字符）")
        self.context_edit.setMaximumHeight(88)
        self.context_edit.setPlainText(str(settings.get("context", wlk_initial.get("alignatt_context", "")) or "")[:1000])
        self.source_language_combo = LanguagePicker(LANGUAGES or _whisper_language_catalog(), settings.get("source_language", "auto"))
        self.target_language_combo = LanguagePicker(TARGET_LANGUAGES or _nllb_language_catalog(), settings.get("target_language", "zh"))
        self.separate_sources = QCheckBox("系统声音与麦克风分别识别")
        self.separate_sources.setChecked(bool(settings.get("separate_sources", True)))
        self.mic_language = LanguagePicker(LANGUAGES or _whisper_language_catalog(), settings.get("mic_language", "zh"))
        self.mic_target_language = LanguagePicker(TARGET_LANGUAGES or _nllb_language_catalog(), settings.get("mic_target_language", "en"))
        self.stream_mode = QComboBox()
        _add_combo_items(self.stream_mode, [("完整文本 · 保留上下文", "full"), ("差异更新 · 更省资源", "diff")])
        _set_combo_data(self.stream_mode, settings.get("stream_mode", "full"))
        self.separate_sources.toggled.connect(self._toggle_mic_language_fields)
        device_form.addRow("系统声音设备", self.output_device)
        device_form.addRow("麦克风设备", self.mic_device)
        device_form.addRow("音源识别", self.separate_sources)
        self.primary_language_label = QLabel("系统听写语言")
        device_form.addRow(self.primary_language_label, _language_control(self.source_language_combo))
        self.primary_target_label=QLabel("麦克风翻译目标" if self.source_mode_value=='mic' else "主音源翻译目标" if self.source_mode_value=='both' else "系统翻译目标")
        device_form.addRow(self.primary_target_label, _language_control(self.target_language_combo))
        device_form.addRow("麦克风识别语言", _language_control(self.mic_language))
        device_form.addRow("麦克风翻译成", _language_control(self.mic_target_language))
        device_form.addRow("", device_action_row)
        self.appearance_combo=QComboBox()
        _add_combo_items(self.appearance_combo,THEME_CHOICES)
        _set_combo_data(self.appearance_combo,current_theme(self))
        self.appearance_combo.setToolTip("软件和字幕窗的整体配色：选择后立即预览，保存后记住；取消恢复。开会中也可切换，不影响听写。如需字幕自选颜色，可在字幕设置中关闭“跟随软件主题配色”。")
        display_form.addRow("软件风格", self.appearance_combo)
        display_form.addRow("主窗口记录区字号", self.font_spin)
        display_form.addRow("字幕窗背景不透明度（快捷调节；100% 完全不透明）", opacity_row)
        display_form.addRow("浮窗外观", self.subtitle_appearance_button)
        display_form.addRow("字幕窗显示", self.always_on_top)
        display_form.addRow("会议记录", self.save_records)
        self.save_records.setToolTip("自动保存会议记录：运行中锁定当前选择；暂停后修改，保存设置后生效。")
        form.addRow("识别模型", self.model_combo)
        form.addRow("译文开关", self.translation_combo)
        form.addRow("翻译引擎", self.translation_provider)
        form.addRow("问答/摘要模型", self.translation_model_status)
        form.addRow("识别服务地址", self.server_url)
        form.addRow("模型下载", self.allow_downloads)
        form.addRow("字幕更新方式", self.stream_mode)
        pipeline_box = QGroupBox("识别、说话人和翻译")
        pipeline_form = QFormLayout(pipeline_box)
        pipeline_form.setHorizontalSpacing(18)
        pipeline_form.setVerticalSpacing(10)
        pipeline_form.addRow("ASR 后端", self.backend_combo)
        pipeline_form.addRow("流式策略", self.policy_combo)
        pipeline_form.addRow("说话人分离", self.diarization)
        pipeline_form.addRow("说话人后端", self.diarization_backend)
        pipeline_form.addRow("最多说话人数", self.max_speakers)
        pipeline_form.addRow("本地模型文件", model_path_row)
        pipeline_form.addRow("本地模型目录", model_dir_row)
        pipeline_form.addRow("翻译后端", self.translation_backend)
        pipeline_form.addRow("NLLB 实现", self.nllb_backend)
        pipeline_form.addRow("NLLB 模型大小", self.nllb_size)
        pipeline_form.addRow("术语与上下文", self.context_edit)
        form.addRow(pipeline_box)
        tabs.addTab(basic_page, "常用设置")

        wlk_settings = settings.get("wlk", {})
        try:
            from app.wlk_config import config_values, field_schema
            schema = field_schema()
            config_settings = dict(settings)
            config_settings.setdefault("source_language", self.source_language_combo.currentData())
            config_settings.setdefault("target_language", self.target_language_combo.currentData())
            values = config_values(config_settings)
            if isinstance(values, dict) and isinstance(values.get("wlk"), dict):
                values = values["wlk"]
        except (ImportError, AttributeError):
            schema, values = [], dict(wlk_settings)
        from app.config_ui import AdvancedConfigPanel
        self.advanced = AdvancedConfigPanel(schema, values, self)
        for field_name, catalog in (("lan", LANGUAGES or []), ("target_language", TARGET_LANGUAGES or [])):
            old_widget = self.advanced.widgets.get(field_name)
            if not isinstance(old_widget, QComboBox) or not catalog:
                continue
            picker = LanguagePicker(catalog, old_widget.currentData())
            owner_layout = old_widget.parentWidget().layout() if old_widget.parentWidget() else None
            if owner_layout is not None:
                self.advanced.replace_field(field_name, picker, _language_control(picker))
        tabs.addTab(self.advanced, "原库高级参数")
        self.advanced_schema = schema
        self._initial_wlk_values = dict(values)
        self._original_wlk = dict(wlk_settings or {})
        self.advanced_tab = tabs.widget(1)
        self.tabs = tabs
        self._initial_common = {
            "lan": self.source_language_combo.currentData(),
            "target_language": self.target_language_combo.currentData(),
            "mic_language": self.mic_language.currentData(),
            "mic_target_language": self.mic_target_language.currentData(),
            "model_size": self.model_combo.currentData(),
            "backend": self.backend_combo.currentData(),
            "backend_policy": self.policy_combo.currentData(),
            "diarization": self.diarization.isChecked(),
            "diarization_backend": self.diarization_backend.currentData(),
            "sortformer_max_speakers": self.max_speakers.currentData(),
            "model_path": self.model_path.text().strip() or None,
            "model_dir": self.model_dir.text().strip() or None,
            "translation_backend": self.translation_backend.currentData(),
            "nllb_backend": self.nllb_backend.currentData(),
            "nllb_size": self.nllb_size.currentData(),
            "alignatt_context": self.context_edit.toPlainText().strip()[:1000],
        }
        session_frozen = bool(session_active and not session_paused)
        self.session_frozen = session_frozen
        self._set_model_config_enabled(not session_frozen)
        if session_frozen:
            self.output_device.setEnabled(False)
            self.mic_device.setEnabled(False)
            self.translation_combo.setEnabled(False)
            self.translation_provider.setEnabled(False)
            self.separate_sources.setEnabled(False)
            self.stream_mode.setEnabled(False)
            self.advanced.set_fields_enabled(True, only={"lan", "target_language"})
            self.tabs.setTabText(1, "原库高级参数（语言可调）")
        self._toggle_mic_language_fields(self.separate_sources.isChecked())
        self._update_primary_language_label()
        self._set_device_refresh_enabled(not session_frozen)
        self.save_records.setEnabled(not session_frozen)

        for widget, key in (
            (self.model_combo, "model_size"), (self.translation_combo, "translation_provider"),
            (self.translation_provider, "translation_provider"),
            (self.font_spin, "font_size"), (self.opacity_slider, "overlay_background_opacity"),
            (self.translation_model_status, "llm_model"),
            (self.always_on_top, "overlay"), (self.source_language_combo, "lan"),
            (self.target_language_combo, "target_language"), (self.mic_language, "lan"),
            (self.mic_target_language, "target_language"), (self.save_records, "save_records"),
        ):
            fallback = "字幕窗：调整独立字幕窗口的背景透明度与置顶状态；主窗口保持不透明。" if key == "overlay" else ""
            attach_help(widget, key, fallback)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_model_config_enabled(self, enabled: bool) -> None:
        self.model_combo.setEnabled(enabled)
        self.server_url.setEnabled(enabled)
        self.allow_downloads.setEnabled(enabled)
        self.model_path.setEnabled(enabled)
        self.model_dir.setEnabled(enabled)
        self.model_path_browse.setEnabled(enabled)
        self.model_dir_browse.setEnabled(enabled)
        for widget in (self.backend_combo, self.policy_combo, self.diarization,
                       self.diarization_backend, self.max_speakers, self.translation_backend,
                       self.nllb_backend, self.nllb_size, self.context_edit, self.translation_combo,
                       self.translation_provider):
            widget.setEnabled(enabled)
        self.save_records.setEnabled(enabled)
        self._set_device_refresh_enabled(enabled)
        self.advanced.set_fields_enabled(enabled)
        if not enabled:
            note = QLabel("会议进行中：可调整听写语言和字幕显示；暂停后可修改其他识别配置。")
            note.setObjectName("muted")
            self.tabs.setTabText(1, "原库高级参数（已锁定）")
            self.basic_form.addRow(note)
        else:
            self.tabs.setTabText(1, "原库高级参数")

    def _toggle_mic_language_fields(self, enabled: bool) -> None:
        self._update_primary_language_label()
        separate_mic = self.source_mode_value == "both" and bool(enabled)
        self.mic_language.setEnabled(separate_mic)
        self.mic_target_language.setEnabled(separate_mic)

    def _update_primary_language_label(self) -> None:
        if self.source_mode_value == "mic":
            text = "麦克风听写语言"
        elif self.source_mode_value == "both":
            text = "主音源听写语言"
        else:
            text = "系统听写语言"
        self.primary_language_label.setText(text)

    def _open_overlay_appearance(self) -> None:
        open_settings = getattr(self.parent(), "show_overlay_settings", None)
        if callable(open_settings):
            open_settings()

    @staticmethod
    def _populate_device_combo(combo: QComboBox, options: list[str], selected: str | None) -> None:
        combo.clear()
        combo.addItem("系统默认", None)
        unique_options = list(dict.fromkeys(str(item) for item in options))
        for device in unique_options:
            combo.addItem(device, device)
        if selected and selected not in unique_options:
            combo.addItem(f"{selected}（未连接）", selected)
        _set_combo_data(combo, selected)

    def _set_device_refresh_enabled(self, enabled: bool) -> None:
        self.device_refresh_button.setEnabled(bool(enabled))
        self.device_refresh_button.setToolTip(
            "仅刷新设备候选；不会自动更换当前选择。会议运行中请先暂停。"
        )

    def _apply_device_candidates(self, devices: dict[str, list[str]]) -> None:
        selected_output = self.output_device.currentData()
        selected_mic = self.mic_device.currentData()
        self._populate_device_combo(self.output_device, devices.get("output", []), selected_output)
        self._populate_device_combo(self.mic_device, devices.get("input", []), selected_mic)
        self.device_refresh_status.setText("设备列表已刷新；当前选择保持不变。")

    def refresh_devices(self) -> None:
        """Refresh WASAPI candidates off the GUI thread without changing selections."""
        if self.session_frozen:
            return
        current = getattr(self, "_device_refresh_thread", None)
        if current is not None and current.is_alive():
            return
        bridge = DeviceRefreshBridge(self)
        bridge.completed.connect(self._apply_device_candidates)
        bridge.failed.connect(self._device_refresh_failed)
        bridge.finished.connect(self._device_refresh_finished)
        self._device_refresh_bridge = bridge

        def enumerate_devices() -> dict[str, list[str]]:
            from app.audio import list_devices
            return list_devices()

        self._device_refresh_thread = start_device_refresh(bridge, enumerate_devices)
        self.device_refresh_button.setEnabled(False)
        self.device_refresh_status.setText("正在读取音频设备…")

    def _device_refresh_failed(self, message: str) -> None:
        self.device_refresh_status.setText(f"刷新失败：{message}")

    def _device_refresh_finished(self) -> None:
        self._device_refresh_thread = None
        self._device_refresh_bridge = None
        self._set_device_refresh_enabled(not self.session_frozen)

    def browse_model_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择本地模型文件", self.model_path.text() or str(ROOT / "models"), "模型文件 (*.*)")
        if path:
            self.model_path.setText(path)

    def browse_model_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择本地模型目录", self.model_dir.text() or str(ROOT / "models"))
        if path:
            self.model_dir.setText(path)

    def values(self) -> dict[str, Any]:
        value = {
            "appearance_theme": normalize_theme(self.appearance_combo.currentData()),
            "output_device": self.output_device.currentData(),
            "mic_device": self.mic_device.currentData(),
            "asr_model": self.model_combo.currentData(),
            "translation_mode": self.translation_combo.currentData(),
            "translation_provider": self.translation_provider.currentData() or "nllb",
            "font_size": self.font_spin.value(),
            "overlay_background_opacity": self.opacity_slider.value(),
            "overlay_always_on_top": self.always_on_top.isChecked(),
            "save_records": self.save_records.isChecked(),
            "server_url": self.server_url.text().strip(),
            "allow_downloads": self.allow_downloads.isChecked(),
            "source_language": self.source_language_combo.currentData(),
            "target_language": self.target_language_combo.currentData(),
            "separate_sources": self.separate_sources.isChecked(),
            "mic_language": self.mic_language.currentData(),
            "mic_target_language": self.mic_target_language.currentData(),
            "stream_mode": self.stream_mode.currentData(),
        }
        value["wlk"] = self.advanced.values()
        resolved_model_dir = str((APP_ROOT / "models" / f"whisper-{self._initial_common['model_size']}").resolve())
        entered_model_dir = value["wlk"].get("model_dir")
        original_model_dir = self._original_wlk.get("model_dir")
        if entered_model_dir and str(Path(str(entered_model_dir)).resolve()) == resolved_model_dir:
            if not original_model_dir or str(Path(str(original_model_dir)).resolve()) == resolved_model_dir:
                value["wlk"]["model_dir"] = None
        value["context"] = self.context_edit.toPlainText().strip()[:1000]
        common_values = {
            "model_size": self.model_combo.currentData(),
            "backend": self.backend_combo.currentData(),
            "backend_policy": self.policy_combo.currentData(),
            "diarization": self.diarization.isChecked(),
            "diarization_backend": self.diarization_backend.currentData(),
            "sortformer_max_speakers": self.max_speakers.currentData(),
            "model_path": self.model_path.text().strip() or None,
            "model_dir": self.model_dir.text().strip() or None,
            "translation_backend": self.translation_backend.currentData(),
            "nllb_backend": self.nllb_backend.currentData(),
            "nllb_size": self.nllb_size.currentData(),
            "alignatt_context": self.context_edit.toPlainText().strip()[:1000],
            "lan": self.source_language_combo.currentData(),
            "target_language": self.target_language_combo.currentData(),
        }
        for key, common_value in common_values.items():
            if common_value != self._initial_common.get(key):
                value["wlk"][key] = common_value
        if common_values["alignatt_context"] != self._initial_common["alignatt_context"]:
            value["context"] = common_values["alignatt_context"]
        else:
            value["context"] = str(value["wlk"].get("alignatt_context") or "")[:1000]
        value["asr_model"] = value["wlk"]["model_size"]
        value["source_language"] = value["wlk"].get("lan", value.get("source_language", "auto"))
        target_language = value["wlk"].get("target_language", value.get("target_language", "zh"))
        if target_language:
            value["target_language"] = target_language
        return value


class CaptionCard(QFrame):
    def __init__(self, row: dict[str, Any], font_size: int, compact: bool = False, rename_requested=None, name_lookup=None, parent=None):
        super().__init__(parent)
        self.setObjectName("softSurface")
        self.row: dict[str, Any] = {}
        self.compact = compact
        self.rename_requested = rename_requested
        self.name_lookup = name_lookup
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("muted")
        self.meta_label.setStyleSheet("font-size:11px")
        self.rename_button = QPushButton("改名")
        self.rename_button.setObjectName("iconButton")
        self.rename_button.setMaximumWidth(56)
        self.rename_button.clicked.connect(self._rename_speaker)
        self.meta_row_widget = QWidget()
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self.meta_row_widget.setLayout(meta_row)
        meta_row.addWidget(self.meta_label, 1)
        meta_row.addWidget(self.rename_button)
        layout.addWidget(self.meta_row_widget)
        self.source_label = QLabel("原文")
        self.source_label.setObjectName("eyebrow")
        self.source_text = QLabel()
        self.source_text.setObjectName("compactCaptionText" if compact else "captionText")
        self.source_text.setTextFormat(Qt.TextFormat.PlainText)
        self.source_text.setWordWrap(True)
        self.source_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source_label)
        layout.addWidget(self.source_text)
        self.translation_label = QLabel("译文")
        self.translation_label.setObjectName("eyebrow")
        self.translation_text = QLabel()
        self.translation_text.setObjectName("compactTranslationText" if compact else "translationText")
        self.translation_text.setTextFormat(Qt.TextFormat.PlainText)
        self.translation_text.setWordWrap(True)
        self.translation_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.translation_label)
        layout.addWidget(self.translation_text)
        self.translation_status_label = QLabel("")
        self.translation_status_label.setObjectName("muted")
        self.translation_status_label.setWordWrap(True)
        self.translation_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.translation_status_label.setStyleSheet("font-size:12px")
        layout.addWidget(self.translation_status_label)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        if compact:
            layout.setContentsMargins(10, 4, 10, 5)
            layout.setSpacing(2)
            self.source_label.hide()
            self.translation_label.hide()
            self.rename_button.hide()
        self.update_row(row)
        self.set_font_size(font_size)

    def _speaker_id(self) -> Any:
        participant_id = self.row.get("participant_id")
        if isinstance(participant_id, str) and participant_id.strip():
            return participant_id
        return self._native_speaker_id()

    def _native_speaker_id(self) -> int | None:
        try:
            speaker_id = int(self.row.get("speaker_id", self.row.get("speaker")))
        except (TypeError, ValueError):
            return None
        return speaker_id if speaker_id >= 1 else None

    def _speaker_name(self) -> str:
        if self.row.get("participant_pending"):
            pending_name = self.row.get("participant_name")
            if pending_name and self._speaker_id() is not None:
                return f"{pending_name}（待确认）"
            identity = self._speaker_id()
            if isinstance(identity, str):
                return f"待确认参会者 {identity}"
            if identity is not None:
                return f"待确认说话人 {identity}"
            return "待确认声组"
        speaker_id = self._speaker_id()
        if speaker_id is None:
            return str(self.row.get("speaker_name") or "")
        fallback = f"参会者 {speaker_id}" if isinstance(speaker_id, str) else f"说话人 {speaker_id}"
        return str((self.name_lookup or {}).get(speaker_id) or self.row.get("participant_name") or self.row.get("speaker_name") or fallback)

    def _rename_speaker(self) -> None:
        speaker_id = self._speaker_id()
        if speaker_id is None or not self.rename_requested:
            return
        name, accepted = QInputDialog.getText(self, "重命名参会者", "参会者名称", text=self._speaker_name())
        if accepted and name.strip():
            self.rename_requested(speaker_id, name.strip())

    def update_row(self, row: dict[str, Any]) -> None:
        new_row = dict(row)
        self.row = new_row
        self.source_text.setText(str(row.get("source") or ""))
        self.translation_text.setText(str(row.get("translation") or ""))
        display_mode = str(row.get("display_source_mode") or "")
        if display_mode == "original":
            self.source_label.setText("原始听写")
        elif display_mode == "corrected":
            self.source_label.setText("纠错后原文")
        else:
            self.source_label.setText("原文")
        provenance = []
        if row.get("source_original") is not None:
            provenance.append(f"原始听写：{row.get('source_original')}")
        if row.get("source_corrected") is not None:
            provenance.append(f"纠错后：{row.get('source_corrected')}")
        revision = row.get("glossary_revision", row.get("source_revision"))
        if revision is not None:
            provenance.append(f"词库版本：{revision}")
        self.source_text.setToolTip("\n".join(map(str, provenance)))
        translation_status = []
        if row.get("translation_pending"):
            translation_status.append("翻译中")
        if row.get("translation_stale"):
            translation_status.append("旧译文待更新")
        if row.get("translation_error"):
            error = row.get("translation_error")
            translation_status.append("翻译未完成" + (f"：{error}" if isinstance(error, str) and error.strip() else ""))
        self.translation_status_label.setText(" · ".join(translation_status))
        self.translation_status_label.setVisible(bool(translation_status))
        colors=palette_for(current_theme(self))
        self.translation_status_label.setStyleSheet(f"color:{colors['error'] if row.get('translation_error') else colors['warning']};font-size:12px")
        time_text = ""
        start = row.get("start", row.get("start_time"))
        end = row.get("end", row.get("end_time"))
        if start is not None:
            try:
                time_text = f"{float(start):.1f}s" + (f"–{float(end):.1f}s" if end is not None else "")
            except (TypeError, ValueError):
                time_text = str(start)
        language = str(row.get("configured_language") or row.get("language") or row.get("lang") or "")
        target_language = str(row.get("target_language") or "")
        language_text = f"{language.upper()} → {target_language.upper()}" if language and target_language else language.upper()
        speaker_name = self._speaker_name()
        source_name = {"system": "系统声音", "mic": "麦克风", "main": "主音源"}.get(row.get("audio_source"), "")
        self.meta_label.setText("  ·  ".join(part for part in (source_name, speaker_name, time_text, language_text) if part))
        self.meta_row_widget.setVisible(bool(source_name or speaker_name or (not self.compact and (time_text or language))))
        self.setToolTip(self.meta_label.text())
        self.rename_button.setVisible(self._speaker_id() is not None and not self.compact)
        self.rename_button.setText("标注姓名" if row.get("participant_pending") else "改名")
        has_translation = bool(row.get("translation"))
        self.translation_label.setVisible((has_translation or bool(translation_status)) and not self.compact)
        self.translation_text.setVisible(has_translation)
        if _text_is_rtl(str(row.get("source") or "")):
            self.source_text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.source_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.source_text.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.source_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if _text_is_rtl(str(row.get("translation") or "")):
            self.translation_text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.translation_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.translation_text.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.translation_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._update_minimum_height()
        if hasattr(self, '_font_size'):
            self.set_font_size(self._font_size)

    def set_font_size(self, font_size: int) -> None:
        from app.text_fonts import css_family
        self._font_size = font_size
        source_size = max(15, min(16, font_size - 8)) if self.compact else font_size
        self.source_text.setStyleSheet(f'font-family:"{css_family(self.source_text.text())}";font-size:{source_size}px;')
        translation_size = max(13, source_size - 3) if self.compact else max(14, source_size - 3)
        self.translation_text.setStyleSheet(f'font-family:"{css_family(self.translation_text.text())}";font-size:{translation_size}px;')
        self.source_text.setMinimumHeight(self.source_text.fontMetrics().lineSpacing())
        self.translation_text.setMinimumHeight(self.translation_text.fontMetrics().lineSpacing())
        self._update_minimum_height()

    def _update_minimum_height(self) -> None:
        layout = self.layout()
        if layout:
            # sizeHint computed before insertion can assume a narrow width and
            # reserve several wrapped lines permanently. Let Qt's real-width
            # heightForWidth calculation size the card as the window changes.
            self.setMinimumHeight(layout.minimumSize().height())
            self.updateGeometry()


def _contains_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def _text_is_rtl(text: str) -> bool:
    import unicodedata
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in ("R", "AL"):
            return True
        if direction == "L":
            return False
    return False


class MainWindow(QMainWindow):
    start_requested = pyqtSignal(object)
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    config_changed = pyqtSignal(object)
    export_requested = pyqtSignal(str, str)
    export_scope_requested = pyqtSignal(str, str, str)
    clear_requested = pyqtSignal()
    tools_requested = pyqtSignal()
    speaker_rename_requested = pyqtSignal(object, str)
    translation_enabled_requested = pyqtSignal(bool)
    overlay_preferences_changed = pyqtSignal(object)
    background_requested = pyqtSignal()

    def __init__(self, settings: dict[str, Any], devices: dict[str, list[str]]):
        super().__init__()
        self.settings = dict(settings or {})
        self.settings['appearance_theme']=normalize_theme(self.settings.get('appearance_theme','dark'))
        set_theme(self.settings['appearance_theme'],commit=True)
        self._status_kind='idle'
        self.devices = devices or {"output": [], "input": []}
        self.caption_rows: dict[str, dict[str, Any]] = {}
        self.caption_order: list[str] = []
        self._caption_sort_keys: list[tuple[float, str]] = []
        self._caption_sort_by_id: dict[str, tuple[float, str]] = {}
        self.caption_page_size = 200
        self._caption_view_end: int | None = None
        self.history_page = 0
        self.caption_cards: dict[str, CaptionCard] = {}
        self.compact_cards: dict[str, CaptionCard] = {}
        self.history_items: dict[str, QListWidgetItem] = {}
        self.speaker_names: dict[int, str] = {}
        self.pipeline_snapshot: dict[str, Any] = {}
        self.pipeline_by_source: dict[str, dict[str, Any]] = {}
        self.applied_routes: dict[str, str] = {}
        self.applied_route_values: dict[str, tuple[str, str]] = {}
        self.export_total_count = 0
        self.running = False
        self.paused = False
        self.stop_pending = False
        self.position_locked = False
        self.compact_mode = False
        self.transitioning = False
        self.current_font_size = int(self.settings.get("font_size", 24))
        self.setWindowTitle("听译 · 本地会议字幕")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(800, 600)
        self.resize(1200, 800)
        # Old display settings are retained for migration into the subtitle
        # window. The management window stays fully opaque and ordinary.
        self.setWindowOpacity(1.0)
        self.setStyleSheet(style_for(current_theme(self)))
        overlay_settings = {key: value for key, value in self.settings.items() if key.startswith("overlay_")}
        overlay_settings.setdefault("overlay_background_opacity", self.settings.get("overlay_background_opacity", round(float(self.settings.get("opacity", 0.94)) * 100)))
        overlay_settings.setdefault("overlay_always_on_top", self.settings.get("always_on_top", True))
        overlay_settings["translation_mode"] = self.settings.get("translation_mode", "local")
        self.subtitle_overlay = SubtitleOverlay(overlay_settings, parent=None)
        self.subtitle_overlay.preferences_changed.connect(self._overlay_preferences_changed)
        self.subtitle_overlay.translation_enabled_changed.connect(self.translation_enabled_requested.emit)
        self.subtitle_overlay.control_requested.connect(self._handle_overlay_control)
        self.subtitle_overlay.visibility_changed.connect(self._overlay_visibility_changed)
        self.destroyed.connect(self.subtitle_overlay.deleteLater)

        root = QWidget()
        self.setCentralWidget(root)
        from app.theme_backdrop import ThemeBackdrop
        self._theme_backdrop=ThemeBackdrop(root)
        self._theme_backdrop.lower()
        outer = QVBoxLayout(root)
        self.root_layout = outer
        outer.setContentsMargins(18, 14, 18, 12)
        outer.setSpacing(10)
        self.title_bar = QWidget()
        self.title_bar.installEventFilter(self)
        title_row = QHBoxLayout(self.title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        mark = QLabel("听")
        self.mark_label=mark
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(34, 34)
        title_row.addWidget(mark)
        heading = QVBoxLayout()
        self.title_label = QLabel("听译")
        self.title_label.setObjectName("title")
        self.subtitle_label = QLabel("本地实时双语会议字幕")
        self.subtitle_label.setObjectName("muted")
        heading.addWidget(self.title_label)
        heading.addWidget(self.subtitle_label)
        title_row.addLayout(heading)
        title_row.addStretch(1)
        self.lock_button = QPushButton("锁定位置")
        self.lock_button.setObjectName("iconButton")
        self.lock_button.clicked.connect(self.toggle_position_lock)
        self.compact_button = QPushButton("字幕窗")
        self.compact_button.setObjectName("iconButton")
        self.compact_button.clicked.connect(self.toggle_compact_mode)
        self.history_button = QPushButton("本次字幕")
        self.history_button.setObjectName("iconButton")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(self.open_history)
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("iconButton")
        self.settings_button.clicked.connect(self.open_settings)
        self.tools_button = QPushButton("工具")
        self.tools_button.setObjectName("iconButton")
        self.tools_button.clicked.connect(self.tools_requested.emit)
        self.background_button = QPushButton("后台运行")
        self.background_button.setObjectName("iconButton")
        self.background_button.setToolTip("隐藏主窗口并继续会议，可从系统托盘找回")
        self.background_button.clicked.connect(self.background_requested.emit)
        outer.addWidget(self.title_bar)

        self.utility_bar = QWidget()
        self.utility_layout = QHBoxLayout(self.utility_bar)
        self.utility_layout.setContentsMargins(0, 0, 0, 0)
        self.utility_layout.setSpacing(8)
        for button, icon_name in ((self.compact_button, "overlay"), (self.history_button, "history"),
                                  (self.tools_button, "tools"), (self.settings_button, "settings"),
                                  (self.background_button, "background")):
            set_button_icon(button, icon_name)
            self.utility_layout.addWidget(button)
        self.utility_layout.addStretch(1)
        outer.addWidget(self.utility_bar)

        self.control_surface = QFrame()
        self.control_surface.setObjectName("surface")
        controls = QVBoxLayout(self.control_surface)
        controls.setContentsMargins(15, 13, 15, 13)
        controls.setSpacing(10)
        self.control_fields_row = QHBoxLayout()
        self.control_actions_row = QHBoxLayout()
        self.control_layout = self.control_fields_row
        controls.addLayout(self.control_fields_row)
        controls.addLayout(self.control_actions_row)
        self.source_mode_field = self._field("音源", self._source_combo())
        self.source_language_field = self._field("识别语言", self._language_combo(False))
        self.target_language_field = self._field("翻译成", self._language_combo(True))
        fields = self.control_fields_row
        fields.addWidget(self.source_mode_field)
        fields.addWidget(self.source_language_field)
        self.swap_button = QPushButton()
        self.swap_button.setObjectName("iconButton")
        self.swap_button.setFixedSize(36, 36)
        self.swap_button.setIcon(swap_icon())
        self.swap_button.setProperty('themeIcon','swap')
        self.swap_button.setIconSize(QSize(32, 32))
        self.swap_button.setAccessibleName("交换识别语言与翻译目标")
        self.swap_button.setToolTip("交换识别语言与翻译目标")
        self.swap_button.clicked.connect(self.swap_languages)
        fields.addWidget(self.swap_button, 0, Qt.AlignmentFlag.AlignVCenter)
        fields.addWidget(self.target_language_field)
        self.model_combo = QComboBox()
        from app.model_presentation import populate_model_combo
        populate_model_combo(self.model_combo, self.settings, self.settings.get('asr_model','small'))
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(12)
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setMaximumWidth(210)
        _set_combo_data(self.model_combo, self.settings.get("asr_model", "small"))
        self.model_field = self._field("识别模型", self.model_combo)
        fields.addWidget(self.model_field)
        fields.addStretch(1)
        self.start_button = QPushButton("开始会议")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_or_resume)
        set_button_icon(self.start_button, "start")
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self._toggle_pause)
        set_button_icon(self.pause_button, "pause")
        self.stop_button = QPushButton("结束")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self._request_stop)
        set_button_icon(self.stop_button, "stop")
        self.runtime_summary_label = QLabel("")
        self.runtime_summary_label.setObjectName("muted")
        self.runtime_summary_label.setWordWrap(True)
        self.runtime_summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.control_actions_row.addWidget(self.runtime_summary_label, 1)
        self.control_actions_row.addWidget(self.start_button)
        self.control_actions_row.addWidget(self.pause_button)
        self.control_actions_row.addWidget(self.stop_button)
        self.route_widget = QWidget()
        route_layout = QHBoxLayout(self.route_widget)
        route_layout.setContentsMargins(0, 0, 0, 0)
        self.system_route_button = QPushButton()
        self.mic_route_button = QPushButton()
        for button in (self.system_route_button, self.mic_route_button):
            button.setObjectName("routeButton")
        self.system_route_button.clicked.connect(lambda: self.edit_route_languages("system"))
        self.mic_route_button.clicked.connect(lambda: self.edit_route_languages("mic"))
        route_layout.addWidget(self.system_route_button)
        route_layout.addWidget(self.mic_route_button)
        route_layout.addStretch(1)
        controls.insertWidget(1, self.route_widget)
        outer.addWidget(self.control_surface)

        self.stack = QStackedWidget()
        self.normal_page = self._build_normal_page()
        self.compact_page = self._build_compact_page()
        self.stack.addWidget(self.normal_page)
        self.stack.addWidget(self.compact_page)
        outer.addWidget(self.stack, 1)
        self._scroll_timer=QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._scroll_to_latest)

        footer = QHBoxLayout()
        self.status_dot = QLabel("")
        self.status_dot.setFixedSize(9, 9)
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("muted")
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setValue(0)
        self.level_bar.setFixedWidth(110)
        self.level_label = QLabel("音量")
        self.level_label.setObjectName("muted")
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setFixedWidth(65)
        self.mic_level_bar.setValue(0)
        self.mic_level_label = QLabel("麦克风")
        self.mic_level_label.setObjectName("muted")
        self.level_bar.setFixedWidth(65)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("muted")
        self.elapsed_caption = QLabel("会议时长")
        self.volume_caption = self.level_label
        footer.addWidget(self.status_dot)
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(self.level_label)
        footer.addWidget(self.level_bar)
        footer.addWidget(self.mic_level_label)
        footer.addWidget(self.mic_level_bar)
        footer.addSpacing(18)
        footer.addWidget(self.elapsed_caption)
        footer.addWidget(self.elapsed_label)
        self.footer_widget = QWidget()
        self.footer_widget.setLayout(footer)
        outer.addWidget(self.footer_widget)

        self.toast_label = QLabel("")
        self.toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast_label.setTextFormat(Qt.TextFormat.PlainText)
        self.toast_label.setWordWrap(True)
        self.toast_label.hide()
        outer.addWidget(self.toast_label)
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_label.hide)
        self._set_initial_values()
        self._connect_config_signals()
        self._refresh_controls()
        self._render_history()
        self._refresh_route_summary()
        self._refresh_runtime_summary()
        watch_theme(self,self._apply_appearance_theme,on_commit=self._remember_appearance_theme)
        for widget, key in (
            (self.source_mode, "source_mode"), (self.source_language, "lan"),
            (self.target_language, "target_language"), (self.model_combo, "model_size"),
            (self.compact_button, "overlay"), (self.settings_button, "settings"),
            (self.tools_button, "tools"), (self.history_button, "history"),
            (self.start_button, "start_meeting"), (self.pause_button, "pause"),
            (self.stop_button, "stop_meeting"), (self.background_button, "overlay"),
        ):
            fallback = {
                "source_mode": "音源：选择系统声音、麦克风或两者一起采集。示例：需要同时记录本机发言时选择系统加麦克风。",
                "overlay": "字幕窗：打开独立字幕窗口查看原文、译文或双语。关闭字幕窗不会结束会议。",
            }.get(key, "")
            attach_help(widget, key, fallback)

    def _remember_appearance_theme(self,theme: str) -> None:
        self.settings['appearance_theme']=normalize_theme(theme)

    def set_appearance_theme(self,theme: str, *, commit: bool=True) -> None:
        set_theme(theme,commit=commit)

    def _apply_appearance_theme(self,theme: str) -> None:
        colors=palette_for(theme)
        self.setStyleSheet(style_for(theme))
        self._theme_backdrop.set_theme(theme)
        self._theme_backdrop.setGeometry(self.centralWidget().rect())
        self._theme_backdrop.lower()
        self.mark_label.setStyleSheet(f"background:{colors['accent']};border-radius:10px;color:{colors['accent_text']};font-size:18px;font-weight:700")
        self.toast_label.setStyleSheet(f"background:{colors['toast_bg']};border:1px solid {colors['border']};border-radius:9px;padding:10px 14px;color:{colors['toast_text']}")
        for scroll in (self.caption_scroll,self.compact_scroll):
            scroll.setStyleSheet(f"QScrollArea {{background:{colors['soft_surface']};border:0;}} QScrollArea > QWidget > QWidget {{background:{colors['soft_surface']};}}")
            scroll.viewport().setStyleSheet(f"background:{colors['soft_surface']}")
            scroll.widget().setStyleSheet(f"background:{colors['soft_surface']}")
        self._apply_draft_theme()
        for card in (*self.caption_cards.values(),*self.compact_cards.values()):
            card.update_row(card.row)
        self.set_status(self.status_label.text(),self._status_kind)

    def _apply_draft_theme(self) -> None:
        from app.text_fonts import css_family
        colors=palette_for(current_theme(self))
        self.draft_label.setStyleSheet(f'background:{colors["draft_bg"]};color:{colors["draft_text"]};border-radius:6px;padding:8px;font-family:"{css_family(self.draft_label.text())}";')

    def resizeEvent(self,event) -> None:
        super().resizeEvent(event)
        if hasattr(self,'_theme_backdrop'):
            self._theme_backdrop.setGeometry(self.centralWidget().rect())

    def _field(self, label_text: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(label_text)
        label.setObjectName("muted")
        layout.addWidget(label)
        layout.addWidget(widget)
        if isinstance(widget, LanguagePicker):
            layout.addWidget(widget.status_label)
        return wrapper

    def _source_combo(self) -> QComboBox:
        self.source_mode = QComboBox()
        _add_combo_items(self.source_mode, [("系统声音", "system"), ("麦克风", "mic"), ("系统 + 麦克风", "both")])
        _set_combo_data(self.source_mode, self.settings.get("source_mode", "system"))
        self.source_mode.setMinimumWidth(145)
        return self.source_mode

    def _language_combo(self, target: bool) -> QComboBox:
        _ensure_language_catalogs()
        values = TARGET_LANGUAGES if target else LANGUAGES
        combo = LanguagePicker(values or [], self.settings.get("target_language" if target else "source_language", "zh" if target else "auto"))
        combo.setMinimumWidth(126)
        if target:
            self.target_language = combo
        else:
            self.source_language = combo
        return combo

    def _set_initial_values(self) -> None:
        self.caption_list.setSpacing(10)
        self.caption_list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.draft_label.hide()
        self.draft_compact.hide()
        _set_combo_data(self.target_language, self.settings.get("target_language", "zh"))
        _set_combo_data(self.source_language, self.settings.get("source_language", "auto"))

    def _connect_config_signals(self) -> None:
        for combo in (self.source_mode, self.model_combo):
            combo.currentIndexChanged.connect(self._emit_config_changed)
        for combo in (self.source_language, self.target_language):
            combo.currentIndexChanged.connect(self._emit_config_changed)

    def _build_normal_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)
        transcript = QFrame()
        transcript.setObjectName("surface")
        transcript_layout = QVBoxLayout(transcript)
        transcript_layout.setContentsMargins(14, 12, 14, 12)
        transcript_layout.setSpacing(8)
        header = QHBoxLayout()
        labels = QVBoxLayout()
        title = QLabel("实时字幕")
        title.setStyleSheet("font-size:16px;font-weight:700")
        helper = QLabel("当前显示范围")
        helper.setToolTip("清空只影响视图；已保存记录保留。可以选择导出整场会议，复制当前包括全部未清空字幕。")
        helper.setWordWrap(True)
        helper.setObjectName("muted")
        labels.addWidget(title)
        labels.addWidget(helper)
        header.addLayout(labels)
        self.pipeline_metrics_label = QLabel("")
        self.pipeline_metrics_label.setObjectName("muted")
        header.addWidget(self.pipeline_metrics_label)
        header.addStretch(1)
        self.copy_button = QPushButton("复制当前")
        self.copy_button.setToolTip("复制本次显示范围的全部字幕，包括较早分页中的内容；不含已清空的字幕")
        self.copy_button.setObjectName("iconButton")
        set_button_icon(self.copy_button, "copy")
        self.copy_button.clicked.connect(self.copy_transcript)
        self.export_button = QPushButton("导出")
        self.export_button.setObjectName("iconButton")
        set_button_icon(self.export_button, "export")
        self.export_button.clicked.connect(self.choose_export_format)
        self.clear_button = QPushButton("清空视图")
        self.clear_button.setObjectName("iconButton")
        set_button_icon(self.clear_button, "clear")
        self.clear_button.clicked.connect(self.confirm_clear)
        self.latest_button = QPushButton("回到最新")
        self.latest_button.setObjectName("iconButton")
        self.latest_button.clicked.connect(self._return_to_latest)
        self.latest_button.hide()
        header.addWidget(self.latest_button)
        header.addWidget(self.copy_button)
        header.addWidget(self.export_button)
        header.addWidget(self.clear_button)
        transcript_layout.addLayout(header)
        self.empty_caption_label = QLabel("选择音源与语言，点击“开始会议”。字幕会在这里显示。")
        self.empty_caption_label.setObjectName("emptyState")
        self.empty_caption_label.setWordWrap(True)
        self.empty_caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        transcript_layout.addWidget(self.empty_caption_label)
        self.draft_label = QLabel("")
        self.draft_label.setObjectName("draftText")
        self.draft_label.setTextFormat(Qt.TextFormat.PlainText)
        self.draft_label.setWordWrap(True)
        transcript_layout.addWidget(self.draft_label)
        self.caption_scroll = QScrollArea()
        self.caption_scroll.setWidgetResizable(True)
        self.caption_container = QWidget()
        self.caption_list = QVBoxLayout(self.caption_container)
        self.caption_list.setContentsMargins(0, 0, 5, 0)
        self.caption_list.setSpacing(10)
        self.caption_scroll.setWidget(self.caption_container)
        transcript_layout.addWidget(self.caption_scroll, 1)

        history = QFrame()
        self.history_panel = history
        history.setObjectName("surface")
        history.setFixedWidth(225)
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(17, 17, 17, 12)
        history_layout.setSpacing(9)
        hist_title = QLabel("本次字幕索引")
        hist_title.setStyleSheet("font-size:16px;font-weight:700")
        hist_help = QLabel("单击定位 · 双击复制")
        hist_help.setObjectName("muted")
        self.history_list = QListWidget()
        self.history_list.setWordWrap(True)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.itemDoubleClicked.connect(self._copy_history_item)
        self.history_list.itemClicked.connect(self._locate_history_item)
        history_layout.addWidget(hist_title)
        history_layout.addWidget(hist_help)
        history_layout.addWidget(self.history_list, 1)
        history_pager = QHBoxLayout()
        self.history_prev_button = QPushButton("较新")
        self.history_prev_button.clicked.connect(lambda: self._change_history_page(-1))
        self.history_page_label = QLabel("")
        self.history_next_button = QPushButton("较旧")
        self.history_next_button.clicked.connect(lambda: self._change_history_page(1))
        history_pager.addWidget(self.history_prev_button)
        history_pager.addWidget(self.history_page_label, 1)
        history_pager.addWidget(self.history_next_button)
        history_layout.addLayout(history_pager)
        layout.addWidget(transcript, 1)
        layout.addWidget(history, 0)
        history.hide()
        return page

    def _build_compact_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("surface")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        header = QHBoxLayout()
        recent_title = QLabel("最近字幕")
        recent_title.setObjectName("muted")
        header.addWidget(recent_title)
        header.addStretch(1)
        self.compact_language_button = QPushButton("语言搜索")
        self.compact_language_button.setObjectName("iconButton")
        self.compact_language_button.clicked.connect(self._open_compact_language_search)
        header.addWidget(self.compact_language_button)
        self.compact_settings_button = QPushButton("设置")
        self.compact_settings_button.setObjectName("iconButton")
        self.compact_settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.compact_settings_button)
        self.compact_history_button = QPushButton("记录")
        self.compact_history_button.setObjectName("iconButton")
        self.compact_history_button.setToolTip("查看本次会议完整字幕记录")
        self.compact_history_button.clicked.connect(self.open_history)
        self.compact_exit_button = QPushButton("展开")
        self.compact_exit_button.clicked.connect(self.toggle_compact_mode)
        header.addWidget(self.compact_history_button)
        layout.addLayout(header)
        # The window title bar and session controls remain the compact-mode toolbar.
        self.compact_scroll = QScrollArea()
        self.compact_scroll.setWidgetResizable(True)
        self.compact_scroll.setMinimumHeight(145)
        compact_container = QWidget()
        self.compact_captions = QVBoxLayout(compact_container)
        self.compact_captions.setContentsMargins(2, 2, 7, 2)
        self.compact_captions.setSpacing(6)
        self.compact_scroll.setWidget(compact_container)
        layout.addWidget(self.compact_scroll, 1)
        self.draft_compact = QLabel("")
        self.draft_compact.setObjectName("draftText")
        self.draft_compact.setTextFormat(Qt.TextFormat.PlainText)
        self.draft_compact.setWordWrap(True)
        layout.addWidget(self.draft_compact)
        self.compact_empty = QLabel("等待真实语音字幕…")
        self.compact_empty.setObjectName("muted")
        layout.addWidget(self.compact_empty)
        return page

    def _config_snapshot(self) -> dict[str, Any]:
        result = dict(self.settings)
        wlk = dict(result.get("wlk") or {})
        source_wlk = dict(wlk)
        previous_model = str(result.get("asr_model", wlk.get("model_size", "")) or "")
        context = str(result.get("context", "") or "")[:1000]
        result.update(
            source_mode=self.source_mode.currentData(),
            source_language=self.source_language.currentData(),
            target_language=self.target_language.currentData(),
            asr_model=self.model_combo.currentData(),
        )
        # Keep legacy keys authoritative for existing callers while giving the
        # native engine a complete matching config snapshot.
        wlk.update(result.get("wlk") or {})
        wlk.update(lan=result["source_language"], target_language=result["target_language"], model_size=result["asr_model"])
        wlk["alignatt_context"] = context
        old_auto_dir = (APP_ROOT / "models" / f"whisper-{previous_model}").resolve()
        model_dir = wlk.get("model_dir")
        model_dir_was_automatic = False
        if previous_model != str(result["asr_model"]) and model_dir:
            try:
                if Path(str(model_dir)).resolve() == old_auto_dir:
                    wlk["model_dir"] = None
                    model_dir_was_automatic = True
            except (OSError, RuntimeError):
                pass
        result["wlk"] = wlk
        try:
            from app.wlk_config import config_values
            resolved = config_values(result)
            auto_model_dir = (APP_ROOT / "models" / f"whisper-{result['asr_model']}").resolve()
            resolved_dir = resolved.get("model_dir")
            if resolved_dir and (not source_wlk.get("model_dir") or model_dir_was_automatic):
                try:
                    if Path(str(resolved_dir)).resolve() == auto_model_dir:
                        resolved["model_dir"] = None
                except (OSError, RuntimeError):
                    pass
            result["wlk"] = resolved
        except (ImportError, AttributeError):
            result["wlk"] = wlk
        return result

    def _emit_config_changed(self, *_args) -> None:
        if hasattr(self, "settings"):
            previous = (
                self.settings.get("source_language"), self.settings.get("target_language"),
                self.settings.get("mic_language"), self.settings.get("mic_target_language"),
            )
            snapshot = self._config_snapshot()
            self.settings.update(snapshot)
            self._refresh_route_summary()
            self._refresh_runtime_summary()
            self.config_changed.emit(dict(snapshot))
            current = (
                snapshot.get("source_language"), snapshot.get("target_language"),
                snapshot.get("mic_language"), snapshot.get("mic_target_language"),
            )
            if self.running and not self.paused and not self.stop_pending and current != previous:
                self.set_status("正在应用新的听写语言设置…", "working")
                self.toast("新语言设置将从接下来的语音识别开始生效。")

    def _start_or_resume(self) -> None:
        if self.stop_pending:
            return
        if self.running and self.paused:
            self._toggle_pause()
            return
        if self.running:
            return
        self.settings.update(self._config_snapshot())
        self.start_requested.emit(dict(self.settings))

    def _toggle_pause(self) -> None:
        if self.running and not self.stop_pending and not self.transitioning:
            self.pause_requested.emit()

    def _request_stop(self) -> None:
        if self.running and not self.stop_pending:
            self.stop_pending = True
            self.set_status("正在结束会议并保存记录…", "working")
            self._refresh_controls()
            self._sync_overlay_state()
            self.stop_requested.emit()

    def _refresh_controls(self) -> None:
        active = self.running
        config_editable = (not active or self.paused) and not self.transitioning
        languages_editable = not self.stop_pending
        for widget in (self.source_mode, self.model_combo):
            widget.setEnabled(config_editable and not self.stop_pending)
        for widget in (self.source_language, self.target_language, self.swap_button):
            widget.setEnabled(languages_editable)
        self.start_button.setVisible(not active or self.stop_pending)
        self.start_button.setEnabled((not active or self.paused) and not self.stop_pending and not self.transitioning)
        self.pause_button.setVisible(active)
        self.stop_button.setVisible(active)
        self.pause_button.setEnabled(active and not self.stop_pending and not self.transitioning)
        self.pause_button.setText("继续" if self.paused else "暂停")
        self.stop_button.setEnabled(active and not self.stop_pending)
        self.settings_button.setEnabled(not self.stop_pending)
        if hasattr(self, "system_route_button"):
            self.system_route_button.setEnabled(languages_editable)
            self.mic_route_button.setEnabled(languages_editable)
        if hasattr(self, "empty_caption_label"):
            self.empty_caption_label.setVisible(not self.caption_rows)
            self.empty_caption_label.setText(
                "正在准备识别引擎，请稍候…" if self.transitioning and active else
                "会议已暂停；可以修改模型、设备等设置，点击“继续”应用。" if self.paused else
                "正在等待声音。请确认音源与设备，字幕将在这里出现。" if active else
                "选择音源与语言，点击“开始会议”。字幕会在这里显示。")
        if self.stop_pending:
            self.start_button.setText("正在结束…")
        else:
            self.start_button.setText("开始会议")

    def set_status(self, text: str, kind: str = "idle") -> None:
        self._status_kind=kind
        self.status_label.setText(str(text))
        palette=palette_for(current_theme(self))
        colors = {"idle": palette['muted'], "working": palette['accent'], "running": palette['accent'], "paused": palette['warning'], "error": palette['error']}
        self.status_dot.setStyleSheet(f"background:{colors.get(kind, colors['idle'])};border-radius:4px")
        self.status_label.setToolTip(str(text))
        self.subtitle_overlay.set_status(str(text), kind)

    def set_running(self, running: bool, paused: bool = False) -> None:
        self.running = bool(running)
        self.paused = bool(paused) if running else False
        if not running:
            self.transitioning = False
        self.stop_pending = False
        if running:
            self.set_status("会议已暂停" if paused else "正在聆听", "paused" if paused else "running")
        elif self.status_label.text().startswith(("正在聆听", "会议已暂停", "正在结束")):
            self.set_status("会议已结束", "idle")
        self._refresh_controls()
        self._sync_overlay_state()
        self._refresh_route_summary()

    def set_transitioning(self, transitioning: bool, message: str = "") -> None:
        self.transitioning = bool(transitioning)
        if self.transitioning:
            self.set_status(message or "正在应用新的识别配置…", "working")
        elif message:
            self.set_status(message, "paused" if self.paused else "running" if self.running else "idle")
        elif self.running:
            self.set_status("会议已暂停" if self.paused else "正在聆听", "paused" if self.paused else "running")
        self._refresh_controls()
        self._sync_overlay_state()

    def set_level(self, level: float, source: str | None = None) -> None:
        value = max(0, min(100, round(float(level) * 100)))
        if source == "mic" and self._dual_sources():
            self.mic_level_bar.setValue(value)
        else:
            self.level_bar.setValue(value)
        if source is None and value == 0:
            self.mic_level_bar.setValue(0)

    def set_translation_preparing(self, preparing: bool) -> None:
        self.subtitle_overlay.set_translation_preparing(preparing)

    def _dual_sources(self) -> bool:
        return self.source_mode.currentData() == "both" and bool(self.settings.get("separate_sources", True))

    def _refresh_runtime_summary(self) -> None:
        try:
            from app.model_presentation import runtime_summary, runtime_details
            text = runtime_summary(self.settings)
            details = runtime_details(self.settings)
        except ImportError:
            text = "请求配置：" + str((self.settings.get("wlk") or {}).get("backend", "faster-whisper"))
            details = text
        self.runtime_summary_label.setText(text)
        self.runtime_summary_label.setToolTip(details + "\n设置显示请求配置；外部服务实际使用的模型以服务端为准。")

    def _refresh_route_summary(self) -> None:
        dual = self._dual_sources()
        self.route_widget.setVisible(dual)
        self.mic_level_bar.setVisible(dual)
        self.mic_level_label.setVisible(dual)
        self.level_label.setText("系统" if dual else "麦克风" if self.source_mode.currentData() == "mic" else "音量")
        self.source_language_field.layout().itemAt(0).widget().setText("系统听写语言" if dual else "听写语言")
        for source, button, prefix in (("system", self.system_route_button, "系统"), ("mic", self.mic_route_button, "麦克风")):
            lan = self.source_language.currentData() if source == "system" else self.settings.get("mic_language", "zh")
            target = self.target_language.currentData() if source == "system" else self.settings.get("mic_target_language", "en")
            translation_on=self.settings.get('translation_mode','local')!='off'
            route_text=f"{prefix}  {display_label(str(lan))}" + (f" → {display_label(str(target))}" if translation_on else " · 仅听写")
            requested_target = str(target) if translation_on else ''
            if self.running and not self.paused:
                route_text += " · 已生效" if self.applied_route_values.get(source)==(str(lan),requested_target) else " · 待应用"
            button.setText(route_text)
            actual = self.applied_routes.get(source)
            button.setToolTip("点击修改这一路语言；从后续语音片段生效。\n请求：" + button.text() + ("\n已生效：" + actual if actual else "\n尚未收到本路生效确认"))
        self.swap_button.setToolTip("交换系统声音这一路的听写与翻译语言；麦克风方向保持不变" if dual else "交换当前音源的听写与翻译语言")

    def set_applied_route(self, source: str, language: str, target: str) -> None:
        name = {"system":"系统", "mic":"麦克风", "main":"当前音源"}.get(source, "当前音源")
        self.applied_routes[source] = f"{name} {display_label(language)} → {display_label(target) if target else '仅听写'}"
        self.applied_route_values[source]=(language,target)
        self._refresh_route_summary()
        self.set_status("已生效：" + "｜".join(self.applied_routes.values()), "running")

    def edit_route_languages(self, source: str) -> None:
        if self.stop_pending:
            return
        if source != "mic" or not self._dual_sources():
            self._open_compact_language_search()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("麦克风语言方向")
        watch_theme(dialog)
        layout = QVBoxLayout(dialog)
        lan = LanguagePicker(LANGUAGES or _whisper_language_catalog(), self.settings.get("mic_language", "zh"))
        target = LanguagePicker(TARGET_LANGUAGES or _nllb_language_catalog(), self.settings.get("mic_target_language", "en"))
        layout.addWidget(LanguageField("麦克风听写语言", lan))
        layout.addWidget(LanguageField("翻译成", target))
        hint = QLabel("仅修改麦克风这一路。运行中从后续语音生效，原有字幕保留。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings.update(mic_language=lan.currentData(), mic_target_language=target.currentData())
            self._emit_config_changed()

    def set_elapsed(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        self.elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}")

    def update_caption(self, rows: list[dict[str, Any]], draft: str = "", translation_draft: str = "", latency: Any = None) -> None:
        snapshot: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            if row.get("id") is None:
                continue
            snapshot[str(row["id"])] = dict(row)
        self.caption_rows = snapshot
        self.caption_order = sorted(snapshot, key=lambda key: self._caption_sort_key(snapshot[key], key))
        self._caption_sort_keys = [self._caption_sort_key(snapshot[key], key) for key in self.caption_order]
        self._caption_sort_by_id = {key: sort_key for key, sort_key in zip(self.caption_order, self._caption_sort_keys)}
        self._render_captions()
        self._render_history()
        draft_parts = []
        if draft:
            draft_parts.append(f"识别草稿  ·  {draft}")
        if translation_draft:
            draft_parts.append(f"翻译草稿  ·  {translation_draft}")
        draft_text = "\n".join(draft_parts)
        if draft_text:
            self.draft_label.setText(f"草稿  ·  {draft}" if draft and not translation_draft else draft_text)
            self.draft_compact.setText(f"草稿 · {draft}" if draft and not translation_draft else draft_text)
            self.draft_label.show()
            self.draft_compact.show()
        else:
            self.draft_label.hide()
            self.draft_compact.hide()
        self._publish_overlay_caption(draft, translation_draft)
        self.pipeline_metrics_label.setText(f"翻译延迟 {latency} ms" if latency is not None else "")

    def update_pipeline_metrics(self, snapshot: dict[str, Any], source: str | None = None,
                                pipelines: dict[str, dict[str, Any]] | None = None) -> None:
        """Refresh transient pipeline text without replacing committed rows."""
        source = source or "main"
        if pipelines is not None:
            for key, value in pipelines.items():
                self.pipeline_by_source[str(key)] = dict(value or {})
        if snapshot or pipelines is None:
            self.pipeline_by_source[source] = dict(snapshot or {})
        self.pipeline_snapshot = dict(snapshot or {})
        draft = str(self.pipeline_snapshot.get("buffer_transcription", self.pipeline_snapshot.get("draft", "")) or "")
        translation_draft = str(self.pipeline_snapshot.get("buffer_translation", self.pipeline_snapshot.get("translation_draft", "")) or "")
        latency = self.pipeline_snapshot.get("translation_latency_ms", self.pipeline_snapshot.get("translation_delay_ms"))
        if self._dual_sources():
            parts = []
            for key, value in self.pipeline_by_source.items():
                if key not in ("system", "mic"):
                    continue
                original = value.get("buffer_transcription", value.get("draft", "")) or ""
                translated = value.get("buffer_translation", value.get("translation_draft", "")) or ""
                if original or translated:
                    parts.append(f"{'系统' if key == 'system' else '麦克风'}草稿 · {original}" + (f"\n翻译草稿 · {translated}" if translated else ""))
            self.draft_label.setText("\n".join(parts))
            self.draft_compact.setText(self.draft_label.text())
            self.draft_label.setVisible(bool(parts))
            self.draft_compact.setVisible(bool(parts))
        elif draft or translation_draft:
            text = f"草稿  ·  {draft}" if draft and not translation_draft else "\n".join(
                part for part in (f"识别草稿  ·  {draft}" if draft else "", f"翻译草稿  ·  {translation_draft}" if translation_draft else "") if part
            )
            self.draft_label.setText(text)
            self.draft_compact.setText(text.replace("草稿  ·  ", "草稿 · "))
            self.draft_label.show()
            self.draft_compact.show()
        else:
            self.draft_label.clear()
            self.draft_compact.clear()
            self.draft_label.hide()
            self.draft_compact.hide()
        self._publish_overlay_caption()
        self._apply_draft_theme()
        if latency is not None:
            self.pipeline_metrics_label.setText(f"翻译延迟 {latency} ms")
        elif "remaining_time_transcription_processing" in self.pipeline_snapshot:
            self.pipeline_metrics_label.setText("计算 %.2f 秒 · 稳定等待 %.2f 秒 · 说话人 %.2f 秒" % (
                float(self.pipeline_snapshot.get("remaining_time_transcription_processing") or 0),
                float(self.pipeline_snapshot.get("remaining_time_transcription_policy") or 0),
                float(self.pipeline_snapshot.get("remaining_time_diarization") or 0)))

    def apply_caption_changes(self, changed: list[dict[str, Any]], removed: list[Any], draft: str | None = "") -> None:
        """Apply committed row changes while keeping the complete history in memory."""
        for identity in removed or []:
            key = str(identity.get("id") if isinstance(identity, dict) else identity)
            if self.caption_rows.pop(key, None) is not None:
                self._remove_caption_order(key)
        for row in changed or []:
            if row.get("id") is not None:
                key = str(row["id"])
                if key in self.caption_rows:
                    self._remove_caption_order(key)
                new_row = dict(row)
                sort_key = self._caption_sort_key(new_row, key)
                index = bisect_left(self._caption_sort_keys, sort_key)
                self._caption_sort_keys.insert(index, sort_key)
                self.caption_order.insert(index, key)
                self._caption_sort_by_id[key] = sort_key
                self.caption_rows[key] = new_row
        if draft is not None:
            self.update_pipeline_metrics({"draft": draft})
        self._render_captions()
        self._render_history()

    def update_pipeline(self, snapshot: dict[str, Any]) -> None:
        """Render a pipeline snapshot containing committed lines and live metrics."""
        self.pipeline_snapshot = dict(snapshot or {})
        rows = self.pipeline_snapshot.get("rows", self.pipeline_snapshot.get("captions", list(self.caption_rows.values()))) or []
        draft = self.pipeline_snapshot.get("buffer_transcription", self.pipeline_snapshot.get("draft", self.pipeline_snapshot.get("asr_draft", ""))) or ""
        translation_draft = self.pipeline_snapshot.get("buffer_translation", self.pipeline_snapshot.get("translation_draft", self.pipeline_snapshot.get("translation_buffer", ""))) or ""
        latency = self.pipeline_snapshot.get("translation_latency_ms", self.pipeline_snapshot.get("translation_delay_ms"))
        if latency is None and self.pipeline_snapshot.get("translation_latency") is not None:
            try:
                latency = round(float(self.pipeline_snapshot["translation_latency"]) * 1000)
            except (TypeError, ValueError):
                latency = self.pipeline_snapshot["translation_latency"]
        self.update_caption(rows, str(draft), str(translation_draft), latency)
        if 'remaining_time_transcription_processing' in self.pipeline_snapshot:
            self.pipeline_metrics_label.setText('计算 %.2f 秒 · 稳定等待 %.2f 秒 · 说话人 %.2f 秒' % (
                float(self.pipeline_snapshot.get('remaining_time_transcription_processing') or 0),
                float(self.pipeline_snapshot.get('remaining_time_transcription_policy') or 0),
                float(self.pipeline_snapshot.get('remaining_time_diarization') or 0)))

    def _render_captions(self) -> None:
        scrollbar = self.caption_scroll.verticalScrollBar()
        follow = self._caption_view_end is None and scrollbar.maximum() - scrollbar.value() <= 30
        end = min(self._caption_view_end, len(self.caption_order)) if self._caption_view_end is not None else len(self.caption_order)
        visible = {key: self.caption_rows[key] for key in self.caption_order[max(0, end-self.caption_page_size):end] if key in self.caption_rows}
        self._sync_caption_cards(visible, self.caption_list, self.caption_cards, compact=False)
        latest_key = self.caption_order[-1] if self.caption_order else None
        latest = {latest_key: self.caption_rows[latest_key]} if latest_key in self.caption_rows else {}
        self._sync_caption_cards(latest, self.compact_captions, self.compact_cards, compact=True)
        self.compact_empty.setVisible(not latest)
        self.empty_caption_label.setVisible(not self.caption_rows)
        self.copy_button.setEnabled(bool(self.caption_rows))
        self.clear_button.setEnabled(bool(self.caption_rows))
        if follow:
            self._scroll_timer.start(0)
        self.latest_button.setVisible(not follow or self._caption_view_end is not None)
        self._publish_overlay_caption()

    def _publish_overlay_caption(self, draft: str | None = None, translation_draft: str | None = None) -> None:
        overlay = self.subtitle_overlay
        if overlay is None:
            return
        latest_key = self.caption_order[-1] if self.caption_order else None
        latest_row = self.caption_rows.get(latest_key) if latest_key else None
        selected = self.pipeline_snapshot
        if self._dual_sources():
            selected = self.pipeline_by_source.get((latest_row or {}).get("audio_source"), {})
            # An unlabelled draft must never be appended to another input's row.
            draft = None
            translation_draft = None
        if draft is None:
            draft = str(selected.get("buffer_transcription", selected.get("draft", "")) or "")
        if translation_draft is None:
            translation_draft = str(selected.get("buffer_translation", selected.get("translation_draft", "")) or "")
        overlay.update_caption(latest_row, str(draft or ""), str(translation_draft or ""))

    def _sync_overlay_state(self) -> None:
        if self.subtitle_overlay is not None:
            self.subtitle_overlay.set_session_state(
                self.running, self.paused, transitioning=self.transitioning, stop_pending=self.stop_pending
            )

    def _overlay_preferences_changed(self, preferences: dict[str, Any]) -> None:
        self.settings.update(preferences or {})
        self.overlay_preferences_changed.emit(dict(preferences or {}))

    def apply_overlay_preferences(self, settings: dict[str, Any]) -> None:
        """Apply controller-confirmed overlay preferences and translation mode."""
        self.settings.update(settings or {})
        self.subtitle_overlay.apply_preferences(settings or {})

    def show_overlay_settings(self) -> None:
        self.subtitle_overlay.open_settings()

    def _overlay_visibility_changed(self, visible: bool) -> None:
        self.compact_mode = bool(visible)
        self.compact_button.setText("隐藏字幕窗" if visible else "字幕窗")

    def _handle_overlay_control(self, action: str) -> None:
        if action == "pause":
            self._toggle_pause()
        elif action == "show_main":
            self.show_main_from_overlay()
        elif action == "settings":
            self.show_overlay_settings()

    def show_main_from_overlay(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _caption_sort_key(row: dict[str, Any], key: str) -> tuple[float, str]:
        start = row.get("start", row.get("start_time"))
        try:
            timestamp = float(start)
            if timestamp != timestamp:
                timestamp = float("inf")
        except (TypeError, ValueError):
            timestamp = float("inf")
        return timestamp, str(key)

    def _remove_caption_order(self, key: str) -> None:
        sort_key = self._caption_sort_by_id.pop(key, None)
        if sort_key is None:
            return
        index = bisect_left(self._caption_sort_keys, sort_key)
        if index < len(self._caption_sort_keys) and self._caption_sort_keys[index] == sort_key:
            self._caption_sort_keys.pop(index)
            self.caption_order.pop(index)

    def _sync_caption_cards(
        self,
        rows: dict[str, dict[str, Any]],
        layout: QVBoxLayout,
        cards: dict[str, CaptionCard],
        compact: bool,
    ) -> None:
        for key in tuple(cards):
            if key not in rows:
                card = cards.pop(key)
                layout.removeWidget(card)
                card.deleteLater()
        for index, (key, row) in enumerate(rows.items()):
            card = cards.get(key)
            if card is None:
                card = CaptionCard(row, self.current_font_size, compact=compact, rename_requested=self._rename_speaker, name_lookup=self.speaker_names)
                cards[key] = card
                layout.insertWidget(index, card)
            elif card.row != row:
                card.update_row(row)
            current_index = layout.indexOf(card)
            if current_index != index:
                layout.removeWidget(card)
                layout.insertWidget(index, card)

    def _render_history(self) -> None:
        total = len(self.caption_order)
        page_count = max(1, (total + self.caption_page_size - 1) // self.caption_page_size)
        self.history_page = min(max(0, self.history_page), page_count - 1)
        end = total - self.history_page * self.caption_page_size
        start = max(0, end - self.caption_page_size)
        page = [(key, self.caption_rows[key]) for key in self.caption_order[start:end] if key in self.caption_rows]
        visible_keys = {key for key, _ in page}
        for key in tuple(self.history_items):
            if key not in visible_keys:
                item = self.history_items.pop(key, None)
                if item is not None:
                    row_index = self.history_list.row(item)
                    if row_index >= 0:
                        self.history_list.takeItem(row_index)
        for index, (key, row) in enumerate(page):
            source = {"system":"系统", "mic":"麦克风"}.get(row.get('audio_source'), '')
            time = row.get('start',row.get('start_time'))
            try:
                position = f'{float(time):.1f}s' if time is not None else ''
            except (TypeError,ValueError):
                position = ''
            speaker = str(row.get('participant_name') or row.get('speaker_name') or '')
            native_id=self._speaker_number(row)
            if native_id is not None:
                speaker = self.speaker_names.get(native_id) or speaker or f'说话人 {native_id}'
            language = str(row.get('configured_language') or row.get('language') or '').upper()
            target = str(row.get('target_language') or '').upper()
            direction = f'{language} → {target}' if language and target else language
            text = ' · '.join(part for part in (source,speaker,position,direction) if part) + '\n' + str(row.get('source') or '')[:100]
            item = self.history_items.get(key)
            if item is None:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.history_items[key] = item
                self.history_list.insertItem(index, item)
            elif item.text() != text:
                item.setText(text)
            item.setToolTip(self._history_text(row))
            from app.text_fonts import caption_font_family
            item.setFont(QFont(caption_font_family(text),10))
            current_index = self.history_list.row(item)
            if current_index != index:
                if current_index >= 0:
                    self.history_list.takeItem(current_index)
                self.history_list.insertItem(index, item)
        if hasattr(self, "history_page_label"):
            self.history_page_label.setText(f"第 {self.history_page + 1}/{page_count} 页 · {total} 条")
            self.history_prev_button.setEnabled(self.history_page > 0)
            self.history_next_button.setEnabled(self.history_page + 1 < page_count)

    def _change_history_page(self, delta: int) -> None:
        self.history_page = max(0, self.history_page + int(delta))
        self._render_history()

    def _history_text(self, row: dict[str, Any]) -> str:
        source = str(row.get("source") or "")
        translation = str(row.get("translation") or "")
        participant_id = row.get("participant_id")
        if row.get("participant_pending"):
            if isinstance(participant_id, str) and participant_id.strip():
                speaker = f"待确认参会者 {participant_id}"
            elif self._speaker_number(row) is not None:
                speaker = f"待确认说话人 {self._speaker_number(row)}"
            else:
                speaker = "待确认声组"
        else:
            speaker = str(self.speaker_names.get(self._speaker_number(row), "") or row.get("participant_name") or row.get("speaker_name") or "")
        if not speaker and self._speaker_number(row) is not None:
            speaker = f"说话人 {self._speaker_number(row)}"
        start = row.get("start", row.get("start_time"))
        end = row.get("end", row.get("end_time"))
        time_text = ""
        meta = ""
        if start is not None:
            try:
                time_text = f"{float(start):.1f}–{float(end):.1f}s" if end is not None else f"{float(start):.1f}s"
            except (TypeError, ValueError):
                time_text = str(start)
            language = str(row.get("configured_language") or row.get("language") or "")
            target = str(row.get("target_language") or "")
            language_text = f"{language.upper()} → {target.upper()}" if language and target else language.upper()
            meta = " · ".join(part for part in (speaker, time_text, language_text) if part) if speaker else ""
        return (f"{meta}\n" if meta else "") + source + (f"\n{translation}" if translation else "")

    @staticmethod
    def _speaker_number(row: dict[str, Any]) -> int | None:
        try:
            number = int(row.get("speaker_id", row.get("speaker")))
        except (TypeError, ValueError):
            return None
        return number if number >= 1 else None

    def _rename_speaker(self, speaker_id: Any, name: str) -> None:
        try:
            native_id = int(speaker_id)
        except (TypeError, ValueError):
            native_id = None
        if native_id is not None:
            self.speaker_names[native_id] = str(name)
        self.speaker_rename_requested.emit(speaker_id, str(name))
        for cards in (self.caption_cards, self.compact_cards):
            for key, card in cards.items():
                card.row = {}
                card.update_row(self.caption_rows.get(key, {}))
        self._render_history()

    def show_error(self, text: str) -> None:
        self.set_status(str(text), "error")
        self.toast(str(text))

    def toast(self, text: str) -> None:
        self.toast_label.setText(text)
        self.toast_label.adjustSize()
        self.toast_label.show()
        self.toast_timer.start(2600)

    def set_languages(self, settings: dict[str, Any], emit: bool = False) -> bool:
        """Set the displayed language selectors, for hot-switch rollback or sync."""
        selected = {
            "source_language": settings.get("source_language", self.settings.get("source_language", "auto")),
            "target_language": settings.get("target_language", self.settings.get("target_language", "zh")),
        }
        for key, combo in (("source_language", self.source_language), ("target_language", self.target_language)):
            if combo.findData(selected[key]) < 0:
                return False
        for key, combo in (("source_language", self.source_language), ("target_language", self.target_language)):
            combo.blockSignals(True)
            try:
                if isinstance(combo, LanguagePicker):
                    combo.commit_code(str(selected[key]))
                else:
                    _set_combo_data(combo, selected[key])
            finally:
                combo.blockSignals(False)
        self.settings.update(selected)
        self.settings.setdefault("wlk", {})
        self.settings["wlk"].update(lan=selected["source_language"], target_language=selected["target_language"])
        for key in ("mic_language", "mic_target_language"):
            if key in settings:
                self.settings[key] = settings[key]
        if emit:
            self._emit_config_changed()
        else:
            self._refresh_route_summary()
        return True

    def swap_languages(self) -> None:
        source = self.source_language.currentData()
        if source == "auto":
            self.toast("请先选择识别语言，再交换语言方向")
            return
        target = self.target_language.currentData()
        source_index = self.source_language.findData(target)
        target_index = self.target_language.findData(source)
        if source_index >= 0 and target_index >= 0:
            self.source_language.blockSignals(True)
            self.target_language.blockSignals(True)
            self.source_language.setCurrentIndex(source_index)
            self.target_language.setCurrentIndex(target_index)
            self.source_language.blockSignals(False)
            self.target_language.blockSignals(False)
            self._emit_config_changed()
        else:
            self.toast("此语言组合不能直接交换：翻译支持的语言与听写支持的语言范围不同，请分别选择。")

    def apply_live_settings(self, font_size: int | None = None, opacity: float | None = None) -> None:
        if font_size is not None:
            self.current_font_size = max(16, min(48, int(font_size)))
            self.settings["font_size"] = self.current_font_size
            for card in (*self.caption_cards.values(), *self.compact_cards.values()):
                card.set_font_size(self.current_font_size)
        if opacity is not None:
            normalized = max(0.15, min(1.0, float(opacity)))
            self._apply_overlay_preferences({"overlay_background_opacity": round(normalized * 100)})

    def _apply_overlay_preferences(self, preferences: dict[str, Any]) -> None:
        if not preferences:
            return
        self.settings.update(preferences)
        if self.subtitle_overlay is not None:
            self.subtitle_overlay.apply_preferences(preferences)

    def toggle_compact_mode(self) -> None:
        if self.subtitle_overlay is None:
            self.toast("字幕窗暂不可用")
            return
        if self.subtitle_overlay.isVisible():
            self.subtitle_overlay.hide()
            self.compact_mode = False
            self.compact_button.setText("字幕窗")
        else:
            self._publish_overlay_caption()
            self._sync_overlay_state()
            self.subtitle_overlay.show()
            self.compact_mode = True
            self.compact_button.setText("隐藏字幕窗")

    def toggle_position_lock(self) -> None:
        self.position_locked = not self.position_locked
        self.lock_button.setText("已锁定" if self.position_locked else "锁定位置")
        self.lock_button.setStyleSheet(f"color:{palette_for(current_theme(self))['accent']}" if self.position_locked else "")

    def eventFilter(self, watched, event):
        if watched is self.title_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if not self.position_locked:
                    self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            elif event.type() == QEvent.Type.MouseMove and hasattr(self, "_drag_offset"):
                if event.buttons() & Qt.MouseButton.LeftButton and not self.position_locked:
                    self.move(event.globalPosition().toPoint() - self._drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease and hasattr(self, "_drag_offset"):
                del self._drag_offset
                return True
        return super().eventFilter(watched, event)

    def copy_transcript(self) -> None:
        text = "\n\n".join(
            f"{self.caption_rows[key].get('source', '')}" + (f"\n{self.caption_rows[key].get('translation', '')}" if self.caption_rows[key].get("translation") else "")
            for key in self.caption_order if key in self.caption_rows
        )
        if text:
            QGuiApplication.clipboard().setText(text)
            self.toast("已复制本次字幕")
        else:
            self.toast("当前还没有可复制的字幕")

    def _copy_history_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        row = self.caption_rows.get(key, {})
        text = str(row.get("source") or "")
        if row.get("translation"):
            text += f"\n{row['translation']}"
        if text:
            QGuiApplication.clipboard().setText(text)
            self.toast("已复制这条字幕")

    def choose_export_format(self) -> None:
        total = max(len(self.caption_rows), self.export_total_count)
        if not total:
            self.toast("当前没有可导出的字幕")
            return
        from app.export_ui import ExportDialog
        dialog = ExportDialog(len(self.caption_rows), total, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.export_scope_requested.emit(*dialog.result_values())

    def confirm_clear(self) -> None:
        if not self.caption_rows:
            self.toast("当前没有字幕记录")
            return
        answer = QMessageBox.question(
            self,
            "清空本次字幕",
            "清空本次会议的字幕视图？已保存的会议记录不会删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.caption_rows.clear()
            self._caption_view_end=None
            self.pipeline_snapshot.clear()
            self.pipeline_by_source.clear()
            self.caption_order.clear()
            self._caption_sort_keys.clear()
            self._caption_sort_by_id.clear()
            self._render_captions()
            self._render_history()
            self.draft_label.clear()
            self.draft_compact.clear()
            self.draft_label.hide()
            self.draft_compact.hide()
            self._publish_overlay_caption("", "")
            self.clear_requested.emit()

    def open_history(self) -> None:
        visible = self.history_panel.isHidden()
        self.history_panel.setVisible(visible)
        self.history_button.setChecked(visible)
        if visible:
            self._render_history()

    def _locate_history_item(self, item: QListWidgetItem) -> None:
        key = str(item.data(Qt.ItemDataRole.UserRole))
        if key not in self.caption_rows:
            return
        index = self.caption_order.index(key)
        if index < len(self.caption_order)-self.caption_page_size:
            self._caption_view_end = min(len(self.caption_order), index+self.caption_page_size)
            self._render_captions()
        card = self.caption_cards.get(key)
        if card:
            self.caption_scroll.ensureWidgetVisible(card, 0, 20)
            self.latest_button.show()

    def _return_to_latest(self) -> None:
        self._caption_view_end = None
        self.caption_scroll.verticalScrollBar().setValue(self.caption_scroll.verticalScrollBar().maximum())
        self._render_captions()
        self.latest_button.hide()

    def _scroll_to_latest(self) -> None:
        if self._caption_view_end is None:
            scrollbar=self.caption_scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _open_compact_language_search(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("搜索语言")
        watch_theme(dialog)
        layout = QVBoxLayout(dialog)
        source = LanguagePicker(LANGUAGES or _whisper_language_catalog(), self.source_language.currentData())
        target = LanguagePicker(TARGET_LANGUAGES or _nllb_language_catalog(), self.target_language.currentData())
        layout.addWidget(LanguageField("识别语言", source))
        layout.addWidget(LanguageField("翻译目标", target))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.source_language.commit_code(str(source.currentData()))
            self.target_language.commit_code(str(target.currentData()))
            self._emit_config_changed()

    def open_settings(self) -> None:
        if self.stop_pending:
            return
        dialog = SettingsDialog(self.settings, self.devices, self, session_active=self.running,
                                session_paused=self.paused and not self.transitioning)
        old_theme=current_theme(self)
        dialog.appearance_combo.currentIndexChanged.connect(lambda _:self.set_appearance_theme(dialog.appearance_combo.currentData(),commit=False))
        old_font = self.current_font_size
        old_overlay_preferences = {
            "overlay_background_opacity": int(self.settings.get("overlay_background_opacity", round(float(self.settings.get("opacity", 0.94)) * 100))),
            "overlay_always_on_top": bool(self.settings.get("overlay_always_on_top", self.settings.get("always_on_top", True))),
        }
        dialog.font_spin.valueChanged.connect(lambda value: self.apply_live_settings(font_size=value))
        dialog.opacity_slider.valueChanged.connect(lambda value: self.apply_live_settings(opacity=value / 100))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.apply_live_settings(font_size=old_font)
            self._apply_overlay_preferences(old_overlay_preferences)
            self.set_appearance_theme(old_theme,commit=False)
            return
        values = dialog.values()
        old_languages = tuple(self.settings.get(key) for key in ("source_language", "target_language", "mic_language", "mic_target_language"))
        if self.running and not self.paused:
            # A live session accepts language and display changes. Other
            # pipeline values remain untouched until the user pauses.
            language_keys = ("source_language", "target_language", "mic_language", "mic_target_language")
            allowed = set(language_keys) | {"appearance_theme", "font_size", "overlay_background_opacity", "overlay_always_on_top"}
            values = {key: value for key, value in values.items() if key in allowed}
            wlk = dict(self.settings.get("wlk") or {})
            if "source_language" in values:
                wlk["lan"] = values["source_language"]
            if "target_language" in values:
                wlk["target_language"] = values["target_language"]
            values["wlk"] = wlk
        self.settings.update(values)
        self.set_appearance_theme(values.get('appearance_theme',old_theme),commit=True)
        if not self.running or self.paused:
            from app.model_presentation import populate_model_combo
            self.model_combo.blockSignals(True)
            try:
                populate_model_combo(self.model_combo,self.settings,self.settings.get('asr_model'))
            finally:
                self.model_combo.blockSignals(False)
        overlay_preferences = {key: value for key, value in values.items() if key.startswith("overlay_")}
        self._apply_overlay_preferences(overlay_preferences)
        if overlay_preferences:
            self.overlay_preferences_changed.emit(dict(overlay_preferences))
        for combo, key in (
            (self.source_mode, "source_mode"), (self.source_language, "source_language"),
            (self.target_language, "target_language"), (self.model_combo, "asr_model"),
        ):
            if key in self.settings:
                combo.blockSignals(True)
                _set_combo_data(combo, self.settings.get(key))
                combo.blockSignals(False)
        self.apply_live_settings(font_size=values.get("font_size"))
        self.show()
        new_languages = tuple(self.settings.get(key) for key in ("source_language", "target_language", "mic_language", "mic_target_language"))
        if self.running and not self.paused and new_languages != old_languages:
            self.set_status("正在应用新的听写语言设置…", "working")
            self.toast("新语言设置将从接下来的语音识别开始生效。")
        self._emit_config_changed()
