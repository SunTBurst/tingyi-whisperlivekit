"""Live UI theme changes, separated from the speech session configuration."""
import weakref
from PyQt6 import sip
from PyQt6.QtCore import QObject, QEvent, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton, QWidget


def _titlebar(widget, theme):
    """Match app-owned Windows frames; leave other operating systems alone."""
    app=QApplication.instance()
    if app is None or app.platformName() != 'windows' or not widget.isWindow() or not widget.isVisible():
        return
    if widget.windowFlags() & Qt.WindowType.FramelessWindowHint:
        return
    from app.theme import palette_for
    import ctypes
    colors=palette_for(theme)
    try:
        handle=int(widget.winId())
        dark=ctypes.c_int(theme=='dark')
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(handle),20,ctypes.byref(dark),4)
        for attribute,key in ((35,'window'),(36,'text'),(34,'border')):
            c=QColor(colors[key])
            value=ctypes.c_uint(c.red() | c.green()<<8 | c.blue()<<16)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(handle),attribute,ctypes.byref(value),4)
    except (AttributeError,OSError,ValueError):
        pass


class _TransientThemes(QObject):
    """Qt creates combo/completer/tooltip windows after their parent is styled."""
    def __init__(self,parent):
        super().__init__(parent)
        self.surfaces={}

    def eventFilter(self, widget, event):
        if event.type()==QEvent.Type.Show and isinstance(widget,QWidget):
            name=widget.metaObject().className()
            if widget.isWindow() and (isinstance(widget,QDialog) or name in ('QMenu','QTipLabel','QComboBoxPrivateContainer') or
                    widget.windowType() in (Qt.WindowType.Popup,Qt.WindowType.ToolTip)):
                if not widget.property('themeManaged'):
                    # A Qt-owned popup's Python wrapper can otherwise disappear
                    # between events even while the native widget remains live.
                    key=id(widget)
                    self.surfaces[key]=widget
                    widget.destroyed.connect(lambda *_args,key=key:self._release_later(key))
                    watch_theme(widget)
            if widget.property('themeManaged'):
                _titlebar(widget,current_theme())
        return False

    def _release_later(self,key):
        # Do not drop the final Python wrapper reference from inside the
        # QObject destructor: Qt's font-popup cleanup is still on the stack.
        QTimer.singleShot(0,lambda:self.surfaces.pop(key,None))


class _ThemeBus(QObject):
    changed=pyqtSignal(str)
    committed=pyqtSignal(str)


def _bus():
    app=QApplication.instance()
    if app is None:
        return None
    if not hasattr(app,'_tingyi_theme_bus'):
        # Also covers Qt's internal overwrite/color/input prompts, which can
        # otherwise bypass our themed wrappers on Windows.
        app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs,True)
        app._tingyi_theme_bus=_ThemeBus(app)
        app._tingyi_transient_themes=_TransientThemes(app)
        app.installEventFilter(app._tingyi_transient_themes)
    return app._tingyi_theme_bus


def current_theme(owner=None):
    from app.theme import normalize_theme
    app=QApplication.instance()
    value=app.property('appearanceTheme') if app else None
    if value:
        return normalize_theme(value)
    settings=getattr(owner,'settings',{}) or {}
    return normalize_theme(settings.get('appearance_theme','dark'))


def set_theme(value, *, commit=False):
    from app.theme import normalize_theme, palette_for, style_for
    theme=normalize_theme(value)
    app=QApplication.instance()
    if app is None:
        return theme
    stylesheet=style_for(theme)
    if app.property('appearanceTheme')==theme and app.property('appearanceStyle')==stylesheet:
        if commit:
            _bus().committed.emit(theme)
        return theme
    app.setProperty('appearanceTheme',theme)
    app.setProperty('appearanceStyle',stylesheet)
    colors=palette_for(theme)
    palette=QPalette(app.palette())
    roles={'Window':'window','WindowText':'text','Base':'field','AlternateBase':'soft_surface',
           'Text':'text','Button':'surface','ButtonText':'text','Highlight':'accent',
           'HighlightedText':'accent_text','ToolTipBase':'surface','ToolTipText':'text',
           'PlaceholderText':'muted','Light':'surface','Midlight':'soft_surface',
           'Mid':'border','Dark':'border','Shadow':'border','BrightText':'accent_text',
           'Link':'accent','LinkVisited':'translation'}
    for role,key in roles.items():
        palette.setColor(getattr(QPalette.ColorRole,role),QColor(colors[key]))
    for role in ('WindowText','Text','ButtonText','PlaceholderText'):
        palette.setColor(QPalette.ColorGroup.Disabled,getattr(QPalette.ColorRole,role),QColor(colors['disabled_text']))
    app.setPalette(palette)
    from app.icons import app_icon
    app.setWindowIcon(app_icon())
    # QSS belongs to each managed window. Applying the same large QSS again at
    # QApplication scope stacks Qt stylesheet proxies and corrupts modal font
    # dialogs after repeated window creation on this bundled Windows runtime.
    bus=_bus()
    bus.changed.emit(theme)
    if commit:
        bus.committed.emit(theme)
    return theme


def refresh_icons(widget):
    from app.icons import app_icon, set_button_icon, swap_icon
    if widget.isWindow():
        widget.setWindowIcon(app_icon())
    for button in widget.findChildren(QPushButton):
        name=button.property('themeIcon')
        if name=='swap':
            button.setIcon(swap_icon())
        elif name:
            set_button_icon(button,str(name))


class _WindowTheme(QObject):
    """A real Qt receiver lets Qt disconnect it before releasing its window."""
    def __init__(self,widget,callback,on_commit):
        super().__init__(widget)
        self.ref=weakref.ref(widget)
        self.callback_ref=weakref.WeakMethod(callback) if callback is not None and getattr(callback,'__self__',None) is not None else None
        self.commit_ref=weakref.WeakMethod(on_commit) if on_commit is not None and getattr(on_commit,'__self__',None) is not None else None
        self.plain_callback=None if self.callback_ref else callback
        self.plain_commit=None if self.commit_ref else on_commit

    @pyqtSlot(str)
    def apply(self,theme):
        from app.theme import style_for
        target=self.ref()
        if target is None or sip.isdeleted(target):
            return
        handler=self.callback_ref() if self.callback_ref else self.plain_callback
        if self.callback_ref and handler is None:
            return
        if handler:
            handler(theme)
        else:
            target.setStyleSheet(style_for(theme))
        refresh_icons(target)
        _titlebar(target,theme)
    @pyqtSlot(str)
    def remember(self,theme):
        target=self.ref()
        handler=self.commit_ref() if self.commit_ref else self.plain_commit
        if target is not None and not sip.isdeleted(target) and handler:
            handler(theme)


def watch_theme(widget, callback=None, *, on_commit=None):
    """Style a window and subscribe for exactly its Qt lifetime."""
    if widget.property('themeManaged'):
        return
    widget.setProperty('themeManaged',True)
    receiver=_WindowTheme(widget,callback,on_commit)
    widget._theme_receiver=receiver
    bus=_bus()
    if bus:
        bus.changed.connect(receiver.apply)
        if on_commit:
            bus.committed.connect(receiver.remember)
    receiver.apply(current_theme(widget))
