"""Color tokens and the application stylesheet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

DARK = {
    "bg": "#0f1116", "sidebar": "#12151c", "surface": "#181c24", "surface2": "#1f242e",
    "surface3": "#2a303c", "border": "#262c37", "border2": "#343b48", "text": "#e9ecf2",
    "muted": "#8d96a8", "faint": "#5f687a", "accent": "#7c6cff", "accent2": "#4f8cff",
    "accent_soft": "#262245", "on_accent": "#ffffff", "ok": "#3ddc97", "warn": "#ffb454",
    "err": "#ff5d6c", "info": "#5ab0ff", "shadow": "#000000",
}
LIGHT = {
    "bg": "#f4f5f9", "sidebar": "#eceef4", "surface": "#ffffff", "surface2": "#f2f3f7",
    "surface3": "#e5e8ef", "border": "#e1e4ec", "border2": "#cfd4de", "text": "#151922",
    "muted": "#5b6577", "faint": "#99a1b1", "accent": "#6a5cff", "accent2": "#3f7bff",
    "accent_soft": "#ebe8ff", "on_accent": "#ffffff", "ok": "#10a36a", "warn": "#c07a09",
    "err": "#e0364a", "info": "#2f7fe0", "shadow": "#8890a0",
}

_current = dict(DARK)


def current() -> dict:
    return _current


def color(name: str) -> QColor:
    return QColor(_current[name])


def resolve(mode: str) -> dict:
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return LIGHT if scheme == Qt.ColorScheme.Light else DARK
    except Exception:
        return DARK


def apply(app, mode: str, asset_dir: Path) -> dict:
    """Apply palette + stylesheet. `asset_dir` receives small generated SVGs used by QSS."""
    global _current
    t = resolve(mode)
    _current.clear()
    _current.update(t)

    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "surface"),
                      (QPalette.AlternateBase, "surface2"), (QPalette.Text, "text"),
                      (QPalette.WindowText, "text"), (QPalette.Button, "surface2"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "surface3"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "faint")):
        pal.setColor(role, QColor(t[key]))
    app.setPalette(pal)

    asset_dir.mkdir(parents=True, exist_ok=True)
    arrow = asset_dir / f"chevron-{t['muted'][1:]}.svg"
    if not arrow.exists():
        arrow.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14">'
            f'<path d="M6 9l6 6 6-6" fill="none" stroke="{t["muted"]}" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    app.setStyleSheet(stylesheet(t, arrow.as_posix()))
    return t


def stylesheet(t: dict, arrow: str) -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-size: 10pt; }}
QMainWindow, #Page, #Central {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface3']}; color: {t['text']}; border: 1px solid {t['border2']};
    border-radius: 6px; padding: 6px 8px; }}

/* sidebar */
#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
#Brand {{ font-size: 13pt; font-weight: 700; }}
#BrandSub {{ color: {t['faint']}; font-size: 8.5pt; }}
#NavButton {{ text-align: left; padding: 9px 12px; border: none; border-radius: 9px;
    background: transparent; color: {t['muted']}; font-weight: 600; }}
#NavButton:hover {{ background: {t['surface2']}; color: {t['text']}; }}
#NavButton:checked {{ background: {t['accent_soft']}; color: {t['text']}; }}
#NavBadge {{ background: {t['accent']}; color: {t['on_accent']}; border-radius: 8px;
    padding: 0 6px; font-size: 8pt; font-weight: 700; }}
#ToolPill {{ color: {t['muted']}; font-size: 8.5pt; }}

/* typography */
#H1 {{ font-size: 18pt; font-weight: 700; }}
#H2 {{ font-size: 11.5pt; font-weight: 700; }}
#Muted {{ color: {t['muted']}; }}
#Faint {{ color: {t['faint']}; font-size: 9pt; }}
#Error {{ color: {t['err']}; }}
#Hint {{ color: {t['warn']}; }}

/* cards */
#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
#InputCard {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 16px; }}
#InfoBar {{ background: {t['surface']}; border: 1px solid {t['border2']}; border-radius: 12px; }}
#InfoBar[level="warn"] {{ border-color: {t['warn']}; }}
#InfoBar[level="info"] {{ border-color: {t['accent']}; }}
#Toast {{ background: {t['surface3']}; color: {t['text']}; border: 1px solid {t['border2']};
    border-radius: 10px; padding: 10px 16px; font-weight: 600; }}
#Empty {{ color: {t['muted']}; }}
#Divider {{ background: {t['border']}; max-height: 1px; min-height: 1px; }}

/* buttons */
QPushButton {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {t['surface3']}; border-color: {t['border2']}; }}
QPushButton:pressed {{ background: {t['border2']}; }}
QPushButton:disabled {{ color: {t['faint']}; background: {t['surface']}; }}
QPushButton[primary="true"] {{ border: none; color: {t['on_accent']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t['accent']}, stop:1 {t['accent2']}); }}
QPushButton[primary="true"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t['accent2']}, stop:1 {t['accent']}); }}
QPushButton[primary="true"]:disabled {{ background: {t['surface3']}; color: {t['faint']}; }}
QPushButton[flat="true"] {{ background: transparent; border: none; color: {t['muted']}; padding: 6px 10px; }}
QPushButton[flat="true"]:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QPushButton[danger="true"]:hover {{ color: {t['err']}; }}
#IconButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
#IconButton:hover {{ background: {t['surface3']}; }}

/* segmented control + chips */
#Segmented {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px; }}
#SegButton {{ background: transparent; border: none; border-radius: 7px; padding: 6px 14px;
    color: {t['muted']}; font-weight: 600; }}
#SegButton:hover {{ color: {t['text']}; }}
#SegButton:checked {{ background: {t['surface3']}; color: {t['text']}; }}
#Chip {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 13px;
    padding: 4px 12px; font-size: 9pt; font-weight: 600; color: {t['muted']}; }}
#Chip:hover {{ color: {t['text']}; border-color: {t['border2']}; }}
#Chip:checked {{ background: {t['accent_soft']}; color: {t['text']}; border-color: {t['accent']}; }}

/* inputs */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {t['surface2']};
    border: 1px solid {t['border']}; border-radius: 9px; padding: 7px 10px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {t['faint']}; }}
#BigInput {{ background: transparent; border: none; font-size: 12pt; padding: 8px 4px; }}
#BigInput:focus {{ border: none; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t['surface2']}; border: 1px solid {t['border2']};
    border-radius: 8px; padding: 4px; selection-background-color: {t['accent_soft']};
    selection-color: {t['text']}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; }}

/* lists and scrolling */
QListView {{ background: transparent; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['surface3']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['border2']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

QMenu {{ background: {t['surface2']}; border: 1px solid {t['border2']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['surface3']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 6px; }}
QMessageBox {{ background: {t['surface']}; }}
"""
