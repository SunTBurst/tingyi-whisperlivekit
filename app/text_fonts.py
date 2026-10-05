"""Use installed script-capable fonts without changing saved preferences."""
from functools import lru_cache
import os
from pathlib import Path
from PyQt6.QtGui import QFontDatabase

@lru_cache(maxsize=32)
def _arabic_family(preferred: str) -> str:
    families = set(QFontDatabase.families())
    # The bundled Qt runtime can initially enumerate only its registered CJK
    # fonts. Register an existing Windows font; never fetch or install fonts.
    font_dir=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for filename in ('segoeui.ttf','arial.ttf','NotoSansArabic-Regular.ttf','tahoma.ttf'):
        if any(family in families and QFontDatabase.WritingSystem.Arabic in QFontDatabase.writingSystems(family)
               for family in (preferred,'Segoe UI','Arial','Noto Sans Arabic','Tahoma')):
            break
        path=font_dir/filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
            families=set(QFontDatabase.families())
    for family in (preferred, "Segoe UI", "Arial", "Noto Sans Arabic", "Tahoma"):
        if family in families and QFontDatabase.WritingSystem.Arabic in QFontDatabase.writingSystems(family):
            return family
    return preferred

def caption_font_family(text: str, preferred: str = "Microsoft YaHei UI") -> str:
    if any("\u0600" <= char <= "\u06ff" for char in str(text)):
        return _arabic_family(preferred)
    return preferred

def css_family(text: str, preferred: str = "Microsoft YaHei UI") -> str:
    return caption_font_family(text, preferred).replace('"', '').replace('\\', '')
