"""Consistent Chinese fonts and widget rendering, including offscreen checks."""
from pathlib import Path
import os
from PyQt6.QtGui import QFont,QFontDatabase


def configure_application(application):
    if getattr(application,'_tingyi_configured',False): return
    application._tingyi_configured=True
    application.setStyle('Fusion')
    families=set(QFontDatabase.families())
    if 'Microsoft YaHei UI' not in families and 'Microsoft YaHei' not in families:
        folder=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('msyh.ttc','msyhbd.ttc'):
            path=folder/name
            if path.is_file(): QFontDatabase.addApplicationFont(str(path))
    families=set(QFontDatabase.families())
    family='Microsoft YaHei UI' if 'Microsoft YaHei UI' in families else 'Microsoft YaHei' if 'Microsoft YaHei' in families else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    application.setFont(QFont(family,10))
