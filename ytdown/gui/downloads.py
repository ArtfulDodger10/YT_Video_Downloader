"""The Downloads page: link input, live preview, options and the download list."""

from __future__ import annotations

import os
import threading
from dataclasses import replace

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QMenu, QMessageBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..engine import Job, Status
from ..options import extract_targets, looks_like_url
from ..probe import ProbeResult, probe
from ..settings import AUDIO_FORMATS, AUDIO_QUALITIES, VIDEO_CONTAINERS, VIDEO_QUALITIES
from ..util import open_path, reveal_in_folder
from . import icons, theme
from .delegate import JobDelegate, fmt_duration, site_name
from .model import FILTERS, FilterModel, JobModel, JobRole
from .widgets import (Chip, InfoBar, Segmented, Spinner, Thumb, ToggleSwitch, button, divider,
                      icon_button, label, refresh_icon)

STD_HEIGHTS = [int(v) for v, _ in VIDEO_QUALITIES if v.isdigit()]


class InputEdit(QLineEdit):
    """Line edit that hands multi-link pastes to the queue instead of squashing them."""
    multi_paste = Signal(str)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            text = QGuiApplication.clipboard().text()
            if len(extract_targets(text)) > 1:
                self.multi_paste.emit(text)
                return
        super().keyPressEvent(e)


