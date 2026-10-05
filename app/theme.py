"""Shared palette and Qt stylesheet for the desktop application."""

from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_CHECK_ICON = (_ASSETS / "theme-check.svg").as_posix()
_ARROW_ICON = (_ASSETS / "theme-arrow-down.svg").as_posix()
_UP_ICON = (_ASSETS / "theme-arrow-up.svg").as_posix()
_LIGHT_DOWN_ICON = (_ASSETS / "theme-arrow-down-light.svg").as_posix()
_LIGHT_UP_ICON = (_ASSETS / "theme-arrow-up-light.svg").as_posix()
_LIGHT_CHECK_ICON = (_ASSETS / "theme-check-light.svg").as_posix()
_SPRING_DOWN_ICON = (_ASSETS / "theme-arrow-down-spring.svg").as_posix()
_SPRING_UP_ICON = (_ASSETS / "theme-arrow-up-spring.svg").as_posix()

STYLE = """
QMainWindow, QDialog { background: #101720; color: #e8eef5; }
QWidget { color: #e8eef5; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QFrame#surface { background: #18232f; border: 1px solid #344656; border-radius: 14px; }
QFrame#softSurface { background: #141e29; border: 1px solid #2c3b49; border-radius: 12px; }
QTabWidget::pane { background: #141e29; border: 1px solid #344656; border-radius: 8px; }
QTabBar::tab { background: #18232f; color: #aab7c4; padding: 9px 15px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #244b5a; color: #ffffff; }
QGroupBox { border: 1px solid #405364; border-radius: 9px; margin-top: 10px; padding-top: 7px; color: #c8d4df; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QLabel#muted { color: #91a1b2; }
QLabel#eyebrow { color: #7f91a3; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel#title { color: #f4f7fa; font-size: 20px; font-weight: 700; }
QLabel#captionText { color: #f3f7fa; font-size: 22px; }
QLabel#translationText { color: #91d9e6; font-size: 18px; }
QLabel#compactCaptionText { color: #f3f7fa; font-size: 18px; }
QLabel#compactTranslationText { color: #91d9e6; font-size: 15px; }
QLabel#draftText { color: #b2c1cf; font-size: 16px; }
QComboBox, QSpinBox { background: #111a23; border: 1px solid #405363; border-radius: 8px; padding: 8px 10px; min-height: 20px; }
QComboBox:hover, QSpinBox:hover { border-color: #55a2b6; }
QComboBox:focus, QSpinBox:focus { border: 1px solid #36b5c6; }
QComboBox::drop-down { width: 27px; border-left: 1px solid #405363; border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QComboBox::down-arrow { image: url("_ARROW_ICON_"); width: 12px; height: 8px; margin-right: 8px; }
QLineEdit, QTextEdit, QPlainTextEdit { background: #111a23; border: 1px solid #405363; border-radius: 8px; padding: 7px 9px; selection-background-color: #244b5a; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: #36b5c6; }
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { color: #687887; background: #141c25; border-color: #303d48; }
QComboBox QAbstractItemView { background: #18232f; border: 1px solid #405363; selection-background-color: #244b5a; outline: 0; }
QPushButton { background: #22313e; border: 1px solid #405363; border-radius: 9px; padding: 9px 14px; color: #e8eef5; font-weight: 600; }
QPushButton:hover { background: #2a3c4a; border-color: #5b8295; }
QPushButton:pressed { background: #1b2934; }
QPushButton:disabled { color: #687887; background: #19232c; border-color: #303d48; }
QPushButton#primary { background: #167b8d; border: 1px solid #2297a9; color: white; padding-left: 18px; padding-right: 18px; }
QPushButton#primary:hover { background: #198da0; }
QPushButton#danger { color: #ffb4a9; border-color: #704542; background: #302324; }
QPushButton#iconButton { padding: 7px 10px; }
QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget::item { color: #c5d0db; padding: 7px 5px; border-bottom: 1px solid #2e3d49; }
QScrollArea { border: 0; background: transparent; }
QScrollArea QWidget { background: transparent; }
QScrollBar:vertical { background: #111a23; width: 8px; margin: 2px 1px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #405363; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #5b7688; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: #111a23; height: 8px; margin: 1px 2px; border-radius: 4px; }
QScrollBar::handle:horizontal { background: #405363; min-width: 28px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #5b7688; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QProgressBar { border: 0; border-radius: 3px; background: #273542; max-height: 6px; text-align: center; }
QProgressBar::chunk { border-radius: 3px; background: #36b5c6; }
QSlider::groove:horizontal { height: 4px; background: #31414e; border-radius: 2px; }
QSlider::handle:horizontal { background: #47bfce; width: 14px; margin: -5px 0; border-radius: 7px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox::indicator:unchecked { border: 1px solid #687b8a; border-radius: 4px; background: #111a23; }
QCheckBox::indicator:checked { border: 1px solid #36aabe; border-radius: 4px; background: #167b8d; image: url("_CHECK_ICON_"); }
"""

