import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from app.ui import MainWindow
from app.settings import DEFAULTS
from app.controller import Controller
from app.tools_ui import ToolsDialog


def test_all_meeting_tools_are_populated_on_open_without_starting_services():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    dialog=ToolsDialog(controller)
    try:
        assert dialog.tabs.tabText(0)=='全部工具'
        assert {'glossary','participants','ai','records','manual_save','recovery','reapply',
                'models','files','service','diagnostics','subtitle','subtitle_style'}<=set(dialog.overview_actions)
        assert not controller.server.active
        assert all(button.text().strip() for button in dialog.overview_actions.values())
    finally: dialog.close(); window.close()


def test_meeting_tools_entry_opens_the_complete_tool_window_and_is_reusable():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    try:
        assert controller.meeting_button.menu() is None
        controller.meeting_button.click()
        app.processEvents()
        dialog=controller._tools_dialog
        assert dialog.isVisible() and dialog.tabs.tabText(0)=='全部工具'
        controller.meeting_button.click()
        assert controller._tools_dialog is dialog
        assert not controller.server.active
    finally:
        if getattr(controller,'_tools_dialog',None): controller._tools_dialog.close()
        window.close()


def test_closed_pending_batch_can_be_started_again_on_reopening():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    dialog=ToolsDialog(controller)
    dialog.show()
    dialog._batch_start_pending=True
    dialog.batch_run_button.setEnabled(False)
    generation=dialog._batch_generation
    dialog.close()
    app.processEvents()
    dialog.show()
    assert not dialog._batch_start_pending and not dialog._closing
    assert dialog._batch_generation>generation
    assert dialog.batch_run_button.isEnabled()
    assert dialog._active_job is None
    dialog.close()
    window.close()


def test_startup_recovery_offers_entry_without_blocking_dialog(monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(dict(DEFAULTS),{'output':[],'input':[]})
    controller=Controller(window)
    monkeypatch.setattr('app.meeting_store.recoverable_meetings',lambda path:[{'path':'synthetic.json'}])
    def blocked_dialog(*args): raise AssertionError('Startup opened a blocking recovery dialog')
    monkeypatch.setattr('app.meeting_ui.RecoveryDialog',blocked_dialog)
    controller.show_recovery(automatic=True)
    assert '待恢复 1' in controller.meeting_button.text()
    assert not controller.server.active
    window.close()
