"""Tiny stroke icon set rendered from inline SVG, tinted on demand and cached."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "download": '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>',
    "video": '<rect x="2.5" y="6" width="14" height="12" rx="2.5"/><path d="M16.5 10.5 21.5 7.5v9l-5-3"/>',
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
    "settings": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.5"/>'
                '<path d="M4 12h2"/><path d="M12 12h8"/><circle cx="9" cy="12" r="2.5"/>'
                '<path d="M4 18h11"/><circle cx="18" cy="18" r="2.5"/>',
    "activity": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "paste": '<rect x="8" y="3" width="8" height="4" rx="1.2"/>'
             '<path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/>',
    "x": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "retry": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3 4v5h5"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="currentColor"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6 7l1 13h10l1-13"/>',
    "pause": '<path d="M8 5v14"/><path d="M16 5v14"/>',
    "resume": '<path d="M7 4.5v15l12.5-7.5z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "link": '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4l-1 1"/>'
            '<path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
    "list": '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="M4 6h.01"/><path d="M4 12h.01"/><path d="M4 18h.01"/>',
    "up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"/>',
    "sparkle": '<path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/>'
               '<path d="m6 6 2.5 2.5"/><path d="m15.5 15.5 2.5 2.5"/><path d="m18 6-2.5 2.5"/><path d="m8.5 15.5-2.5 2.5"/>',
    "playlist": '<path d="M4 6h12"/><path d="M4 12h12"/><path d="M4 18h7"/><path d="M15 15.5v5l4.5-2.5z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}

_cache: dict = {}


def svg(name: str, color: str) -> bytes:
    body = _PATHS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>').encode()


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is None:
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg(name, color))).render(p, QRectF(0, 0, size * dpr, size * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


def paint(p: QPainter, name: str, color: str, rect, size: int = 18):
    """Draw an icon centered in `rect` (QRect/QRectF)."""
    pm = pixmap(name, color, size)
    x = rect.x() + (rect.width() - size) / 2
    y = rect.y() + (rect.height() - size) / 2
    p.drawPixmap(int(x), int(y), pm)