STYLE = STYLE.replace("_CHECK_ICON_", _CHECK_ICON).replace("_ARROW_ICON_", _ARROW_ICON)
STYLE+='''
QSpinBox::up-button, QDoubleSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;width:22px;background:#22313e;border-left:1px solid #405363;}
QSpinBox::down-button, QDoubleSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;width:22px;background:#22313e;border-left:1px solid #405363;}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {image:url("__UP_ICON__");width:10px;height:7px;}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {image:url("__DOWN_ICON__");width:10px;height:7px;}
'''.replace('__UP_ICON__',_UP_ICON).replace('__DOWN_ICON__',_ARROW_ICON)

# Native controls keep the existing charcoal / teal palette, with lighter
# borders and compact hit areas. IDs keep caption-specific tokens scoped.
STYLE += '''
QFrame#surface { border-color:#2d414e; border-radius:10px; }
QFrame#softSurface { border-color:#273946; border-radius:9px; }
QTabWidget::pane { border-color:#2d414e; }
QTabBar::tab { padding:7px 12px; }
QTabBar::tab:selected { background:#1d3b47; color:#f4fbfc; }
QGroupBox { border-color:#344b59; border-radius:7px; padding-top:5px; }
QComboBox, QSpinBox { border-color:#344957; border-radius:6px; padding:6px 8px; }
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { color:#9aaab5; background:#1b252e; border-color:#34414c; }
QLineEdit, QTextEdit, QPlainTextEdit { border-color:#344957; border-radius:6px; padding:6px 8px; }
QPushButton { border-color:#344957; border-radius:6px; padding:7px 11px; }
QPushButton:hover { background:#29414d; border-color:#4a8796; }
QPushButton:pressed { background:#1b303a; border-color:#3d7482; }
QPushButton:disabled { color:#9aaab5; background:#1b252e; border-color:#34414c; }
QPushButton#primary { background:#167b8d; border-color:#2297a9; color:#ffffff; }
QPushButton#primary:disabled { color:#b6c6ce; background:#29424b; border-color:#38545e; }
QPushButton#danger { color:#ffb4a9; border-color:#704542; background:#302324; }
QPushButton#danger:disabled { color:#bd918c; background:#282325; border-color:#514044; }
QPushButton#iconButton { padding:5px; min-width:30px; min-height:30px; }
QComboBox QAbstractItemView { background:#18232f; color:#e8eef5; border:1px solid #3a5260; selection-background-color:#244b5a; selection-color:#ffffff; }
QMenu { background:#18232f; color:#e8eef5; border:1px solid #3a5260; padding:4px; }
QMenu::item { padding:6px 24px 6px 9px; border-radius:4px; }
QMenu::item:selected { color:#ffffff; background:#244b5a; }
QMenu::item:disabled { color:#9aaab5; }
QMenu::separator { height:1px; background:#344957; margin:4px 6px; }
QToolTip { color:#f3f7fa; background:#1b2934; border:1px solid #405c6a; padding:5px 7px; }
QCheckBox:disabled { color:#9aaab5; }
QCheckBox::indicator:disabled { border-color:#566572; background:#1b252e; }
QCheckBox::indicator:checked:disabled { border-color:#566572; background:#334650; image:url("_CHECK_ICON_"); }
QScrollBar:vertical { background:#111a23; width:7px; margin:2px 1px; }
QScrollBar::handle:vertical { background:#4b6473; min-height:25px; border-radius:3px; }
QScrollBar::handle:vertical:hover { background:#66889a; }
QScrollBar:horizontal { height:7px; }
QScrollBar::handle:horizontal { background:#4b6473; min-width:25px; border-radius:3px; }
QScrollBar::handle:horizontal:hover { background:#66889a; }
QLabel#overlayStatus { color:#71d3dc; font-size:12px; font-weight:600; }
QLabel#overlayAudioSource { color:#c4e3e8; background:#203743; border:1px solid #345863; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:600; }
QLabel#emptyState { color:#b4c3cd; background:#141e29; border:1px solid #2b3d49; border-radius:7px; padding:10px 12px; }
'''.replace("_CHECK_ICON_", _CHECK_ICON)


