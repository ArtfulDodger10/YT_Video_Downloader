"""Small custom widgets: toggle switch, segmented control, chips, spinner, toast, info bar."""

from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget)

from . import icons
from . import theme


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text: str = "", icon: str = "", primary: bool = False, flat: bool = False,
           tooltip: str = "", danger: bool = False) -> QPushButton:
    b = QPushButton(f" {text}" if icon and text else text)  # breathing room after the icon
    if primary:
        b.setProperty("primary", True)
    if flat:
        b.setProperty("flat", True)
    if danger:
        b.setProperty("danger", True)
    if icon:
        b.setProperty("iconName", icon)
        refresh_icon(b)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def icon_button(icon: str, tooltip: str, size: int = 18) -> QPushButton:
    b = QPushButton()
    b.setObjectName("IconButton")
    b.setProperty("iconName", icon)
    b.setProperty("iconPx", size)
    b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    refresh_icon(b)
    return b


def refresh_icon(b: QPushButton):
    """(Re)tint a button's icon for the current theme."""
    name = b.property("iconName")
    if not name:
        return
    size = b.property("iconPx") or 17
    col = theme.current()["on_accent"] if b.property("primary") else theme.current()["muted"]
    b.setIcon(icons.icon(name, col, size))
    b.setIconSize(QSize(size, size))


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    return f


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(42, 24)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def setChecked(self, on):  # keep the knob in sync when set programmatically
        super().setChecked(on)
        if not self._anim_running():
            self._pos = 1.0 if on else 0.0
            self.update()

    def _anim_running(self):
        return hasattr(self, "_anim") and self._anim.state() == QPropertyAnimation.Running

    def paintEvent(self, _):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 2, 40, 20)
        off, on = QColor(t["surface3"]), QColor(t["accent"])
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 10, 10)
        p.setBrush(QColor("#ffffff"))
        x = r.x() + 3 + self._pos * (r.width() - 20)
        p.drawEllipse(QRectF(x, r.y() + 3, 14, 14))


class Segmented(QFrame):
    """A pill-shaped group of mutually exclusive buttons."""
    changed = Signal(str)

    def __init__(self, options, value: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons = {}
        for opt in options:
            val, text, icon = (opt + ("",))[:3] if len(opt) < 3 else opt
            b = QPushButton(f" {text}" if icon else text)
            b.setObjectName("SegButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if icon:
                b.setProperty("iconName", icon)
                refresh_icon(b)
            self._group.addButton(b)
            self._buttons[val] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, v=val: self.changed.emit(v))
        self.set_value(value or next(iter(self._buttons)))

    def set_value(self, value: str):
        if value in self._buttons:
            self._buttons[value].setChecked(True)

    def value(self) -> str:
        for v, b in self._buttons.items():
            if b.isChecked():
                return v
        return ""

    def set_label(self, value: str, text: str):
        b = self._buttons[value]
        b.setText(f" {text}" if b.property("iconName") else text)

    def refresh_icons(self):
        for b in self._buttons.values():
            refresh_icon(b)


class Chip(QPushButton):
    def __init__(self, text: str, checkable: bool = True, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)


class Spinner(QWidget):
    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def _step(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def showEvent(self, e):
        self._timer.start(16)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(theme.color("accent"), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = 2
        p.drawArc(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m),
                  -self._angle * 16, 270 * 16)


class Thumb(QWidget):
    """Rounded 16:9 image with a placeholder icon and an optional corner badge."""

    def __init__(self, w: int = 192, h: int = 108, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._pm: QPixmap | None = None
        self._badge = ""
        self._icon = "video"

    def set_pixmap(self, pm):
        self._pm = pm
        self.update()

    def set_badge(self, text: str):
        self._badge = text
        self.update()

    def set_icon(self, name: str):
        self._icon = name
        self.update()

    def paintEvent(self, _):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        p.fillRect(r, QColor(t["surface3"]))
        if self._pm and not self._pm.isNull():
            paint_cover(p, self._pm, r)
        else:
            icons.paint(p, self._icon, t["faint"], self.rect(), 30)
        if self._badge:
            draw_badge(p, r, self._badge)


def paint_cover(p: QPainter, pm: QPixmap, r: QRectF):
    """Draw `pm` scaled to cover `r` (center-cropped)."""
    iw, ih = pm.width(), pm.height()
    if not iw or not ih:
        return
    scale = max(r.width() / iw, r.height() / ih)
    sw, sh = r.width() / scale, r.height() / scale
    src = QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh)
    p.drawPixmap(r, pm, src)


def draw_badge(p: QPainter, r: QRectF, text: str):
    f = p.font()
    f.setPointSizeF(8)
    f.setBold(True)
    p.setFont(f)
    tw = p.fontMetrics().horizontalAdvance(text) + 10
    br = QRectF(r.right() - tw - 5, r.bottom() - 20, tw, 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 185))
    p.drawRoundedRect(br, 4, 4)
    p.setPen(QColor("#ffffff"))
    p.drawText(br, Qt.AlignCenter, text)


class Toast(QLabel):
    """Transient message floating near the bottom of its parent."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._timer = QTimer(self, singleShot=True, timeout=self._fade)
        self._anim.finished.connect(lambda: self._fx.opacity() < 0.05 and self.hide())
        self.hide()

    def show_message(self, text: str, ms: int = 2600):
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)
        self._anim.stop()
        self._fx.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _fade(self):
        self._anim.setDuration(350)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()


class InfoBar(QFrame):
    """Dismissable banner with an optional action button."""

    def __init__(self, level: str = "info", parent=None):
        super().__init__(parent)
        self.setObjectName("InfoBar")
        self.setProperty("level", level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = label(wrap=True)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.action = button(flat=False)
        self.close_btn = icon_button("x", "Dismiss", 15)
        self.close_btn.clicked.connect(self.hide)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.action)
        lay.addWidget(self.close_btn)
        self._level = level
        self.refresh()
        self.hide()

    def set(self, text: str, action_text: str = "", level: str | None = None):
        if level:
            self._level = level
            self.setProperty("level", level)
            self.style().unpolish(self)
            self.style().polish(self)
        self.text.setText(text)
        self.action.setVisible(bool(action_text))
        self.action.setText(action_text)
        self.refresh()
        self.show()

    def refresh(self):
        t = theme.current()
        col = t["warn"] if self._level == "warn" else t["accent"]
        self.icon.setPixmap(icons.pixmap("alert" if self._level == "warn" else "info", col, 18))
        refresh_icon(self.close_btn)
