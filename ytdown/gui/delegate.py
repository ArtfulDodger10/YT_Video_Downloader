"""Paints each download as a card: thumbnail, title, details, progress and hover actions."""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolTip

from ..engine import ACTIVE, Job, Status
from ..util import human_bytes, human_eta
from . import icons, theme
from .model import JobRole
from .widgets import draw_badge, paint_cover

CARD_H = 96
RIGHT_W = 170

ACTION_LABELS = {"play": "Open file", "folder": "Show in folder", "retry": "Retry",
                 "stop": "Cancel", "x": "Cancel", "trash": "Remove from list"}


def site_name(key: str) -> str:
    key = key or ""
    for suffix in ("Tab", "Search", "Playlist", "Clip", "Video", "IE"):
        if key.endswith(suffix) and len(key) > len(suffix):
            key = key[: -len(suffix)]
    return {"Youtube": "YouTube", "Generic": "Web", "Http": "Web"}.get(key, key)


def fmt_duration(sec) -> str:
    if not isinstance(sec, (int, float)) or sec <= 0:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_label(job: Job) -> str:
    s = job.settings
    if s.mode == "audio":
        return (s.audio_format.upper() if s.audio_format != "original" else "Audio")
    q = job.format_note or ("Best" if s.video_quality == "best" else f"{s.video_quality}p")
    c = s.video_container.upper() if s.video_container != "original" else ""
    return f"{q} {c}".strip()


def actions_for(job: Job) -> list:
    st = job.status
    if st in ACTIVE:
        return ["stop"]
    if st == Status.QUEUED:
        return ["x", "trash"]
    if st == Status.DONE:
        return ["play", "folder", "trash"]
    return ["retry", "trash"]


