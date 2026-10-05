"""Double-click entry point for 听译, the local Chinese meeting caption app."""
import logging
import os
import sys

from app.settings import ROOT, load_settings

# CUDA's dependent DLLs must be visible before importing the speech libraries.
torch_lib = ROOT / '.venv/Lib/site-packages/torch/lib'
os.environ['PATH'] = str(torch_lib) + os.pathsep + os.environ.get('PATH', '')
os.environ['PYTHONUTF8'] = '1'
os.chdir(ROOT)

from PyQt6.QtCore import QLockFile, QTimer, Qt, QTranslator, QLibraryInfo
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication
from app.dialogs import QMessageBox
from app.audio import list_devices
from app.controller import Controller
from app.ui import MainWindow


class AppWindow(MainWindow):
    def closeEvent(self, event):
        controller = getattr(self, 'controller', None)
        background=getattr(self,'background',None)
        if controller and controller.active and background and background.available and not self.closing and not getattr(self,'_exit_requested',False):
            event.ignore()
            background.hide_main()
            if not getattr(self,'_background_close_explained',False):
                self._background_close_explained=True
                background.notify_background()
            return
        if controller and controller.has_processes:
            self.closing = True
            event.ignore()
            controller.request_shutdown()
            self.stop_pending = True
            self._refresh_controls()
            self.set_status('正在保存字幕并关闭…', 'working')
            return
        super().closeEvent(event)
        if controller: controller.flush_overlay_preferences()
        if background: background.dispose()
        if getattr(self,'subtitle_overlay',None): self.subtitle_overlay.close()


def main():
    (ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    (ROOT / 'data').mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(ROOT / 'logs/app.log'), encoding='utf-8', level=logging.INFO)
    application = QApplication(sys.argv)
    from app.qt_bootstrap import configure_application
    configure_application(application)
    from app.interaction import install_interaction_policy
    install_interaction_policy(application)
    application.setApplicationName('听译')
    from app.icons import app_icon
    application.setWindowIcon(app_icon())
    qt_translator = QTranslator(application)
    if qt_translator.load('qtbase_zh_CN', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        application.installTranslator(qt_translator)
    lock = QLockFile(str(ROOT / 'data/app.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, '听译', '听译已经在运行，请切换到已打开的窗口。')
        return 0
    try:
        devices = list_devices()
    except Exception as exc:
        devices = {'output':[], 'input':[]}
        logging.exception('Device enumeration failed')
    window = AppWindow(load_settings(), devices)
    controller = Controller(window)
    window.controller = controller
    window.closing = False
    from app.background import BackgroundManager
    window.background=BackgroundManager(window,controller)
    application.aboutToQuit.connect(window.background.dispose)
    controller.shutdown_finished.connect(lambda:window.close() if window.closing else None)
    geometry = application.primaryScreen().availableGeometry()
    window.move(max(geometry.x(), geometry.center().x()-window.width()//2), max(geometry.y(), geometry.center().y()-window.height()//2))
    window.show()
    QTimer.singleShot(700,lambda:controller.show_recovery(automatic=True))
    result=application.exec()
    # Delete Qt windows while the application and style/font engine still live.
    from PyQt6.QtCore import QCoreApplication,QEvent
    for widget in list(application.topLevelWidgets()): widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