# The default stylesheet above remains the compatibility surface for existing
# dialogs and the subtitle overlay. New callers can select a palette explicitly.
THEME_CHOICES = (("深色·静谧", "dark"), ("晴空蓝", "sky"), ("春意绿", "spring"))

_PALETTES = {
    "dark": {
        "window": "#101720", "surface": "#18232f", "soft_surface": "#141e29",
        "field": "#111a23", "text": "#e8eef5", "muted": "#aab7c4",
        "border": "#344957", "accent": "#167b8d", "accent_hover": "#198da0",
        "accent_text": "#ffffff", "translation": "#91d9e6", "draft_bg": "#141e29",
        "draft_text": "#b2c1cf", "toast_bg": "#1b2934", "toast_text": "#f3f7fa",
        "warning": "#f0c674", "error": "#ffb4a9", "disabled_text": "#9aaab5",
        "disabled_bg": "#1b252e", "icon": "#c5d8e0", "icon_active": "#71d3dc",
        "icon_disabled": "#71838e",
    },
    "sky": {
        "window": "#f1f7fb", "surface": "#ffffff", "soft_surface": "#eaf3f9",
        "field": "#ffffff", "text": "#183044", "muted": "#4b6376",
        "border": "#c5d5e0", "accent": "#246b91", "accent_hover": "#1d5879",
        "accent_text": "#ffffff", "translation": "#286a82", "draft_bg": "#edf4f8",
        "draft_text": "#456174", "toast_bg": "#183044", "toast_text": "#ffffff",
        "warning": "#805000", "error": "#9c3030", "disabled_text": "#576b79",
        "disabled_bg": "#e5edf2", "icon": "#526d80", "icon_active": "#1d5879",
        "icon_disabled": "#748793",
    },
    "spring": {
        "window": "#f2f7ef", "surface": "#ffffff", "soft_surface": "#eaf2e6",
        "field": "#ffffff", "text": "#1e3525", "muted": "#4c6651",
        "border": "#c8d6c4", "accent": "#326943", "accent_hover": "#285638",
        "accent_text": "#ffffff", "translation": "#2d6d56", "draft_bg": "#edf4e9",
        "draft_text": "#48634d", "toast_bg": "#1e3525", "toast_text": "#ffffff",
        "warning": "#805000", "error": "#983535", "disabled_text": "#596d57",
        "disabled_bg": "#e6ede3", "icon": "#536d58", "icon_active": "#285638",
        "icon_disabled": "#758674",
    },
}


def normalize_theme(value):
    """Return a supported theme id, falling back safely to the legacy dark theme."""
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in _PALETTES:
            return candidate
        for label, theme_id in THEME_CHOICES:
            if value == label:
                return theme_id
    return "dark"


def palette_for(theme_id):
    """Return a fresh mapping of semantic colors for a theme."""
    return dict(_PALETTES[normalize_theme(theme_id)])


