import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QSpinBox

from app.subtitle_overlay import SubtitleOverlay, _AppearanceDialog


class SubtitleOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_overlay(self, **settings):
        overlay = SubtitleOverlay(settings)
        self.addCleanup(overlay.close)
        return overlay

    def test_is_independent_qt_tool_with_owner_lifetime_and_resize_grip(self):
        parent = QDialog()
        overlay = SubtitleOverlay({}, parent=parent)
        self.addCleanup(parent.close)
        self.addCleanup(overlay.close)
        assert overlay.parentWidget() is None
        assert overlay.owner is parent
        assert overlay.isWindow()
        assert overlay.windowFlags() & Qt.WindowType.Tool
        overlay.show()
        assert overlay.resize_grip.isVisible()
        assert overlay.resize_grip.isEnabled()

    def test_hiding_or_minimizing_owner_does_not_hide_overlay(self):
        parent = QDialog()
        overlay = SubtitleOverlay({}, parent=parent)
        self.addCleanup(parent.close)
        self.addCleanup(overlay.close)
        parent.show()
        overlay.show()
        parent.showMinimized()
        self.app.processEvents()
        assert overlay.isVisible()

    def test_drag_moves_unlocked_window_and_lock_blocks_drag(self):
        overlay = self.make_overlay(overlay_x=100, overlay_y=100, overlay_width=320, overlay_height=160)
        overlay.show()
        self.app.processEvents()
        start = overlay.pos()
        local = QPointF(5, 5)
        header_point = overlay.drag_header.mapToGlobal(QPoint(5, 5))
        global_start = QPointF(header_point)
        press = QMouseEvent(QEvent.Type.MouseButtonPress, local, global_start,
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(overlay.drag_header, press)
        moved = QPointF(global_start.x() + 50, global_start.y() + 30)
        motion = QMouseEvent(QEvent.Type.MouseMove, local, moved, Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(overlay.drag_header, motion)
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, local, moved,
                              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(overlay.drag_header, release)
        self.app.processEvents()
        delta = overlay.pos() - start
        assert abs(delta.x() - 50) <= 2
        assert abs(delta.y() - 30) <= 2

        overlay.lock_toggle.setChecked(True)
        locked_start = overlay.pos()
        QApplication.sendEvent(overlay.drag_header, press)
        QApplication.sendEvent(overlay.drag_header, motion)
        QApplication.sendEvent(overlay.drag_header, release)
        self.assertEqual(overlay.pos(), locked_start)

    def test_preferences_validate_geometry_colors_font_and_display_mode(self):
        overlay = self.make_overlay(
            overlay_width=10,
            overlay_height=10000,
            overlay_background_color="not-a-color",
            overlay_background_opacity=120,
            overlay_font_family="A font that does not exist",
            overlay_font_size=1,
            overlay_source_color="#abcdef",
            overlay_translation_color="#123456",
            overlay_display_mode="bogus",
        )
        prefs = overlay.preferences()
        assert prefs["overlay_width"] >= 320
        assert prefs["overlay_height"] <= 1200
        assert prefs["overlay_background_color"] == "#20242b"
        assert prefs["overlay_background_opacity"] == 100
        assert prefs["overlay_font_family"] != "A font that does not exist"
        assert prefs["overlay_font_size"] >= 12
        assert prefs["overlay_source_color"] == "#abcdef"
        assert prefs["overlay_translation_color"] == "#123456"
        assert prefs["overlay_display_mode"] == "bilingual"

    def test_background_alpha_changes_background_without_window_opacity(self):
        overlay = self.make_overlay(overlay_background_opacity=55)
        assert overlay.windowOpacity() == 1.0
        assert overlay.background_color.alpha() < overlay.source_label.palette().color(
            overlay.source_label.foregroundRole()
        ).alpha()
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        overlay.show()
        self.app.processEvents()
        pixel=overlay.grab().toImage().pixelColor(overlay.width()//2,overlay.height()-12)
        assert 100 < pixel.alpha() < 200

    def test_translation_control_emits_request_until_settings_confirm_state(self):
        overlay = self.make_overlay(translation_mode="off")
        requests = []
        changes = []
        overlay.translation_enabled_changed.connect(requests.append)
        overlay.preferences_changed.connect(changes.append)
        overlay.translation_toggle.setChecked(True)
        assert requests == [True]
        assert overlay.translation_toggle.isChecked()
        overlay.apply_preferences({"translation_mode": "off"})
        assert not overlay.translation_toggle.isChecked()
        assert changes == []
        overlay.translation_toggle.setChecked(True)
        overlay.apply_preferences({"translation_mode": "local"})
        assert overlay.translation_toggle.isChecked()

    def test_display_modes_and_pending_or_failed_translation_never_claim_completion(self):
        overlay = self.make_overlay(overlay_display_mode="bilingual")
        row = {"id": "one", "source": "hello", "translation": "旧译文", "translation_stale": True}
        overlay.update_caption(row)
        assert overlay.source_label.text() == "hello"
        assert overlay.translation_label.text().startswith("（旧译文，待更新）")
        assert "过期" in overlay.translation_status.text()
        overlay.update_caption({"source": "hello", "translation": "错误译文", "translation_error": "timeout"})
        assert overlay.translation_label.text().startswith("（翻译未完成）")
        assert "未完成" in overlay.translation_status.text()
        overlay.update_caption({"source": "hello", "translation": "你好"})
        assert overlay.translation_label.text() == "你好"
        overlay.display_mode_combo.setCurrentIndex(overlay.display_mode_combo.findData("source"))
        assert not overlay.translation_label.isVisible()
        overlay.display_mode_combo.setCurrentIndex(overlay.display_mode_combo.findData("translation"))
        assert not overlay.source_label.isVisible()

    def test_empty_state_drafts_speaker_and_long_text_are_rendered(self):
        overlay = self.make_overlay(overlay_show_speaker=True, overlay_show_draft=True)
        assert "会议开始" in overlay.empty_label.text()
        overlay.update_caption({"source": "one", "translation": "一", "speaker_name": "主持人"},
                               draft="unfinished words", translation_draft="未完成")
        assert "主持人" in overlay.speaker_label.text()
        assert "unfinished words" in overlay.draft_label.text()
        assert "未完成" in overlay.draft_label.text()
        overlay.update_caption({"source": "长句" * 300, "translation": "长译文" * 300})
        assert overlay.source_label.text() == "长句" * 300
        assert overlay.source_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    def test_session_controls_pause_and_preserve_reachable_return_button(self):
        overlay = self.make_overlay()
        controls = []
        overlay.control_requested.connect(controls.append)
        overlay.set_session_state(running=True, paused=False)
        assert overlay.pause_button.text() == "暂停"
        overlay.pause_button.click()
        assert controls == ["pause"]
        overlay.set_session_state(running=True, paused=True, transitioning=True)
        assert overlay.pause_button.text() == "继续"
        assert not overlay.pause_button.isEnabled()
        assert overlay.show_main_button.isEnabled()
        overlay.show_main_button.click()
        assert controls == ["pause", "show_main"]

    def test_close_hides_overlay_and_never_requests_session_stop(self):
        overlay = self.make_overlay()
        controls = []
        visibility = []
        overlay.control_requested.connect(controls.append)
        overlay.visibility_changed.connect(visibility.append)
        overlay.show()
        overlay.close()
        self.app.processEvents()
        assert not overlay.isVisible()
        assert "stop" not in controls
        assert visibility == [True, False]

    def test_settings_dialog_cancel_restores_preview_and_emits_nothing(self):
        overlay = self.make_overlay(overlay_font_size=24)
        emitted = []
        overlay.preferences_changed.connect(emitted.append)
        dialog = _AppearanceDialog(overlay)
        size = dialog.findChild(QSpinBox, "overlayFontSize")
        assert size is not None
        size.setValue(40)
        dialog.reject()
        assert overlay.preferences()["overlay_font_size"] == 24
        assert emitted == []

    def test_appearance_mode_updates_header_and_cancel_reverts_it(self):
        overlay=self.make_overlay(overlay_display_mode='bilingual')
        dialog=_AppearanceDialog(overlay)
        dialog.display_mode.setCurrentIndex(dialog.display_mode.findData('source'))
        assert overlay.preferences()['overlay_display_mode']=='source'
        assert overlay.display_mode_combo.currentData()=='source'
        dialog.reject()
        assert overlay.preferences()['overlay_display_mode']=='bilingual'
        assert overlay.display_mode_combo.currentData()=='bilingual'
        overlay._commit_appearance({**overlay.preferences(),'overlay_display_mode':'translation'})
        assert overlay.display_mode_combo.currentData()=='translation'

    def test_single_subtitle_settings_button_opens_own_appearance_dialog(self):
        overlay = self.make_overlay()
        self.assertEqual(overlay.appearance_button.text(), "字幕设置")
        self.assertFalse(hasattr(overlay, "settings_button"))
        emitted = []
        overlay.control_requested.connect(emitted.append)
        dialogs = []

        def close_appearance_dialog():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, _AppearanceDialog):
                dialogs.append(dialog)
                dialog.reject()

        QTimer.singleShot(0, close_appearance_dialog)
        overlay.appearance_button.click()
        self.assertEqual(len(dialogs), 1)
        self.assertEqual(dialogs[0].windowTitle(), "字幕设置")
        self.assertEqual(emitted, [])

    def test_lock_and_topmost_changes_are_persisted_preferences(self):
        overlay = self.make_overlay(overlay_locked=False, overlay_always_on_top=False)
        changed = []
        overlay.preferences_changed.connect(changed.append)
        overlay.lock_toggle.setChecked(True)
        overlay.topmost_toggle.setChecked(True)
        assert overlay.preferences()["overlay_locked"] is True
        assert overlay.preferences()["overlay_always_on_top"] is True
        assert len(changed) == 2


if __name__ == "__main__":
    unittest.main()