class DownloadsPage(QWidget):
    _probe_done = Signal(int, object)

    def __init__(self, win):
        super().__init__()
        self.setObjectName("Page")
        self.win = win
        self._probe_gen = 0
        self._probe: ProbeResult | None = None
        self._probe_timer = QTimer(self, singleShot=True, interval=450, timeout=self._maybe_probe)
        self._probe_done.connect(self._on_probe_done, Qt.QueuedConnection)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 14)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Downloads", "H1"))
        titles.addWidget(label("Paste a link from YouTube or 1,800+ other sites, or type to search.", "Muted"))
        head.addLayout(titles)
        head.addStretch(1)
        self.speed_label = label("", "Muted")
        head.addWidget(self.speed_label, 0, Qt.AlignBottom)
        root.addLayout(head)

        root.addWidget(self._build_input())
        root.addWidget(self._build_preview())

        self.restore_bar = InfoBar("info")
        self.env_bar = InfoBar("warn")
        root.addWidget(self.restore_bar)
        root.addWidget(self.env_bar)

        root.addLayout(self._build_list_header())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list())
        self.stack.addWidget(self._build_empty())
        root.addWidget(self.stack, 1)
        self.sync_from_settings()
        self.update_counts()
        self._update_empty()

    # ================================================================ building

    def _build_input(self):
        card = QFrame()
        card.setObjectName("InputCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 10, 12, 12)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.link_icon = QLabel()
        row.addWidget(self.link_icon)
        self.input = InputEdit()
        self.input.setObjectName("BigInput")
        self.input.setPlaceholderText("Paste a link or search YouTube…")
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self.add_from_input)
        self.input.textChanged.connect(self._on_text_changed)
        self.input.multi_paste.connect(lambda text: self.win.add_text(text, source="clipboard"))
        row.addWidget(self.input, 1)
        self.paste_btn = button("Paste", "paste", tooltip="Paste from clipboard (several links are queued at once)")
        self.paste_btn.clicked.connect(self.paste)
        row.addWidget(self.paste_btn)
        self.dl_btn = button("Download", "download", primary=True)
        self.dl_btn.setMinimumWidth(128)
        self.dl_btn.clicked.connect(self.add_from_input)
        row.addWidget(self.dl_btn)
        v.addLayout(row)
        v.addWidget(divider())

        opts = QHBoxLayout()
        opts.setSpacing(10)
        self.mode = Segmented([("video", "Video", "video"), ("audio", "Audio", "music")])
        self.mode.changed.connect(lambda m: self.win.set_setting("mode", m))
        opts.addWidget(self.mode)
        opts.addSpacing(6)
        opts.addWidget(label("Quality", "Muted"))
        self.quality = QComboBox()
        self.quality.setMinimumWidth(130)
        self.quality.activated.connect(self._quality_picked)
        opts.addWidget(self.quality)
        opts.addWidget(label("Format", "Muted"))
        self.fmt = QComboBox()
        self.fmt.setMinimumWidth(150)
        self.fmt.activated.connect(self._format_picked)
        opts.addWidget(self.fmt)
        opts.addSpacing(6)
        self.folder_btn = button("", "folder", tooltip="Download folder")
        self.folder_btn.setMaximumWidth(260)
        self.folder_btn.clicked.connect(self.choose_folder)
        opts.addWidget(self.folder_btn)
        opts.addStretch(1)
        opts.addWidget(label("Whole playlist", "Muted"))
        self.playlist_switch = ToggleSwitch()
        self.playlist_switch.setToolTip("When a video link is part of a playlist, download the whole playlist")
        self.playlist_switch.toggled.connect(self._playlist_toggled)
        opts.addWidget(self.playlist_switch)
        v.addLayout(opts)
        return card

    def _build_preview(self):
        self.preview = QFrame()
        self.preview.setObjectName("Card")
        h = QHBoxLayout(self.preview)
        h.setContentsMargins(14, 14, 10, 14)
        h.setSpacing(16)
        self.pv_thumb = Thumb(208, 117)
        h.addWidget(self.pv_thumb, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(6)
        top = QHBoxLayout()
        self.pv_spinner = Spinner(16)
        top.addWidget(self.pv_spinner)
        self.pv_title = label("", "H2", wrap=True)
        self.pv_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(self.pv_title, 1)
        col.addLayout(top)
        self.pv_meta = label("", "Muted")
        col.addWidget(self.pv_meta)
        self.pv_error = label("", "Error", wrap=True)
        self.pv_hint = label("", "Hint", wrap=True)
        col.addWidget(self.pv_error)
        col.addWidget(self.pv_hint)

        self.pv_chips_row = QWidget()
        self.pv_chips = QHBoxLayout(self.pv_chips_row)
        self.pv_chips.setContentsMargins(0, 4, 0, 0)
        self.pv_chips.setSpacing(6)
        self.pv_chip_group = QButtonGroup(self)
        self.pv_chip_group.setExclusive(True)
        col.addWidget(self.pv_chips_row)

        self.pv_playlist_row = QWidget()
        pr = QHBoxLayout(self.pv_playlist_row)
        pr.setContentsMargins(0, 4, 0, 0)
        pr.setSpacing(8)
        pr.addWidget(label("Items", "Muted"))
        self.pv_items = QLineEdit()
        self.pv_items.setPlaceholderText("All  ·  e.g. 1-10, 15")
        self.pv_items.setFixedWidth(210)
        self.pv_items.textEdited.connect(lambda s: self.win.set_setting("playlist_items", s, sync=False))
        pr.addWidget(self.pv_items)
        self.pv_pl_note = label("", "Faint")
        pr.addWidget(self.pv_pl_note)
        pr.addStretch(1)
        col.addWidget(self.pv_playlist_row)
        col.addStretch(1)
        h.addLayout(col, 1)

        close = icon_button("x", "Hide preview", 16)
        close.clicked.connect(self.preview.hide)
        h.addWidget(close, 0, Qt.AlignTop)
        self.preview.hide()
        return self.preview

    def _build_list_header(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.filter = Segmented([("all", "All"), ("active", "Active"), ("done", "Completed"),
                                 ("failed", "Failed")])
        self.filter.changed.connect(self._filter_changed)
        row.addWidget(self.filter)
        row.addStretch(1)
        self.pause_btn = button("Pause", "pause", flat=True, tooltip="Pause the queue (running downloads finish)")
        self.pause_btn.clicked.connect(self.win.toggle_pause)
        row.addWidget(self.pause_btn)
        self.retry_all_btn = button("Retry failed", "retry", flat=True)
        self.retry_all_btn.clicked.connect(self.retry_failed)
        row.addWidget(self.retry_all_btn)
        clear = button("Clear completed", "check", flat=True)
        clear.clicked.connect(self.win.manager.clear_finished)
        row.addWidget(clear)
        folder = button("Open folder", "folder", flat=True)
        folder.clicked.connect(lambda: self.win.open_folder(self.win.settings.output_dir))
        row.addWidget(folder)
        return row

    def _build_list(self):
        self.model = JobModel(self.win.manager, self)
        self.proxy = FilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.view = QListView()
        self.view.setModel(self.proxy)
        self.delegate = JobDelegate(self.win.thumbs, self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.verticalScrollBar().setSingleStep(24)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(lambda idx: self.job_action(idx.data(JobRole), "play"))
        self.view.viewport().installEventFilter(self)
        self.view.installEventFilter(self)
        self.delegate.action.connect(self.job_action)
        for sig in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset,
                    self.proxy.layoutChanged):
            sig.connect(self._update_empty)
        return self.view

    def _build_empty(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(1)
        self.empty_icon = QLabel(alignment=Qt.AlignCenter)
        v.addWidget(self.empty_icon)
        self.empty_title = label("No downloads yet", "H2")
        self.empty_title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty_title)
        self.empty_text = label("Paste a link above, drop links onto this window,\n"
                                "or type anything to search YouTube.", "Muted")
        self.empty_text.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty_text)
        v.addStretch(2)
        return w

    # ================================================================ theme / sync

    def refresh_theme(self):
        t = theme.current()
        self.link_icon.setPixmap(icons.pixmap("link", t["faint"], 20))
        self.empty_icon.setPixmap(icons.pixmap("download", t["accent"], 56))
        self.mode.refresh_icons()
        self.view.viewport().update()

    def sync_from_settings(self):
        s = self.win.settings
        self.mode.set_value(s.mode)
        video = s.mode == "video"
        q_choices = VIDEO_QUALITIES if video else AUDIO_QUALITIES
        f_choices = VIDEO_CONTAINERS if video else AUDIO_FORMATS
        q_val = s.video_quality if video else s.audio_quality
        f_val = s.video_container if video else s.audio_format
        for combo, choices, val in ((self.quality, q_choices, q_val), (self.fmt, f_choices, f_val)):
            combo.blockSignals(True)
            combo.clear()
            for v, lbl in choices:
                combo.addItem(lbl, v)
            i = combo.findData(val)
            combo.setCurrentIndex(max(0, i))
            combo.blockSignals(False)
        self.quality.setEnabled(video or s.audio_format in ("mp3", "m4a", "opus"))
        self.playlist_switch.blockSignals(True)
        self.playlist_switch.setChecked(s.download_playlist)
        self.playlist_switch.blockSignals(False)
        if self.pv_items.text() != s.playlist_items:
            self.pv_items.setText(s.playlist_items)
        name = os.path.basename(os.path.normpath(s.output_dir)) or s.output_dir
        fm = self.folder_btn.fontMetrics()
        self.folder_btn.setText(fm.elidedText(name, Qt.ElideMiddle, 200))
        self.folder_btn.setToolTip(f"Download folder:\n{s.output_dir}")
        self._sync_chips()

    def _quality_picked(self, i):
        key = "video_quality" if self.win.settings.mode == "video" else "audio_quality"
        self.win.set_setting(key, self.quality.itemData(i))

    def _format_picked(self, i):
        key = "video_container" if self.win.settings.mode == "video" else "audio_format"
        self.win.set_setting(key, self.fmt.itemData(i))

    def _playlist_toggled(self, on):
        self.win.set_setting("download_playlist", on)
        self._probe = None
        self._maybe_probe()

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Download folder", self.win.settings.output_dir)
        if d:
            self.win.set_setting("output_dir", os.path.normpath(d))

    # ================================================================ input + preview

    def paste(self):
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            self.win.toast("Clipboard is empty")
            return
        if len(extract_targets(text)) > 1:
            self.win.add_text(text, source="clipboard")
            return
        self.input.setText(text)
        self.input.setFocus()
        self._probe_timer.stop()
        self._maybe_probe()

    def _on_text_changed(self, _):
        self._probe_timer.start()
        if not self.input.text().strip():
            self.preview.hide()
            self._probe_gen += 1

    def _maybe_probe(self):
        text = self.input.text().strip()
        if not looks_like_url(text):
            if not text:
                self.preview.hide()
            return
        if self._probe and self._probe.url == text and self.preview.isVisible():
            return
        self._probe_gen += 1
        gen = self._probe_gen
        self._probe = None
        self._show_loading(text)
        settings, env = replace(self.win.settings), self.win.env
        threading.Thread(target=lambda: self._probe_done.emit(gen, probe(text, settings, env)),
                         daemon=True, name="probe").start()

    def _show_loading(self, url):
        self.preview.show()
        self.pv_spinner.show()
        self.pv_title.setText("Fetching info…")
        self.pv_meta.setText(url)
        for w in (self.pv_error, self.pv_hint, self.pv_chips_row, self.pv_playlist_row):
            w.hide()
        self.pv_thumb.set_pixmap(None)
        self.pv_thumb.set_badge("")
        self.pv_thumb.set_icon("video")

    def _on_probe_done(self, gen, r: ProbeResult):
        if gen != self._probe_gen or self.input.text().strip() != r.url:
            return
        self._probe = r
        self.pv_spinner.hide()
        if r.kind == "error":
            self.pv_title.setText("Couldn't read this link")
            self.pv_meta.setText(r.url)
            self.pv_error.setText(r.error.splitlines()[0][:300] if r.error else "")
            self.pv_error.setVisible(bool(r.error))
            self.pv_hint.setText(r.hint)
            self.pv_hint.setVisible(bool(r.hint))
            return
        self.pv_title.setText(r.title)
        bits = [r.uploader]
        if site_name(r.site).lower() != r.uploader.lower():
            bits.append(site_name(r.site))
        if r.kind == "playlist":
            n = f"{r.count}+" if r.count_capped else str(r.count or 0)
            bits.append(f"Playlist · {n} items")
        else:
            bits.append(fmt_duration(r.duration))
        self.pv_meta.setText("  ·  ".join(b for b in bits if b))
        self.pv_thumb.set_icon("playlist" if r.kind == "playlist" else "video")
        self.pv_thumb.set_badge(fmt_duration(r.duration) if r.kind == "video" else "")
        pm = self.win.thumbs.get(r.thumbnail)
        self.pv_thumb.set_pixmap(pm)
        self._pv_thumb_url = r.thumbnail
        if r.kind == "playlist":
            self.pv_playlist_row.show()
            self.pv_chips_row.hide()
            self.pv_pl_note.setText("Each item downloads separately into its own folder."
                                    if self.win.settings.playlist_subfolder else "")
        else:
            self.pv_playlist_row.hide()
            self._build_chips(r)

    def thumbnail_loaded(self, url):
        if getattr(self, "_pv_thumb_url", None) == url and self.preview.isVisible():
            self.pv_thumb.set_pixmap(self.win.thumbs.get(url))

    def _build_chips(self, r: ProbeResult):
        while self.pv_chips.count():
            w = self.pv_chips.takeAt(0).widget()
            if w:
                self.pv_chip_group.removeButton(w)
                w.setParent(None)
                w.deleteLater()
        options = []
        if r.has_video:
            top = r.heights[0] if r.heights else None
            options.append(("best", f"Best{f' · {top}p' if top else ''}"))
            for h in STD_HEIGHTS:
                if h in r.heights and h != top:
                    options.append((str(h), "4K" if h == 2160 else f"{h}p"))
        options.append(("audio", "Audio only"))
        for value, text in options:
            chip = Chip(text)
            chip.setProperty("value", value)
            chip.clicked.connect(lambda _=False, v=value: self._chip_picked(v))
            self.pv_chip_group.addButton(chip)
            self.pv_chips.addWidget(chip)
        self.pv_chips.addStretch(1)
        self.pv_chips_row.show()
        self._sync_chips()

    def _chip_picked(self, value):
        if value == "audio":
            self.win.set_setting("mode", "audio")
        else:
            self.win.set_setting("video_quality", value, sync=False)
            self.win.set_setting("mode", "video")

    def _sync_chips(self):
        s = self.win.settings
        want = "audio" if s.mode == "audio" else s.video_quality
        for b in self.pv_chip_group.buttons():
            b.setChecked(b.property("value") == want)

    def add_from_input(self):
        text = self.input.text().strip()
        targets = extract_targets(text)
        if not targets:
            self.input.setFocus()
            self.win.toast("Paste a link or type something to search")
            return
        extra = {}
        r = self._probe
        if len(targets) == 1 and r and r.url == targets[0] and r.kind != "error":
            extra = {"title": r.title if r.kind == "video" else "", "thumbnail": r.thumbnail,
                     "uploader": r.uploader, "site": r.site, "duration": r.duration}
            if r.kind == "video" and r.info:
                extra.update(prefetched=r.info, prefetched_at=r.fetched_at)
        if self.win.add_targets(targets, first_extra=extra):
            self.input.clear()
            self.preview.hide()
            self._probe = None

    # ================================================================ list

    def _filter_changed(self, mode):
        self.proxy.set_mode(mode)
        self._update_empty()

    def _update_empty(self, *_):
        empty = self.proxy.rowCount() == 0
        if empty:
            if self.proxy.mode == "all":
                self.empty_title.setText("No downloads yet")
                self.empty_text.setText("Paste a link above, drop links onto this window,\n"
                                        "or type anything to search YouTube.")
            else:
                self.empty_title.setText("Nothing here")
                self.empty_text.setText("No downloads match this filter.")
        self.stack.setCurrentIndex(1 if empty else 0)

    def update_counts(self):
        counts = {k: 0 for k in FILTERS}
        for j in list(self.win.manager.jobs):
            counts["all"] += 1
            for k, sts in FILTERS.items():
                if sts and j.status in sts:
                    counts[k] += 1
        names = {"all": "All", "active": "Active", "done": "Completed", "failed": "Failed"}
        for k, n in counts.items():
            self.filter.set_label(k, f"{names[k]}  {n}" if n else names[k])
        self.retry_all_btn.setVisible(counts["failed"] > 0)
        paused = self.win.manager.paused
        self.pause_btn.setText(" Resume" if paused else " Pause")
        self.pause_btn.setProperty("iconName", "resume" if paused else "pause")
        refresh_icon(self.pause_btn)

    def selected_jobs(self) -> list[Job]:
        return [i.data(JobRole) for i in self.view.selectionModel().selectedIndexes() if i.data(JobRole)]

    def retry_failed(self):
        for j in list(self.win.manager.jobs):
            if j.status in (Status.FAILED, Status.CANCELLED):
                self.win.manager.retry(j)

    def job_action(self, job: Job, name: str):
        if job is None:
            return
        m = self.win.manager
        if name == "play":
            f = _existing(job)
            if f:
                open_path(f)
            elif job.status == Status.FAILED:
                self.show_details(job)
        elif name == "folder":
            f = _existing(job)
            if f:
                reveal_in_folder(f)
            else:
                self.win.open_folder(os.path.join(job.settings.output_dir, job.subdir))
        elif name == "retry":
            m.retry(job)
        elif name in ("stop", "x"):
            m.cancel(job)
        elif name == "trash":
            m.remove(job)
        elif name == "top":
            m.move(job, to_top=True)
        elif name == "copy":
            QGuiApplication.clipboard().setText(job.url)
            self.win.toast("Link copied")
        elif name == "delete":
            self.delete_file(job)
        elif name == "details":
            self.show_details(job)

    def _context_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        jobs = self.selected_jobs() or [idx.data(JobRole)]
        job = idx.data(JobRole)
        t = theme.current()
        menu = QMenu(self)

        def add(text, icon, fn, enabled=True):
            a = menu.addAction(icons.icon(icon, t["muted"], 16), text, fn)
            a.setEnabled(enabled)

        single = len(jobs) == 1
        add("Open file", "play", lambda: self.job_action(job, "play"), single and bool(_existing(job)))
        add("Show in folder", "folder", lambda: self.job_action(job, "folder"), single)
        add("Details", "info", lambda: self.show_details(job), single)
        add("Copy link", "copy", lambda: self._copy_links(jobs))
        menu.addSeparator()
        add("Retry", "retry", lambda: [self.win.manager.retry(j) for j in jobs],
            any(j.status in (Status.FAILED, Status.CANCELLED, Status.SKIPPED) for j in jobs))
        add("Cancel", "stop", lambda: [self.win.manager.cancel(j) for j in jobs],
            any(not j.is_finished for j in jobs))
        add("Move to top", "up", lambda: [self.win.manager.move(j) for j in reversed(jobs)],
            any(j.status == Status.QUEUED for j in jobs))
        menu.addSeparator()
        add("Remove from list", "trash", lambda: [self.win.manager.remove(j) for j in jobs])
        add("Delete file from disk…", "trash", lambda: self.delete_file(job),
            single and bool(_existing(job)))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _copy_links(self, jobs):
        QGuiApplication.clipboard().setText("\n".join(j.url for j in jobs))
        self.win.toast("Link copied" if len(jobs) == 1 else f"{len(jobs)} links copied")

    def delete_file(self, job: Job):
        f = _existing(job)
        if not f:
            return
        if QMessageBox.question(self, "Delete file", f"Permanently delete this file?\n\n{f}") \
                != QMessageBox.Yes:
            return
        try:
            os.remove(f)
        except OSError as e:
            QMessageBox.warning(self, "Delete file", str(e))
            return
        self.win.manager.remove(job, delete_partial=False)
        self.win.toast("File deleted")

    def show_details(self, job: Job):
        lines = [f"<b>{job.display_title}</b>", f"<span>{job.url}</span>",
                 f"Status: {job.status.value}{(' · ' + job.detail) if job.detail else ''}"]
        if job.files:
            lines.append(f"Saved to: {job.files[-1]}")
        if job.error:
            lines.append(f"<br><b>Error</b><br>{job.error}")
        if job.hint:
            lines.append(f"<br><b>Tip</b><br>{job.hint}")
        box = QMessageBox(self)
        box.setWindowTitle("Download details")
        box.setTextFormat(Qt.RichText)
        box.setText("<br>".join(x.replace("\n", "<br>") for x in lines))
        if job.log:
            box.setDetailedText("\n".join(list(job.log)[-200:]))
        box.exec()

    def eventFilter(self, obj, e):
        if obj is self.view.viewport() and e.type() == QEvent.Leave:
            self.view.viewport().update()
        if obj is self.view and e.type() == QEvent.KeyPress:
            if e.key() == Qt.Key_Delete:
                for j in self.selected_jobs():
                    self.win.manager.remove(j)
                return True
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                sel = self.selected_jobs()
                if len(sel) == 1:
                    self.job_action(sel[0], "play")
                return True
        return super().eventFilter(obj, e)


def _existing(job: Job):
    for f in reversed(job.files):
        if os.path.exists(f):
            return f
    return None