def _complete_controls(p):
    """Shared rules for auxiliary tools and Qt-created transient surfaces."""
    return f'''
QAbstractItemView {{ background:{p['surface']}; color:{p['text']}; alternate-background-color:{p['soft_surface']}; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; outline:0; }}
QAbstractItemView::item:selected {{ background:{p['accent']}; color:{p['accent_text']}; }}
QAbstractItemView::item:selected:disabled {{ background:{p['disabled_bg']}; color:{p['disabled_text']}; }}
QTableView, QTreeView {{ background:{p['surface']}; color:{p['text']}; alternate-background-color:{p['soft_surface']}; gridline-color:{p['border']}; border:1px solid {p['border']}; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; }}
QHeaderView {{ background:{p['soft_surface']}; color:{p['text']}; }}
QHeaderView::section {{ color:{p['text']}; background:{p['soft_surface']}; border:0; border-right:1px solid {p['border']}; border-bottom:1px solid {p['border']}; padding:5px 7px; }}
QTableCornerButton::section {{ background:{p['soft_surface']}; border:1px solid {p['border']}; }}
QDoubleSpinBox {{ background:{p['field']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:6px; padding:6px 8px; min-height:20px; }}
QDoubleSpinBox:disabled {{ background:{p['disabled_bg']}; color:{p['disabled_text']}; }}
QPushButton:checked {{ background:{p['accent']}; color:{p['accent_text']}; border-color:{p['accent']}; }}
QToolButton {{ background:{p['soft_surface']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:5px; padding:5px; }}
QToolButton:hover {{ background:{p['surface']}; border-color:{p['accent']}; }}
QToolButton:pressed, QToolButton:checked {{ background:{p['accent']}; color:{p['accent_text']}; }}
QToolButton:disabled {{ background:{p['disabled_bg']}; color:{p['disabled_text']}; border-color:{p['border']}; }}
QRadioButton {{ color:{p['text']}; spacing:8px; }}
QRadioButton:disabled {{ color:{p['disabled_text']}; }}
QRadioButton::indicator {{ width:16px; height:16px; border:1px solid {p['muted']}; border-radius:8px; background:{p['field']}; }}
QRadioButton::indicator:checked {{ background:{p['accent']}; border:3px solid {p['field']}; }}
QRadioButton::indicator:disabled {{ border-color:{p['border']}; background:{p['disabled_bg']}; }}
QRadioButton::indicator:checked:disabled {{ background:{p['disabled_text']}; }}
QMenuBar {{ background:{p['window']}; color:{p['text']}; }}
QMenuBar::item:selected {{ background:{p['accent']}; color:{p['accent_text']}; }}
QStatusBar {{ background:{p['window']}; color:{p['muted']}; }}
QSplitter::handle {{ background:{p['border']}; }}
QToolTip {{ color:{p['text']}; background:{p['surface']}; border:1px solid {p['border']}; padding:5px 7px; }}
QLabel#warning {{ color:{p['warning']}; }}
QLabel#error {{ color:{p['error']}; }}
QComboBoxPrivateContainer {{ background:{p['surface']}; border:1px solid {p['border']}; }}
'''


STYLE += _complete_controls(palette_for('dark'))


