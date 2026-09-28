"""Activity page: the combined yt-dlp log of all downloads."""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtGui import QColor, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from . import theme
from .widgets import Segmented, button, label


class ActivityPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("Page")
        self.win = win
        self.lines: deque = deque(maxlen=8000)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 22, 28, 18)
        v.setSpacing(14)
        v.addWidget(label("Activity", "H1"))
        v.addWidget(label("Everything yt-dlp reports, useful when something goes wrong.", "Muted"))
        bar = QHBoxLayout()
        self.filter = Segmented([("all", "Everything"), ("problems", "Warnings && errors")])
        self.filter.changed.connect(lambda _: self.rerender())
        bar.addWidget(self.filter)
        bar.addStretch(1)
        copy = button("Copy", "copy", flat=True)
        copy.clicked.connect(self.copy)
        clear = button("Clear", "trash", flat=True)
        clear.clicked.connect(self.clear)
        bar.addWidget(copy)
        bar.addWidget(clear)
        v.addLayout(bar)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setMaximumBlockCount(8000)
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        v.addWidget(self.text, 1)

    def _fmt(self, level):
        f = QTextCharFormat()
        key = {"error": "err", "warning": "warn"}.get(level, "text")
        f.setForeground(QColor(theme.current()[key]))
        return f

    def append_many(self, items):
        only_problems = self.filter.value() == "problems"
        sb = self.text.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 4
        cur = QTextCursor(self.text.document())
        cur.movePosition(QTextCursor.End)
        for level, msg in items:
            line = f"{time.strftime('%H:%M:%S')}  {msg}"
            self.lines.append((level, line))
            if only_problems and level == "info":
                continue
            if not self.text.document().isEmpty():
                cur.insertBlock()
            cur.insertText(line, self._fmt(level))
        if at_end:
            sb.setValue(sb.maximum())

    def rerender(self):
        only = self.filter.value() == "problems"
        self.text.clear()
        cur = QTextCursor(self.text.document())
        first = True
        for level, line in self.lines:
            if only and level == "info":
                continue
            if not first:
                cur.insertBlock()
            cur.insertText(line, self._fmt(level))
            first = False
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def copy(self):
        QGuiApplication.clipboard().setText("\n".join(line for _, line in self.lines))
        self.win.toast("Log copied")

    def clear(self):
        self.lines.clear()
        self.text.clear()
