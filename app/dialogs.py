"""Qt-owned dialogs: consistent themes without relying on OS dialog colors."""
from pathlib import Path

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog as _ColorDialog, QDialog, QFileDialog as _FileDialog,
    QInputDialog as _InputDialog, QLineEdit, QMessageBox as _MessageBox,
)
from app.appearance import watch_theme


class QFileDialog(_FileDialog):
    def __init__(self, parent=None, caption='', directory='', filter=''):
        super().__init__(parent, caption, directory, filter)
        self.setOption(self.Option.DontUseNativeDialog, True)
        watch_theme(self)

    @classmethod
    def _choose(cls, parent, caption, directory, filter, selectedFilter, options, mode, save=False):
        dialog = cls(parent, caption, '', filter)
        try:
            dialog.setOptions(options | cls.Option.DontUseNativeDialog)
            dialog.setFileMode(mode)
            dialog.setAcceptMode(cls.AcceptMode.AcceptSave if save else cls.AcceptMode.AcceptOpen)
            if directory:
                path = Path(directory)
                if path.is_dir() or mode == cls.FileMode.Directory:
                    dialog.setDirectory(str(path))
                else:
                    dialog.setDirectory(str(path.parent))
                    dialog.selectFile(path.name)
            if selectedFilter:
                dialog.selectNameFilter(selectedFilter)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return (dialog.selectedFiles() if accepted else []), dialog.selectedNameFilter() if accepted else ''
        finally:
            dialog.deleteLater()

    @classmethod
    def getOpenFileName(cls, parent=None, caption='', directory='', filter='', initialFilter='', options=_FileDialog.Option(0)):
        files, selected = cls._choose(parent, caption, directory, filter, initialFilter, options, cls.FileMode.ExistingFile)
        return (files[0] if files else ''), selected

    @classmethod
    def getOpenFileNames(cls, parent=None, caption='', directory='', filter='', initialFilter='', options=_FileDialog.Option(0)):
        return cls._choose(parent, caption, directory, filter, initialFilter, options, cls.FileMode.ExistingFiles)

    @classmethod
    def getSaveFileName(cls, parent=None, caption='', directory='', filter='', initialFilter='', options=_FileDialog.Option(0)):
        files, selected = cls._choose(parent, caption, directory, filter, initialFilter, options, cls.FileMode.AnyFile, True)
        return (files[0] if files else ''), selected

    @classmethod
    def getExistingDirectory(cls, parent=None, caption='', directory='', options=_FileDialog.Option.ShowDirsOnly):
        files, _ = cls._choose(parent, caption, directory, '', '', options, cls.FileMode.Directory)
        return files[0] if files else ''


class QColorDialog(_ColorDialog):
    def __init__(self, initial=QColor(), parent=None):
        super().__init__(initial, parent)
        self.setOption(self.ColorDialogOption.DontUseNativeDialog, True)
        watch_theme(self)

    @classmethod
    def getColor(cls, initial=QColor(), parent=None, title='', options=_ColorDialog.ColorDialogOption(0)):
        dialog = cls(initial, parent)
        try:
            dialog.setWindowTitle(title or '选择颜色')
            dialog.setOptions(options | cls.ColorDialogOption.DontUseNativeDialog)
            return dialog.currentColor() if dialog.exec() == QDialog.DialogCode.Accepted else QColor()
        finally:
            dialog.deleteLater()


class QInputDialog(_InputDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOkButtonText('确定')
        self.setCancelButtonText('取消')
        watch_theme(self)

    @classmethod
    def getText(cls, parent, title, label, echo=QLineEdit.EchoMode.Normal, text=''):
        dialog = cls(parent)
        try:
            dialog.setWindowTitle(title)
            dialog.setLabelText(label)
            dialog.setTextEchoMode(echo)
            dialog.setTextValue(text)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return (dialog.textValue() if accepted else ''), accepted
        finally:
            dialog.deleteLater()

    @classmethod
    def getItem(cls, parent, title, label, items, current=0, editable=True):
        dialog = cls(parent)
        try:
            dialog.setWindowTitle(title)
            dialog.setLabelText(label)
            dialog.setComboBoxItems(items)
            dialog.setComboBoxEditable(editable)
            if 0 <= current < len(items):
                dialog.setTextValue(items[current])
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return (dialog.textValue() if accepted else ''), accepted
        finally:
            dialog.deleteLater()


class QMessageBox(_MessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Windows native message boxes ignore the application's stylesheet.
        self.setOption(self.Option.DontUseNativeDialog, True)
        watch_theme(self)

    @classmethod
    def _show(cls, icon, parent, title, text, buttons, defaultButton):
        dialog = cls(parent)
        try:
            dialog.setIcon(icon)
            dialog.setWindowTitle(title)
            dialog.setText(text)
            dialog.setStandardButtons(buttons)
            if defaultButton != cls.StandardButton.NoButton:
                dialog.setDefaultButton(defaultButton)
            labels = {cls.StandardButton.Ok:'确定', cls.StandardButton.Yes:'是',
                      cls.StandardButton.No:'否', cls.StandardButton.Cancel:'取消'}
            for button, label in labels.items():
                widget = dialog.button(button)
                if widget:
                    widget.setText(label)
            dialog.exec()
            return dialog.standardButton(dialog.clickedButton())
        finally:
            dialog.deleteLater()

    @classmethod
    def information(cls, parent, title, text, buttons=_MessageBox.StandardButton.Ok, defaultButton=_MessageBox.StandardButton.NoButton):
        return cls._show(cls.Icon.Information, parent, title, text, buttons, defaultButton)

    @classmethod
    def warning(cls, parent, title, text, buttons=_MessageBox.StandardButton.Ok, defaultButton=_MessageBox.StandardButton.NoButton):
        return cls._show(cls.Icon.Warning, parent, title, text, buttons, defaultButton)

    @classmethod
    def question(cls, parent, title, text, buttons=_MessageBox.StandardButton.Yes | _MessageBox.StandardButton.No, defaultButton=_MessageBox.StandardButton.NoButton):
        return cls._show(cls.Icon.Question, parent, title, text, buttons, defaultButton)