def style_for(theme_id):
    """Build a complete, layout-preserving Qt stylesheet for a theme."""
    theme_id = normalize_theme(theme_id)
    if theme_id == "dark":
        return STYLE
    p = palette_for(theme_id)
    arrow_down = _SPRING_DOWN_ICON if theme_id == "spring" else _LIGHT_DOWN_ICON
    arrow_up = _SPRING_UP_ICON if theme_id == "spring" else _LIGHT_UP_ICON
    check_icon = _LIGHT_CHECK_ICON
    # Dimensions, spacing and radii intentionally follow the established UI.
    return f'''\
QMainWindow, QDialog {{ background:{p['window']}; color:{p['text']}; }}
QWidget {{ color:{p['text']}; font-family:"Microsoft YaHei UI", "Segoe UI", sans-serif; font-size:13px; }}
QWidget:disabled {{ color:{p['disabled_text']}; }}
QFrame#surface {{ background:{p['surface']}; border:1px solid {p['border']}; border-radius:10px; }}
QFrame#softSurface {{ background:{p['soft_surface']}; border:1px solid {p['border']}; border-radius:9px; }}
QTabWidget::pane {{ background:{p['soft_surface']}; border:1px solid {p['border']}; border-radius:8px; }}
QTabBar::tab {{ background:{p['surface']}; color:{p['muted']}; padding:7px 12px; margin-right:3px; border-top-left-radius:7px; border-top-right-radius:7px; }}
QTabBar::tab:hover {{ background:{p['soft_surface']}; color:{p['text']}; }}
QTabBar::tab:selected {{ background:{p['accent']}; color:{p['accent_text']}; }}
QGroupBox {{ border:1px solid {p['border']}; border-radius:7px; margin-top:10px; padding-top:5px; color:{p['text']}; font-weight:600; }}
QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 5px; }}
QLabel#muted {{ color:{p['muted']}; }}
QLabel#eyebrow {{ color:{p['muted']}; font-size:11px; font-weight:600; letter-spacing:1px; }}
QLabel#title {{ color:{p['text']}; font-size:20px; font-weight:700; }}
QLabel#captionText, QLabel#compactCaptionText {{ color:{p['text']}; }}
QLabel#captionText {{ font-size:22px; }}
QLabel#compactCaptionText {{ font-size:18px; }}
QLabel#translationText {{ color:{p['translation']}; font-size:18px; }}
QLabel#compactTranslationText {{ color:{p['translation']}; font-size:15px; }}
QLabel#draftText {{ color:{p['draft_text']}; background:{p['draft_bg']}; font-size:16px; }}
QLabel#warning {{ color:{p['warning']}; }}
QLabel#error {{ color:{p['error']}; }}
QComboBox, QSpinBox, QDoubleSpinBox {{ background:{p['field']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:6px; padding:6px 8px; min-height:20px; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color:{p['accent']}; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border:1px solid {p['accent_hover']}; }}
QComboBox::drop-down {{ width:27px; border-left:1px solid {p['border']}; border-top-right-radius:6px; border-bottom-right-radius:6px; }}
QComboBox::down-arrow {{ image:url("{arrow_down}"); width:12px; height:8px; margin-right:8px; }}
QLineEdit, QTextEdit, QPlainTextEdit {{ background:{p['field']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:6px; padding:6px 8px; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border:1px solid {p['accent_hover']}; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ color:{p['disabled_text']}; background:{p['disabled_bg']}; border-color:{p['border']}; }}
QComboBox QAbstractItemView {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['border']}; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; outline:0; }}
QAbstractItemView {{ background:{p['surface']}; color:{p['text']}; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; outline:0; }}
QTableView {{ background:{p['surface']}; color:{p['text']}; alternate-background-color:{p['soft_surface']}; gridline-color:{p['border']}; border:1px solid {p['border']}; selection-background-color:{p['accent']}; selection-color:{p['accent_text']}; }}
QHeaderView::section {{ color:{p['text']}; background:{p['soft_surface']}; border:0; border-bottom:1px solid {p['border']}; }}
QPushButton {{ background:{p['soft_surface']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:6px; padding:7px 11px; font-weight:600; }}
QPushButton:hover {{ background:{p['surface']}; border-color:{p['accent']}; }}
QPushButton:pressed {{ background:{p['border']}; }}
QPushButton:focus {{ border:2px solid {p['accent']}; }}
QPushButton:disabled {{ color:{p['disabled_text']}; background:{p['disabled_bg']}; border-color:{p['border']}; }}
QPushButton#primary {{ background:{p['accent']}; border:1px solid {p['accent']}; color:{p['accent_text']}; padding-left:18px; padding-right:18px; }}
QPushButton#primary:hover {{ background:{p['accent_hover']}; border-color:{p['accent_hover']}; }}
QPushButton#primary:disabled {{ color:{p['disabled_text']}; background:{p['disabled_bg']}; border-color:{p['border']}; }}
QPushButton#danger {{ color:{p['error']}; border-color:{p['error']}; background:{p['surface']}; }}
QPushButton#danger:disabled {{ color:{p['disabled_text']}; background:{p['disabled_bg']}; border-color:{p['border']}; }}
QPushButton#iconButton {{ padding:5px; min-width:30px; min-height:30px; color:{p['icon']}; }}
QPushButton#iconButton:hover, QPushButton#iconButton:checked {{ color:{p['icon_active']}; }}
QPushButton#iconButton:disabled {{ color:{p['disabled_text']}; background:{p['disabled_bg']}; }}
QListWidget {{ background:transparent; border:0; outline:0; }}
QListWidget::item {{ color:{p['text']}; padding:7px 5px; border-bottom:1px solid {p['border']}; }}
QListWidget::item:hover {{ background:{p['soft_surface']}; }}
QListWidget::item:selected {{ color:{p['accent_text']}; background:{p['accent']}; }}
QScrollArea {{ border:0; background:transparent; }}
QScrollArea QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:{p['soft_surface']}; width:7px; margin:2px 1px; }}
QScrollBar::handle:vertical {{ background:{p['icon']}; min-height:25px; border-radius:3px; }}
QScrollBar::handle:vertical:hover {{ background:{p['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; background:transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
QScrollBar:horizontal {{ background:{p['soft_surface']}; height:7px; margin:1px 2px; }}
QScrollBar::handle:horizontal {{ background:{p['icon']}; min-width:25px; border-radius:3px; }}
QScrollBar::handle:horizontal:hover {{ background:{p['accent']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; background:transparent; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background:transparent; }}
QProgressBar {{ border:0; border-radius:3px; background:{p['soft_surface']}; max-height:6px; text-align:center; }}
QProgressBar::chunk {{ border-radius:3px; background:{p['accent']}; }}
QSlider::groove:horizontal {{ height:4px; background:{p['border']}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:{p['accent']}; width:14px; margin:-5px 0; border-radius:7px; }}
QCheckBox {{ spacing:8px; }}
QCheckBox:disabled {{ color:{p['disabled_text']}; }}
QCheckBox::indicator {{ width:17px; height:17px; }}
QCheckBox::indicator:unchecked {{ border:1px solid {p['muted']}; border-radius:4px; background:{p['field']}; }}
QCheckBox::indicator:checked {{ border:1px solid {p['accent']}; border-radius:4px; background:{p['accent']}; image:url("{check_icon}"); }}
QCheckBox::indicator:disabled {{ border-color:{p['border']}; background:{p['disabled_bg']}; }}
QCheckBox::indicator:checked:disabled {{ border-color:{p['border']}; background:{p['disabled_text']}; image:url("{check_icon}"); }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:22px; background:{p['soft_surface']}; border-left:1px solid {p['border']}; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:22px; background:{p['soft_surface']}; border-left:1px solid {p['border']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image:url("{arrow_up}"); width:10px; height:7px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image:url("{arrow_down}"); width:10px; height:7px; }}
QMenu {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['border']}; padding:4px; }}
QMenu::item {{ padding:6px 24px 6px 9px; border-radius:4px; }}
QMenu::item:selected {{ color:{p['accent_text']}; background:{p['accent']}; }}
QMenu::item:disabled {{ color:{p['disabled_text']}; }}
QMenu::separator {{ height:1px; background:{p['border']}; margin:4px 6px; }}
QToolTip {{ color:{p['toast_text']}; background:{p['toast_bg']}; border:1px solid {p['border']}; padding:5px 7px; }}
QFrame#toast {{ color:{p['toast_text']}; background:{p['toast_bg']}; border:1px solid {p['border']}; border-radius:6px; }}
QLabel#overlayStatus {{ color:{p['translation']}; font-size:12px; font-weight:600; }}
QLabel#overlayAudioSource {{ color:{p['text']}; background:{p['soft_surface']}; border:1px solid {p['border']}; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:600; }}
QLabel#emptyState {{ color:{p['muted']}; background:{p['soft_surface']}; border:1px solid {p['border']}; border-radius:7px; padding:10px 12px; }}
''' + _complete_controls(p)
