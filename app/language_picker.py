"""Searchable language selector that separates typed text from selection."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QKeyEvent, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QCompleter, QLabel, QVBoxLayout, QWidget


_ENGLISH = {
    "auto": "Automatic", "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese",
    "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali",
    "bo": "Tibetan", "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "cs": "Czech", "cy": "Welsh",
    "da": "Danish", "de": "German", "el": "Greek", "en": "English", "es": "Spanish", "et": "Estonian",
    "eu": "Basque", "fa": "Persian", "fi": "Finnish", "fo": "Faroese", "fr": "French", "gl": "Galician",
    "gu": "Gujarati", "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "ht": "Haitian Creole", "hu": "Hungarian", "hy": "Armenian", "id": "Indonesian", "is": "Icelandic",
    "it": "Italian", "ja": "Japanese", "jw": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer",
    "kn": "Kannada", "ko": "Korean", "la": "Latin", "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lv": "Latvian", "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian",
    "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese", "my": "Burmese",
    "ne": "Nepali", "nl": "Dutch", "nn": "Norwegian Nynorsk", "no": "Norwegian", "oc": "Occitan",
    "pa": "Punjabi", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sa": "Sanskrit", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sn": "Shona",
    "so": "Somali", "sq": "Albanian", "sr": "Serbian", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai", "tk": "Turkmen", "tl": "Tagalog",
    "tr": "Turkish", "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese",
    "yi": "Yiddish", "yo": "Yoruba", "yue": "Cantonese", "zh": "Chinese",
}
_ALIASES = {
    "zh": ("中文", "汉语", "普通话", "chinese", "mandarin", "zh-cn", "zh-hans", "cmn"),
    "en": ("英语", "英文", "english"),
    "ar": ("阿拉伯语", "阿语", "arabic"),
    "auto": ("自动", "自动识别", "automatic", "detect"),
}
_ISO3 = {
    "arb": "ar", "ara": "ar", "zho": "zh", "chi": "zh", "cmn": "zh", "eng": "en", "spa": "es",
    "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "ita": "it", "por": "pt", "jpn": "ja",
    "kor": "ko", "rus": "ru", "nld": "nl", "dut": "nl", "hin": "hi", "ind": "id", "tur": "tr",
    "swe": "sv", "pol": "pl", "ron": "ro", "rum": "ro", "ukr": "uk", "vie": "vi", "tha": "th",
}


def _english_name(code: str) -> str:
    direct = _ENGLISH.get(code)
    if direct:
        return direct
    base = code.split("_", 1)[0].split("-", 1)[0].lower()
    return _ENGLISH.get(_ISO3.get(base, ""), "")


_SHORT_ZH = {
    "auto": "自动", "ar": "阿拉伯语", "de": "德语", "en": "英语", "es": "西班牙语",
    "fa": "波斯语", "fr": "法语", "hi": "印地语", "id": "印尼语", "it": "意大利语",
    "ja": "日语", "ko": "韩语", "nl": "荷兰语", "no": "挪威语", "pt": "葡萄牙语",
    "ru": "俄语", "sv": "瑞典语", "th": "泰语", "tr": "土耳其语", "vi": "越南语",
    "zh": "中文",
}


def display_label(code: Any) -> str:
    """Return a compact selected-state label while keeping the full popup rows intact."""
    value = str(code or "").strip()
    lowered = value.lower().replace("_", "-")
    if lowered in {"zh-hans", "zh-cn", "zh-sg", "cmn-hans", "cmn-hans-cn", "zho-hans", "chi-hans"}:
        return "简体中文"
    if lowered in {"zh-hant", "zh-tw", "zh-hk", "cmn-hant", "cmn-hant-tw", "zho-hant", "chi-hant"}:
        return "繁體中文"
    base = lowered.split("-", 1)[0]
    label = _SHORT_ZH.get(base) or _SHORT_ZH.get(_ISO3.get(base,''))
    if label and '_' in value and '-' in lowered:
        script=lowered.split('-',1)[1]
        scripts={'arab':'阿拉伯文字','latn':'拉丁转写','cyrl':'西里尔文字','deva':'天城文字'}
        return f"{label}（{scripts.get(script,script)}）"
    if label:
        return label
    english = _english_name(value)
    return english or value


class LanguagePicker(QComboBox):
    """Editable, searchable combo whose committed value changes only on choice."""

    code_role = int(Qt.ItemDataRole.UserRole) + 11
    search_role = int(Qt.ItemDataRole.UserRole) + 12
    _recent_codes: list[str] = []

    def __init__(self, values: list[tuple[str, Any]], current: Any = None, parent=None):
        super().__init__(parent)
        self._committed = None
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        self._catalog = QStandardItemModel(self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self._catalog)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(0)
        completer = QCompleter(self.proxy_model, self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionRole(self.search_role)
        self.setCompleter(completer)
        self.setModel(self._catalog)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.status_label.setAccessibleName("语言搜索状态")
        self.search_edit = self.lineEdit()
        self.search_edit.installEventFilter(self)
        self.search_edit.setPlaceholderText("搜索中文、English 或语言代码")
        self.search_edit.setAccessibleName("搜索语言")
        self._codes: set[str] = set()
        priorities = {}
        for index, code in enumerate([current, *self._recent_codes, "auto", "zh", "en", "ar"]):
            priorities.setdefault(str(code), index)
        values = sorted(values, key=lambda item: (priorities.get(str(item[1]), 99), str(item[0])))
        for label, code in values:
            code = str(code)
            english = _english_name(code)
            full_label = f"{label}  ·  {english}  ·  {code}"
            item = QStandardItem(full_label)
            item.setToolTip(full_label)
            item.setAccessibleText(full_label)
            item.setData(code, self.code_role)
            base_code = code.split("_", 1)[0].split("-", 1)[0]
            aliases = (*_ALIASES.get(code, ()), *_ALIASES.get(base_code, ()),
                       *_ALIASES.get(_ISO3.get(base_code.lower(), ""), ()))
            item.setData(" ".join((str(label), english, code, *aliases)), self.search_role)
            self._catalog.appendRow(item)
            self._codes.add(code)
        self.activated.connect(self._activated)
        self.currentIndexChanged.connect(self._index_changed)
        self.search_edit.textChanged.connect(self._search_changed)
        self._completer.activated[QModelIndex].connect(self._completion_index_activated)
        if current in self._codes:
            self.commit_code(str(current))
        elif self._catalog.rowCount():
            self.commit_code(str(self._catalog.item(0).data(self.code_role)))

    @property
    def _completer(self) -> QCompleter:
        return self.completer()

    def currentData(self, role: int = Qt.ItemDataRole.UserRole) -> Any:  # noqa: N802 - Qt API
        if role == Qt.ItemDataRole.UserRole:
            return self._committed
        return super().currentData(role)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt API
        super().setCurrentIndex(index)
        if 0 <= index < self.count():
            code = self.itemData(index, self.code_role)
            if code in self._codes:
                self._committed = code
                self.lineEdit().setText(display_label(code))
                self.lineEdit().setCursorPosition(0)

    def findData(self, value: Any, role: int = Qt.ItemDataRole.UserRole, flags=Qt.MatchFlag.MatchExactly) -> int:  # noqa: N802
        if role == Qt.ItemDataRole.UserRole:
            for row in range(self.count()):
                if self.itemData(row, self.code_role) == value:
                    return row
            return -1
        return super().findData(value, role, flags)

    def commit_code(self, code: str) -> bool:
        index = self.findData(code)
        if index < 0:
            self.status_label.setText("没有匹配的有效语言，当前选择保持不变。")
            return False
        super().setCurrentIndex(index)
        self._committed = str(code)
        type(self)._recent_codes = [str(code), *(item for item in type(self)._recent_codes if item != str(code))][:12]
        self.lineEdit().setText(display_label(code))
        self.lineEdit().setCursorPosition(0)
        self.status_label.setText("")
        return True

    def _activated(self, index: int) -> None:
        code = self.itemData(index, self.code_role)
        if code is not None:
            self.commit_code(str(code))

    def _index_changed(self, index: int) -> None:
        if index >= 0:
            code = self.itemData(index, self.code_role)
            if code in self._codes:
                self._committed = code
                type(self)._recent_codes = [str(code), *(item for item in type(self)._recent_codes if item != str(code))][:12]
                self.status_label.clear()

    def _completion_index_activated(self, index: QModelIndex) -> None:
        code = index.data(self.code_role)
        if code is not None:
            self.commit_code(str(code))

    def _search_changed(self, text: str) -> None:
        needle = str(text or "").strip()
        self.proxy_model.setFilterRole(self.search_role)
        self.proxy_model.setFilterFixedString(needle)
        message = "没有匹配的有效语言，当前选择保持不变。"
        status = "" if not needle or self.proxy_model.rowCount() else message
        self.status_label.setText(status)
        index=self.findData(self._committed)
        full=self.itemText(index) if index>=0 else ''
        explanation=full+'\n输入后从候选中选择或按 Enter 确认；仅输入不会改变当前语言。会议中修改用于后续语音片段。'
        tooltip=(status+'\n' if status else '')+explanation
        self.setToolTip(tooltip)
        self.search_edit.setToolTip(tooltip)
        self.search_edit.setAccessibleDescription(status)
        if needle and self.proxy_model.rowCount():
            self.completer().complete()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_search()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            popup = self.completer().popup()
            selected = popup.currentIndex()
            if popup.isVisible() and selected.isValid():
                self._completion_index_activated(selected)
                popup.hide()
                event.accept()
                return
            if self.proxy_model.rowCount() == 1:
                code = self.proxy_model.index(0, 0).data(self.code_role)
                self.commit_code(str(code))
                event.accept()
                return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if watched is self.search_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_search()
                event.accept()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                popup = self.completer().popup()
                selected = popup.currentIndex()
                if popup.isVisible() and selected.isValid():
                    self._completion_index_activated(selected)
                    popup.hide()
                    event.accept()
                    return True
                if self.proxy_model.rowCount() == 1:
                    self._completion_index_activated(self.proxy_model.index(0, 0))
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _cancel_search(self) -> None:
        self.completer().popup().hide()
        if self._committed is not None:
            index = self.findData(self._committed)
            if index >= 0:
                self.lineEdit().setText(display_label(self._committed))
                self.lineEdit().setCursorPosition(0)
        self.proxy_model.setFilterFixedString("")
        self.status_label.clear()


class LanguageField(QWidget):
    """Small labeled picker wrapper for forms."""

    def __init__(self, label: str, picker: LanguagePicker, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        title.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(picker)
        layout.addWidget(picker.status_label)
