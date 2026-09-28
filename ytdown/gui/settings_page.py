"""Settings page: grouped cards of labelled controls bound to Settings fields."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..options import validate_extra_args
from ..settings import (AUDIO_FORMATS, AUDIO_QUALITIES, BROWSERS, FILENAME_TEMPLATES,
                        SPONSORBLOCK_CATEGORIES, SPONSORBLOCK_MODES, VIDEO_CODECS,
                        VIDEO_CONTAINERS, VIDEO_QUALITIES, Settings, config_dir)
from . import theme
from .widgets import Chip, ToggleSwitch, button, label


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("Page")
        self.win = win
        self._sync = []  # callables that push settings -> widgets

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        self.col = QVBoxLayout(body)
        self.col.setContentsMargins(28, 22, 28, 28)
        self.col.setSpacing(16)
        self.col.addWidget(label("Settings", "H1"))
        self.col.addWidget(label("Changes are saved automatically and apply to new downloads.", "Muted"))

        c = self.card("General")
        self.folder_row(c)
        self.combo_row(c, "Default mode", "What the Downloads page starts with.", "mode",
                       [("video", "Video"), ("audio", "Audio only")])
        self.edit_row(c, "File name", "yt-dlp template: %(title)s, %(uploader)s, %(id)s, "
                      "%(upload_date>%Y-%m-%d)s …", "filename_template", combo_values=FILENAME_TEMPLATES)
        self.combo_row(c, "Theme", "", "theme", [("system", "Follow system"), ("dark", "Dark"),
                                                 ("light", "Light")])
        self.switch_row(c, "Notify when downloads finish", "Desktop notification while the window "
                        "is in the background.", "notify_done")
        self.switch_row(c, "Keep running in the tray when closed", "Downloads continue in the "
                        "background; quit from the tray icon.", "close_to_tray")
        self.switch_row(c, "Watch the clipboard", "Copied links are added to the queue automatically.",
                        "watch_clipboard")

        c = self.card("Video")
        self.combo_row(c, "Quality", "Highest resolution to download.", "video_quality", VIDEO_QUALITIES)
        self.combo_row(c, "Container", "MP4 is the most compatible.", "video_container", VIDEO_CONTAINERS)
        self.combo_row(c, "Codecs", "Compatible plays on every TV, phone and editor. YouTube only "
                       "offers VP9/AV1 above 1080p.", "video_codec", VIDEO_CODECS)

        c = self.card("Audio")
        self.combo_row(c, "Format", "", "audio_format", AUDIO_FORMATS)
        self.combo_row(c, "Quality", "For MP3, M4A and OPUS.", "audio_quality", AUDIO_QUALITIES)

        c = self.card("Playlists & channels")
        self.switch_row(c, "Download the whole playlist from a video link",
                        "Applies when a video link also contains a playlist.", "download_playlist")
        self.switch_row(c, "Save into a subfolder named after the playlist", "", "playlist_subfolder")
        self.switch_row(c, "Number the files (01 - Title)", "", "playlist_numbering")
        self.switch_row(c, "Skip videos downloaded before", "Remembers finished downloads so "
                        "re-syncing a playlist or channel only fetches new videos.", "use_archive",
                        extra=self._forget_button())

        c = self.card("Subtitles & metadata")
        self.switch_row(c, "Embed thumbnail as cover art", "", "embed_thumbnail")
        self.switch_row(c, "Embed metadata", "Title, artist, date and description.", "embed_metadata")
        self.switch_row(c, "Embed chapters", "", "embed_chapters")
        self.switch_row(c, "Download subtitles", "", "subtitles")
        self.edit_row(c, "Subtitle languages", "Comma separated, regex allowed, e.g. en.*,ar,fr or all.",
                      "subtitle_langs", width=220)
        self.switch_row(c, "Include auto-generated subtitles", "", "auto_subtitles")
        self.switch_row(c, "Embed subtitles into the video", "Otherwise saved as .srt files.",
                        "embed_subtitles")

        c = self.card("SponsorBlock  ·  YouTube")
        self.combo_row(c, "Sponsored segments", "Community-submitted segment data.", "sponsorblock",
                       SPONSORBLOCK_MODES)
        self.sponsor_chips(c)

        c = self.card("Network & performance")
        self.spin_row(c, "Simultaneous downloads", "Playlists are split into items that also run in "
                      "parallel.", "max_concurrent", 1, 10)
        self.spin_row(c, "Connections per download", "Parallel fragments for streamed formats.",
                      "fragments", 1, 32)
        self.edit_row(c, "Speed limit", "Per download, e.g. 2M or 500K. Empty = unlimited.",
                      "rate_limit", width=140, placeholder="Unlimited")
        self.spin_row(c, "Retries", "", "retries", 0, 100)
        self.edit_row(c, "Proxy", "e.g. socks5://127.0.0.1:1080 or http://user:pass@host:port",
                      "proxy", width=280, placeholder="None")
        self.combo_row(c, "Cookies from browser", "Lets the app act as your signed-in browser for "
                       "age-restricted or members-only videos. Firefox is the most reliable; "
                       "Chrome/Edge must be closed.", "cookies_browser", BROWSERS)
        self.file_row(c, "…or a cookies.txt file", "Netscape format, exported with a browser "
                      "extension. Takes priority when set.", "cookies_file")
        self.aria = self.switch_row(c, "Use aria2c for direct files", "Multi-connection downloader "
                                    "(install aria2 first).", "use_aria2c")
        self.switch_row(c, "Use the system certificate store", "Fixes \"certificate verify failed\" "
                        "behind antivirus HTTPS scanning or company proxies.", "system_certs")

        c = self.card("Advanced")
        self.extra = self.edit_row(c, "Extra yt-dlp arguments", "Any yt-dlp option, e.g. "
                                   "--match-filter \"duration < 600\"", "extra_args", width=360)
        self.extra_msg = label("", "Faint", wrap=True)
        c.addWidget(self.extra_msg, c.rowCount(), 0, 1, 2)
        reset = button("Restore defaults", "retry")
        reset.clicked.connect(self.reset)
        c.addWidget(reset, c.rowCount(), 0, 1, 1, Qt.AlignLeft)
        self.col.addStretch(1)

    # ---- building helpers --------------------------------------------------

    def card(self, title):
        frame = QFrame()
        frame.setObjectName("Card")
        grid = QGridLayout(frame)
        grid.setContentsMargins(20, 16, 20, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.addWidget(label(title, "H2"), 0, 0, 1, 2)
        self.col.addWidget(frame)
        return grid

    def _text(self, title, desc):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(label(title))
        if desc:
            v.addWidget(label(desc, "Faint", wrap=True))
        return w

    def _row(self, grid, title, desc, control):
        r = grid.rowCount()
        grid.addWidget(self._text(title, desc), r, 0)
        grid.addWidget(control, r, 1, Qt.AlignRight | Qt.AlignVCenter)
        return control

    def switch_row(self, grid, title, desc, name, extra=None):
        sw = ToggleSwitch(getattr(self.win.settings, name))
        sw.toggled.connect(lambda on: self.win.set_setting(name, on))
        self._sync.append(lambda: _quiet(sw, sw.setChecked, getattr(self.win.settings, name)))
        if extra:
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(12)
            h.addWidget(extra)
            h.addWidget(sw)
            self._row(grid, title, desc, box)
        else:
            self._row(grid, title, desc, sw)
        return sw

    def combo_row(self, grid, title, desc, name, choices):
        cb = QComboBox()
        cb.setMinimumWidth(220)
        for v, lbl in choices:
            cb.addItem(lbl, v)
        cb.activated.connect(lambda i: self.win.set_setting(name, cb.itemData(i)))
        self._sync.append(lambda: _quiet(cb, cb.setCurrentIndex,
                                         max(0, cb.findData(getattr(self.win.settings, name)))))
        return self._row(grid, title, desc, cb)

    def spin_row(self, grid, title, desc, name, lo, hi):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setMinimumWidth(90)
        sp.setAlignment(Qt.AlignCenter)
        sp.valueChanged.connect(lambda v: self.win.set_setting(name, v))
        self._sync.append(lambda: _quiet(sp, sp.setValue, getattr(self.win.settings, name)))
        return self._row(grid, title, desc, sp)

    def edit_row(self, grid, title, desc, name, width=300, placeholder="", combo_values=None):
        if combo_values:
            w = QComboBox()
            w.setEditable(True)
            w.addItems(combo_values)
            w.setMinimumWidth(width)
            edit = w.lineEdit()
            w.currentTextChanged.connect(lambda s: self.win.set_setting(name, s))
            self._sync.append(lambda: _quiet(w, w.setEditText, getattr(self.win.settings, name)))
        else:
            w = edit = QLineEdit()
            w.setMinimumWidth(width)
            w.textEdited.connect(lambda s: self.win.set_setting(name, s))
            self._sync.append(lambda: w.text() != getattr(self.win.settings, name)
                              and _quiet(w, w.setText, getattr(self.win.settings, name)))
        if placeholder:
            edit.setPlaceholderText(placeholder)
        return self._row(grid, title, desc, w)

    def folder_row(self, grid):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        edit = QLineEdit()
        edit.setMinimumWidth(300)
        edit.editingFinished.connect(lambda: self.win.set_setting("output_dir", edit.text().strip()))
        pick = button("Browse", "folder")
        pick.clicked.connect(lambda: self._pick_folder(edit))
        h.addWidget(edit)
        h.addWidget(pick)
        self._sync.append(lambda: _quiet(edit, edit.setText, self.win.settings.output_dir))
        self._row(grid, "Download folder", "", box)

    def _pick_folder(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Download folder", self.win.settings.output_dir)
        if d:
            self.win.set_setting("output_dir", os.path.normpath(d))
            self.sync()

    def file_row(self, grid, title, desc, name):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        edit = QLineEdit()
        edit.setMinimumWidth(240)
        edit.setPlaceholderText("None")
        edit.editingFinished.connect(lambda: self.win.set_setting(name, edit.text().strip()))
        pick = button("Browse", "folder")

        def choose():
            f, _ = QFileDialog.getOpenFileName(self, "cookies.txt", "", "Cookies (*.txt);;All files (*)")
            if f:
                self.win.set_setting(name, os.path.normpath(f))
                self.sync()
        pick.clicked.connect(choose)
        h.addWidget(edit)
        h.addWidget(pick)
        self._sync.append(lambda: _quiet(edit, edit.setText, getattr(self.win.settings, name)))
        self._row(grid, title, desc, box)

    def sponsor_chips(self, grid):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        chips = {}
        for value, text in SPONSORBLOCK_CATEGORIES:
            chip = Chip(text)
            chips[value] = chip
            h.addWidget(chip)
            chip.toggled.connect(lambda _=False: self.win.set_setting(
                "sponsorblock_categories", ",".join(k for k, c in chips.items() if c.isChecked())))
        h.addStretch(1)

        def sync():
            cur = set(self.win.settings.sponsorblock_categories.split(","))
            for k, c in chips.items():
                _quiet(c, c.setChecked, k in cur)
        self._sync.append(sync)
        r = grid.rowCount()
        grid.addWidget(label("Categories", "Muted"), r, 0, 1, 2)
        grid.addWidget(box, r + 1, 0, 1, 2)

    def _forget_button(self):
        b = button("Forget history", flat=True)
        b.clicked.connect(self.forget_history)
        return b

    # ---- actions -------------------------------------------------------------

    def sync(self):
        for fn in self._sync:
            fn()
        self.aria.setEnabled(bool(self.win.env.aria2c))
        self.update_extra_msg()

    def update_extra_msg(self):
        err = validate_extra_args(self.win.settings.extra_args)
        t = theme.current()
        if not self.win.settings.extra_args.strip():
            self.extra_msg.setText("")
        else:
            self.extra_msg.setText(err or "Arguments look valid.")
            self.extra_msg.setStyleSheet(f"color: {t['err'] if err else t['ok']}")

    def forget_history(self):
        path = config_dir() / "archive.txt"
        if not path.exists():
            self.win.toast("Download history is already empty")
            return
        n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        if QMessageBox.question(self, "Forget history", f"Forget {n} remembered download(s)? "
                                "They will be downloaded again if you add them.") == QMessageBox.Yes:
            path.unlink(missing_ok=True)
            self.win.toast("History cleared")

    def reset(self):
        if QMessageBox.question(self, "Restore defaults", "Restore all settings to their defaults? "
                                "Your download folder is kept.") != QMessageBox.Yes:
            return
        fresh = Settings(output_dir=self.win.settings.output_dir,
                         window_geometry=self.win.settings.window_geometry)
        self.win.replace_settings(fresh)
        self.win.toast("Defaults restored")

    def showEvent(self, e):
        self.sync()
        super().showEvent(e)


def _quiet(widget, fn, value):
    widget.blockSignals(True)
    try:
        fn(value)
    finally:
        widget.blockSignals(False)
    return True
