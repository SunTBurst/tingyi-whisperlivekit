import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QScrollArea, QSpinBox, QWidget, QVBoxLayout

from app.interaction import install_interaction_policy, attach_help


def wheel(widget, delta=-120):
    local = QPointF(widget.rect().center())
    global_pos = QPointF(widget.mapToGlobal(widget.rect().center()))
    event = QWheelEvent(local, global_pos, QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


def test_closed_combo_wheel_does_not_change_data_or_emit_and_scrolls_parent():
    app = QApplication.instance() or QApplication([])
    policy = install_interaction_policy(app)
    area = QScrollArea()
    body = QWidget()
    layout = QVBoxLayout(body)
    combo = QComboBox(body)
    combo.addItems(["one", "two", "three"])
    layout.addWidget(combo)
    body.setMinimumHeight(700)
    area.setWidget(body)
    area.resize(240, 140)
    area.show()
    app.processEvents()
    start = combo.currentData()
    changes = []
    combo.currentIndexChanged.connect(changes.append)
    wheel(combo)
    assert combo.currentData() == start
    assert changes == []
    assert area.verticalScrollBar().value() > 0
    area.close()
    assert policy is not None


def test_editable_combo_line_edit_wheel_is_protected_but_typing_works():
    app = QApplication.instance() or QApplication([])
    install_interaction_policy(app)
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["alpha", "beta"])
    combo.setCurrentIndex(0)
    combo.show()
    app.processEvents()
    wheel(combo.lineEdit())
    assert combo.currentData() is None or combo.currentText() == "alpha"
    combo.lineEdit().setText("search")
    assert combo.lineEdit().text() == "search"
    combo.close()


def test_unfocused_spinbox_wheel_does_not_change_value():
    app = QApplication.instance() or QApplication([])
    install_interaction_policy(app)
    root = QWidget()
    spin = QSpinBox(root)
    spin.setRange(0, 10)
    spin.setValue(4)
    other = QWidget(root)
    root.show()
    other.setFocus()
    app.processEvents()
    wheel(spin)
    assert spin.value() == 4
    spin.close()


def test_help_attaches_chinese_description_and_example():
    app = QApplication.instance() or QApplication([])
    install_interaction_policy(app)
    widget = QComboBox()
    attach_help(widget, "lan")
    assert "识别语言" in widget.property("helpText")
    assert "例" in widget.property("helpText")
    widget.close()


def test_open_combo_popup_keeps_native_wheel_and_keyboard_selection():
    app = QApplication.instance() or QApplication([])
    install_interaction_policy(app)
    combo = QComboBox()
    for index in range(30):
        combo.addItem(f"语言 {index}", f"l{index}")
    combo.resize(180, 30)
    combo.show()
    app.processEvents()
    combo.showPopup()
    app.processEvents()
    assert combo.view().isVisible()
    scrollbar = combo.view().verticalScrollBar()
    before = scrollbar.value()
    selected = combo.currentData()
    wheel(combo.view().viewport())
    # Qt's styled list popup scrolls its candidates; the unstyled native popup
    # may ignore the wheel. Neither must silently commit another language.
    assert scrollbar.value() >= before
    assert combo.currentData() == selected
    combo.setFocus()
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() >= 0
    combo.hidePopup()
    combo.close()


def test_help_is_delayed_and_still_available_for_disabled_control():
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton, QToolTip
    app = QApplication.instance() or QApplication([])
    install_interaction_policy(app)
    button = QPushButton("操作")
    button.setEnabled(False)
    attach_help(button, "lan")
    button.show()
    QTest.mouseMove(button, button.rect().center())
    QTest.qWait(650)
    assert not QToolTip.isVisible()
    QTest.qWait(300)
    assert QToolTip.isVisible()
    assert button.accessibleDescription()
    button.close()


def test_child_editor_inherits_help_from_picker():
    app = QApplication.instance() or QApplication([])
    policy = install_interaction_policy(app)
    combo = QComboBox()
    combo.setEditable(True)
    attach_help(combo, "lan")
    combo.show()
    app.processEvents()
    policy._auto_attach(combo.lineEdit())
    assert "识别语言" in combo.lineEdit().property("helpText")
    combo.close()


def test_every_upstream_schema_field_has_specific_help():
    from app.wlk_config import field_schema
    from app.help_text import HELP_TEXT
    schema = field_schema()
    assert len(schema) == 118
    assert {field["name"] for field in schema} <= HELP_TEXT.keys()
    assert "请勿分享" in HELP_TEXT["api_token"]
    assert "私钥内容" in HELP_TEXT["ssl_keyfile"]


def test_existing_tooltip_is_not_replaced_by_unknown_generic_key():
    app = QApplication.instance() or QApplication([])
    from PyQt6.QtWidgets import QPushButton
    button = QPushButton("后台运行")
    button.setToolTip("已有的具体操作说明")
    attach_help(button, "unmapped_key")
    assert button.toolTip() == "已有的具体操作说明"

def test_overlay_control_object_name_gets_help_automatically():
    app = QApplication.instance() or QApplication([])
    policy = install_interaction_policy(app)
    from PyQt6.QtWidgets import QSpinBox
    spin = QSpinBox()
    spin.setObjectName("overlayFontSize")
    policy._auto_attach(spin)
    assert "字号" in spin.property("helpText")
    spin.close()

def test_destroyed_help_widget_clears_pending_timer_safely():
    from PyQt6 import sip
    app = QApplication.instance() or QApplication([])
    policy = install_interaction_policy(app)
    from PyQt6.QtWidgets import QPushButton
    button = QPushButton("临时控件")
    from PyQt6.QtCore import QEvent
    policy.eventFilter(button, QEvent(QEvent.Type.Enter))
    sip.delete(button)
    assert policy._help_widget is None
    policy._show_help()


def test_legacy_ui_help_keys_resolve_to_the_actual_control_behavior():
    from PyQt6.QtWidgets import QCheckBox, QSlider, QPushButton
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItem("本地翻译", "local")
    combo.addItem("仅转写", "off")
    attach_help(combo, "translation_provider")
    assert "本地译文" in combo.property("helpText")
    slider = QSlider(Qt.Orientation.Horizontal)
    attach_help(slider, "overlay")
    assert "100%" in slider.property("helpText") and '越小越透明' in slider.property('helpText')
    topmost = QCheckBox("字幕窗保持在其他窗口上方")
    attach_help(topmost, "overlay")
    assert "字幕窗置顶" in topmost.property("helpText")
    overlay = QPushButton("字幕窗")
    attach_help(overlay, "overlay")
    assert "不会停止会议" in overlay.property("helpText")



def test_specific_existing_field_tooltip_is_preserved():
    from PyQt6.QtWidgets import QPushButton
    app = QApplication.instance() or QApplication([])
    button = QPushButton("设置")
    button.setToolTip("该字段已有的准确说明")
    attach_help(button, "settings")
    assert button.toolTip() == "该字段已有的准确说明"


def test_all_upstream_config_fields_have_chinese_display_labels():
    from app.wlk_config import LABELS, field_schema
    schema = field_schema()
    assert len(schema) == 118
    assert all(field["name"] in LABELS for field in schema)
    assert all(LABELS[field["name"]] != field["name"] for field in schema)
    assert all(any("\u4e00" <= char <= "\u9fff" for char in LABELS[field["name"]]) for field in schema)
