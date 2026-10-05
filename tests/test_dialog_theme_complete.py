"""Exercise modal selections and the transient surfaces that used to miss themes."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QMenu
from app.appearance import set_theme, watch_theme
from app.dialogs import QFileDialog, QColorDialog, QInputDialog, QMessageBox
from app.icons import app_icon
from app.theme import palette_for, style_for


class DialogThemeCompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        set_theme('sky')

    def tearDown(self):
        for widget in list(self.app.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        set_theme('dark')

    def modal(self, operation, interaction):
        failures=[]
        def visit():
            dialog=self.app.activeModalWidget()
            try:
                self.assertIsNotNone(dialog)
                self.assertEqual(dialog.styleSheet(),style_for('sky'))
                set_theme('spring')
                self.assertEqual(dialog.styleSheet(),style_for('spring'))
                interaction(dialog)
            except Exception as exc:
                failures.append(exc)
                if dialog:
                    dialog.reject()
        QTimer.singleShot(0,visit)
        result=operation()
        if failures:
            raise failures[0]
        return result

    def test_text_and_item_results_survive_live_theme_change(self):
        def name(dialog):
            dialog.setTextValue('参会者甲')
            dialog.accept()
        self.assertEqual(self.modal(lambda:QInputDialog.getText(None,'名称','输入',text='旧名'),name),('参会者甲',True))
        set_theme('sky')
        def choose(dialog):
            dialog.setTextValue('translation')
            dialog.accept()
        self.assertEqual(self.modal(lambda:QInputDialog.getItem(None,'用途','选择',['asr','translation'],0,False),choose),('translation',True))

    def test_color_picker_preserves_choice_and_cancel_is_invalid(self):
        def color(dialog):
            self.assertTrue(dialog.testOption(QColorDialog.ColorDialogOption.DontUseNativeDialog))
            dialog.setCurrentColor(QColor('#abcdef'))
            dialog.accept()
        selected=self.modal(lambda:QColorDialog.getColor(QColor('#123456'),None,'颜色'),color)
        self.assertEqual(selected.name(),'#abcdef')
        set_theme('sky')
        canceled=self.modal(lambda:QColorDialog.getColor(QColor('#123456')),lambda d:d.reject())
        self.assertFalse(canceled.isValid())

    def test_file_dialog_selection_and_cancel_without_writing_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'字幕.txt'
            path.write_text('synthetic fixture',encoding='utf-8')
            def choose(dialog):
                self.assertTrue(dialog.testOption(QFileDialog.Option.DontUseNativeDialog))
                self.assertEqual(dialog.fileMode(),QFileDialog.FileMode.ExistingFile)
                dialog.selectFile(str(path))
                dialog.accept()
            result=self.modal(lambda:QFileDialog.getOpenFileName(None,'选择',str(path),'文本 (*.txt)'),choose)
            self.assertEqual(Path(result[0]),path)
            set_theme('sky')
            self.assertEqual(self.modal(lambda:QFileDialog.getSaveFileName(None,'保存',str(path.parent/'未写入.txt'),'文本 (*.txt)'),lambda d:d.reject()),('',''))
            self.assertFalse((path.parent/'未写入.txt').exists())

    def test_message_button_result_and_default_remain_safe(self):
        def choose(dialog):
            self.assertTrue(dialog.testOption(QMessageBox.Option.DontUseNativeDialog))
            self.assertEqual(dialog.standardButton(dialog.defaultButton()),QMessageBox.StandardButton.No)
            dialog.button(QMessageBox.StandardButton.No).click()
        result=self.modal(lambda:QMessageBox.question(None,'覆盖','要覆盖吗？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No),choose)
        self.assertEqual(result,QMessageBox.StandardButton.No)

    def test_popup_and_app_mark_follow_theme_without_global_stylesheet(self):
        dialog=QDialog()
        watch_theme(dialog)
        combo=QComboBox(dialog)
        combo.addItems(['中文','英语'])
        dialog.show()
        combo.showPopup()
        self.app.processEvents()
        popup=combo.view().window()
        self.assertTrue(popup.property('themeManaged'))
        for theme in ('sky','spring','dark','sky'):
            set_theme(theme)
            self.app.processEvents()
            self.assertEqual(popup.styleSheet(),style_for(theme))
            pixel=app_icon().pixmap(64,64).toImage().pixelColor(10,10)
            self.assertEqual(pixel.name(),palette_for(theme)['accent'])
            self.assertEqual(self.app.styleSheet(),'')


if __name__=='__main__':
    unittest.main()