class JobDelegate(QStyledItemDelegate):
    action = Signal(object, str)  # job, action name

    def __init__(self, thumbs, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        self._mouse = QPointF(-1, -1)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), CARD_H)

    # ---- geometry --------------------------------------------------------

    def _geo(self, rect, job: Job) -> dict:
        card = QRectF(rect).adjusted(2, 4, -10, -4)
        th = card.height() - 24
        thumb = QRectF(card.x() + 12, card.y() + 12, th * 16 / 9, th)
        cx = thumb.right() + 16
        rx = card.right() - RIGHT_W
        acts = actions_for(job)
        size = 32
        btns = {}
        x = card.right() - 12 - size * len(acts) - 4 * (len(acts) - 1)
        for a in acts:
            btns[a] = QRectF(x, card.center().y() - size / 2, size, size)
            x += size + 4
        return {"card": card, "thumb": thumb, "title": QRectF(cx, card.y() + 13, rx - cx - 12, 22),
                "meta": QRectF(cx, card.y() + 37, rx - cx - 12, 18),
                "bar": QRectF(cx, card.bottom() - 22, rx - cx - 12, 6),
                "status": QRectF(rx, card.y() + 14, RIGHT_W - 14, 20),
                "sub": QRectF(rx - 20, card.bottom() - 30, RIGHT_W + 6, 18),
                "buttons": btns}

    # ---- painting ----------------------------------------------------------

    def paint(self, p: QPainter, option, index):
        job: Job = index.data(JobRole)
        if job is None:
            return
        t = theme.current()
        g = self._geo(option.rect, job)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        card = g["card"]
        p.setPen(QColor(t["accent"]) if selected else QColor(t["border"]))
        p.setBrush(QColor(t["surface2"] if hovered else t["surface"]))
        p.drawRoundedRect(card, 12, 12)

        self._paint_thumb(p, g["thumb"], job, t)

        base = QFont(option.font)
        title_f = QFont(base)
        title_f.setPointSizeF(10.5)
        title_f.setWeight(QFont.DemiBold)
        small = QFont(base)
        small.setPointSizeF(9)

        p.setFont(title_f)
        p.setPen(QColor(t["text"]))
        p.drawText(g["title"], Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(title_f).elidedText(job.display_title, Qt.ElideRight, int(g["title"].width())))

        p.setFont(small)
        if job.status == Status.FAILED and job.error:
            p.setPen(QColor(t["err"]))
            meta = short_error(job.error)
        else:
            p.setPen(QColor(t["muted"]))
            size = job.total or (job.downloaded if job.is_finished else 0)
            site = site_name(job.site)
            parts = [job.uploader, site if site.lower() != job.uploader.lower() else "", format_label(job),
                     human_bytes(size) if size else ""]
            meta = "  ·  ".join(x for x in parts if x)
        p.drawText(g["meta"], Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(small).elidedText(meta, Qt.ElideRight, int(g["meta"].width())))

        if job.status == Status.FAILED and job.hint:
            hint_r = QRectF(g["bar"].x(), g["bar"].y() - 7, g["bar"].width(), 20)
            p.setFont(small)
            p.setPen(QColor(t["warn"]))
            p.drawText(hint_r, Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(small).elidedText("Tip: " + job.hint, Qt.ElideRight, int(hint_r.width())))
        else:
            self._paint_bar(p, g["bar"], job, t)

        if hovered:
            for name, r in g["buttons"].items():
                over = r.contains(self._mouse)
                if over:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(t["surface3"]))
                    p.drawRoundedRect(r, 8, 8)
                col = t["err"] if over and name in ("stop", "x", "trash") else (t["text"] if over else t["muted"])
                icons.paint(p, name, col, r, 17)
        else:
            self._paint_status(p, g, job, t, title_f, small)
        p.restore()

    def _paint_thumb(self, p, r: QRectF, job: Job, t):
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.save()
        p.setClipPath(path)
        p.fillRect(r, QColor(t["surface3"]))
        pm = self.thumbs.get(job.thumbnail)
        if pm is not None:
            paint_cover(p, pm, r)
        else:
            icons.paint(p, "music" if job.settings.mode == "audio" else "video", t["faint"], r, 24)
        dur = fmt_duration(job.duration)
        if dur:
            draw_badge(p, r, dur)
        p.restore()

    def _paint_bar(self, p, r: QRectF, job: Job, t):
        st = job.status
        if st == Status.QUEUED:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["surface3"]))
        p.drawRoundedRect(r, 3, 3)
        if st == Status.STARTING or (st == Status.DOWNLOADING and job.progress <= 0):
            # indeterminate: a sliding highlight
            phase = (time.monotonic() * 0.8) % 1.0
            w = r.width() * 0.28
            x = r.x() + (r.width() + w) * phase - w
            seg = QRectF(max(r.x(), x), r.y(), min(w, r.right() - max(r.x(), x)), r.height())
            if seg.width() > 0:
                p.setBrush(QColor(t["accent"]))
                p.drawRoundedRect(seg, 3, 3)
            return
        frac = 1.0 if st == Status.DONE else max(0.0, min(1.0, job.progress))
        if frac <= 0:
            return
        fill = QRectF(r.x(), r.y(), max(r.height(), r.width() * frac), r.height())
        if st == Status.DONE:
            p.setBrush(QColor(t["ok"]))
        elif st == Status.FAILED:
            p.setBrush(QColor(t["err"]))
        elif st in (Status.CANCELLED, Status.SKIPPED):
            p.setBrush(QColor(t["faint"]))
        else:
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0, QColor(t["accent"]))
            grad.setColorAt(1, QColor(t["accent2"]))
            p.setBrush(grad)
        p.drawRoundedRect(fill, 3, 3)

    def _paint_status(self, p, g, job: Job, t, title_f, small):
        st = job.status
        colors = {Status.DONE: t["ok"], Status.FAILED: t["err"], Status.CANCELLED: t["faint"],
                  Status.SKIPPED: t["muted"], Status.QUEUED: t["muted"], Status.PROCESSING: t["info"]}
        if st == Status.DOWNLOADING:
            text, col = f"{job.progress * 100:.0f}%", t["text"]
        elif st == Status.STARTING:
            text, col = "Starting", t["muted"]
        else:
            text, col = st.value, colors.get(st, t["text"])
        f = QFont(title_f)
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor(col))
        p.drawText(g["status"], Qt.AlignRight | Qt.AlignVCenter, text)

        sub = ""
        if st == Status.DOWNLOADING:
            bits = []
            if job.speed:
                bits.append(f"{human_bytes(job.speed)}/s")
            if job.eta is not None:
                bits.append(f"{human_eta(job.eta)} left")
            if job.detail:
                bits.append(job.detail)
            sub = "  ·  ".join(bits)
        elif st in (Status.PROCESSING, Status.STARTING, Status.SKIPPED, Status.CANCELLED) or (
                st == Status.DONE and job.detail):
            sub = job.detail
        if sub and sub != text:
            p.setFont(small)
            p.setPen(QColor(t["muted"]))
            p.drawText(g["sub"], Qt.AlignRight | Qt.AlignVCenter,
                       QFontMetrics(small).elidedText(sub, Qt.ElideLeft, int(g["sub"].width())))

    # ---- interaction ---------------------------------------------------------

    def editorEvent(self, event, model, option, index):
        job = index.data(JobRole)
        if job is None:
            return False
        if event.type() == QEvent.MouseMove:
            self._mouse = event.position()
            return False
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            for name, r in self._geo(option.rect, job)["buttons"].items():
                if r.contains(event.position()):
                    self.action.emit(job, name)
                    return True
        return False

    def helpEvent(self, event, view, option, index):
        job = index.data(JobRole)
        if job is None:
            return False
        g = self._geo(option.rect, job)
        pos = QPointF(event.pos())
        for name, r in g["buttons"].items():
            if r.contains(pos):
                QToolTip.showText(event.globalPos(), ACTION_LABELS.get(name, name), view)
                return True
        lines = [f"<b>{_esc(job.display_title)}</b>"]
        if job.error:
            lines.append(f"<span style='color:{theme.current()['err']}'>{_esc(job.error)}</span>")
        if job.hint:
            lines.append(f"<span style='color:{theme.current()['warn']}'>Tip: {_esc(job.hint)}</span>")
        if job.files:
            lines.append(_esc(job.files[-1]))
        elif not job.error:
            lines.append(_esc(job.url))
        QToolTip.showText(event.globalPos(), "<br>".join(lines), view)
        return True


def short_error(error: str) -> str:
    """First line of an error without yt-dlp's "[extractor] id:" prefix."""
    line = (error or "").splitlines()[0] if error else ""
    return re.sub(r"^\[[^\]]+\]\s*[^:\s]*:\s*", "", line) or line


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
