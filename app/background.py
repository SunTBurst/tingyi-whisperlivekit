"""Keep meeting controls reachable while the independent subtitle is visible."""
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu,QSystemTrayIcon
from app.icons import app_icon
from app.appearance import watch_theme, _bus


class BackgroundManager(QObject):
    def __init__(self,window,controller,*,tray_available=None):
        super().__init__(window)
        self.window=window
        self.controller=controller
        self.available=QSystemTrayIcon.isSystemTrayAvailable() if tray_available is None else tray_available
        self.tray=None
        if self.available:
            self.tray=QSystemTrayIcon(app_icon(),self)
            self.tray.setToolTip('听译 · 本地会议字幕')
            menu=QMenu(window)
            watch_theme(menu)
            menu.addAction('打开主窗口',self.restore_main)
            menu.addAction('显示字幕窗',self.show_subtitle)
            self.pause_action=menu.addAction('暂停 / 继续',controller.toggle_pause)
            menu.addSeparator()
            menu.addAction('退出并保存',self.quit)
            menu.aboutToShow.connect(lambda:self.pause_action.setEnabled(controller.active and not controller.starting and not controller.resuming and not controller.closing and not window.stop_pending and not window.transitioning))
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._activated)
            self.tray.show()
            _bus().changed.connect(self._apply_theme)
        window.background_requested.connect(self.hide_main)
        window.subtitle_overlay.hidden.connect(self._subtitle_hidden)

    def _apply_theme(self, _theme):
        if self.tray:
            self.tray.setIcon(app_icon())

    def _activated(self,reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_main()

    def show_subtitle(self):
        self.window.subtitle_overlay.show()
        self.window.subtitle_overlay.raise_()

    def hide_main(self):
        self.show_subtitle()
        self.window.hide()

    def restore_main(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def notify_background(self):
        if self.tray:
            self.tray.showMessage('听译仍在运行','会议继续采集声音。点击托盘图标返回；选择“退出并保存”完全关闭。',QSystemTrayIcon.MessageIcon.Information,5000)

    def _subtitle_hidden(self):
        if not self.available and not self.window.isVisible() and not getattr(self.window,'closing',False):
            self.restore_main()

    def quit(self):
        self.window._exit_requested=True
        self.restore_main()
        self.window.close()

    def dispose(self):
        if self.tray: self.tray.hide()
