"""Tkinter GUI. All widget access happens on the Tk thread; worker threads only push
events into queues that `_tick` drains a few times per second (cheap even with
hundreds of jobs, and progress hooks never block on the UI)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME, __version__
from ..deps import detect
from ..engine import ACTIVE, DownloadManager, Job, Status
from ..options import _URL_RE, extract_targets, validate_extra_args
from ..settings import (AUDIO_FORMATS, AUDIO_QUALITIES, BROWSERS, FILENAME_TEMPLATES,
                        SPONSORBLOCK_CATEGORIES, SPONSORBLOCK_MODES, VIDEO_CODECS,
                        VIDEO_CONTAINERS, VIDEO_QUALITIES, Settings, config_dir)
from ..util import (ensure_std_streams, human_bytes, human_eta, open_path, progress_bar,
                    reveal_in_folder)

try:
    import sv_ttk
except ImportError:  # the app still works with the stock ttk theme
    sv_ttk = None

PROJECT_URL = "https://github.com/ArtfulDodger10/YT_Video_Downloader"
PLACEHOLDER = "Paste one or more links (one per line), or type something to search YouTube…"

PALETTE = {
    "dark": {"text_bg": "#2b2b2b", "text_fg": "#f3f3f3", "muted": "#9a9a9a", "ok": "#6ccb5f",
             "err": "#ff7b72", "warn": "#e3b341", "active": "#60a5fa"},
    "light": {"text_bg": "#ffffff", "text_fg": "#1b1b1b", "muted": "#6e6e6e", "ok": "#0f7b0f",
              "err": "#c42b1c", "warn": "#9a6700", "active": "#0067c0"},
}


def _short_quality(job: Job) -> str:
    s = job.settings
    if s.mode == "audio":
        return s.audio_format.upper() if s.audio_format != "original" else "Audio"
    q = "Best" if s.video_quality == "best" else f"{s.video_quality}p"
    c = s.video_container.upper() if s.video_container != "original" else ""
    return f"{q} {c}".strip()


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame (for the settings page)."""

    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(4, 4, 16, 4))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def set_bg(self, color):
        self.canvas.configure(background=color)


class App(tk.Tk):
    TICK_MS = 150

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.env = detect()
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._logs: queue.SimpleQueue = queue.SimpleQueue()
        self._log_lines: deque = deque(maxlen=5000)
        self._vars: dict = {}
        self._combo_vars: dict = {}
        self._save_after = None
        self._queue_dirty = False
        self._last_queue_save = 0.0
        self._last_clip = None
        self._clip_after = None
        self._placeholder_on = False

        self.manager = DownloadManager(
            self.env, on_event=lambda k, j: self._events.put((k, j)),
            on_log=lambda lvl, msg: self._logs.put((lvl, msg)),
            archive_path=str(config_dir() / "archive.txt"),
            max_concurrent=self.settings.max_concurrent)

        self.title(APP_NAME)
        self.minsize(860, 560)
        self.geometry(self.settings.window_geometry or "1060x700")
        self._set_icon()
        self._apply_theme(self.settings.theme, initial=True)
        self._build()
        self._apply_theme(self.settings.theme)
        self._restore_queue()
        self._update_env_labels()
        if self.settings.watch_clipboard:
            self._start_clipboard_watch()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Control-Return>", lambda e: self._add_from_input())
        self.after(self.TICK_MS, self._tick)

    # ================================================================ UI build

    def _build(self):
        self._build_statusbar()  # packed first so the expanding body can't push it off-screen
        root = ttk.Frame(self, padding=(14, 12, 14, 6))
        root.pack(fill="both", expand=True)
        self._build_input(root)
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, pady=(10, 0))
        self._build_queue_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self._build_about_tab()

    def _accent(self):
        return "Accent.TButton" if sv_ttk else "TButton"

    def _build_input(self, root):
        top = ttk.Frame(root)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)

        self.url_text = tk.Text(top, height=3, wrap="word", undo=True, relief="flat",
                                borderwidth=0, padx=10, pady=8, font=("Segoe UI", 10))
        self.url_text.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        self.url_text.bind("<FocusIn>", lambda e: self._placeholder(False))
        self.url_text.bind("<FocusOut>", lambda e: self._placeholder(True))
        self.url_text.bind("<Return>", self._on_return)
        self._placeholder(True)

        ttk.Button(top, text="Paste", width=12, command=self._paste).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Download", width=12, style=self._accent(),
                   command=self._add_from_input).grid(row=1, column=1, sticky="ew", pady=(6, 0))

        opts = ttk.Frame(root)
        opts.pack(fill="x", pady=(10, 0))
        mode = self._var("mode", tk.StringVar)
        ttk.Radiobutton(opts, text="Video", value="video", variable=mode).pack(side="left")
        ttk.Radiobutton(opts, text="Audio only", value="audio", variable=mode).pack(side="left", padx=(8, 18))

        ttk.Label(opts, text="Quality").pack(side="left")
        qslot = ttk.Frame(opts)
        qslot.pack(side="left", padx=(6, 0))
        ttk.Label(opts, text="Format").pack(side="left", padx=(14, 0))
        fslot = ttk.Frame(opts)
        fslot.pack(side="left", padx=(6, 0))
        self.cb_vq = self._combo(qslot, "video_quality", VIDEO_QUALITIES, width=14, pack=False)
        self.cb_aq = self._combo(qslot, "audio_quality", AUDIO_QUALITIES, width=14, pack=False)
        self.cb_vc = self._combo(fslot, "video_container", VIDEO_CONTAINERS, width=10, pack=False)
        self.cb_af = self._combo(fslot, "audio_format", AUDIO_FORMATS, width=20, pack=False)

        ttk.Checkbutton(opts, text="Whole playlist", variable=self._var("download_playlist", tk.BooleanVar)
                        ).pack(side="left", padx=(18, 0))
        ttk.Label(opts, text="Items").pack(side="left", padx=(12, 4))
        items = ttk.Entry(opts, width=10, textvariable=self._var("playlist_items", tk.StringVar))
        items.pack(side="left")
        self._tooltip(items, "Optional playlist item range, e.g. 1-10,15,20-\n"
                             "Applies to the next links you add.")

        folder = ttk.Frame(root)
        folder.pack(fill="x", pady=(10, 0))
        ttk.Label(folder, text="Save to").pack(side="left")
        ttk.Entry(folder, textvariable=self._var("output_dir", tk.StringVar)
                  ).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(folder, text="Browse…", command=self._browse_output).pack(side="left")
        ttk.Button(folder, text="Open", command=lambda: self._open_folder(self.settings.output_dir)
                   ).pack(side="left", padx=(6, 0))
        self._sync_mode_widgets()

    def _build_queue_tab(self):
        tab = ttk.Frame(self.nb, padding=(0, 8, 0, 0))
        self.nb.add(tab, text="  Downloads  ")

        self.env_banner = ttk.Label(tab, text="", wraplength=900, justify="left")
        self.banner = ttk.Label(tab, text="", wraplength=900, justify="left")
        bar = self._queue_bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.btn_pause = ttk.Button(bar, text="Pause queue", command=self._toggle_pause)
        self.btn_pause.pack(side="left")
        for text, cmd in (("Retry", self._retry_sel), ("Cancel", self._cancel_sel),
                          ("Remove", self._remove_sel), ("Clear finished", self.manager.clear_finished)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Show file", command=self._reveal_sel).pack(side="left", padx=(6, 0))
        self.summary = ttk.Label(bar, text="")
        self.summary.pack(side="right")

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("title", "status", "progress", "size", "speed", "eta", "fmt")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="extended")
        for col, text, width, stretch, anchor in (
                ("title", "Title", 320, True, "w"), ("status", "Status", 190, False, "w"),
                ("progress", "Progress", 175, False, "w"), ("size", "Size", 80, False, "e"),
                ("speed", "Speed", 90, False, "e"), ("eta", "ETA", 64, False, "center"),
                ("fmt", "Format", 96, False, "center")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=50, stretch=stretch, anchor=anchor)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_details())
        self.tree.bind("<Double-1>", lambda e: self._open_sel())
        self.tree.bind("<Return>", lambda e: self._open_sel())
        self.tree.bind("<Delete>", lambda e: self._remove_sel())
        self.tree.bind("<Control-a>", lambda e: self.tree.selection_set(self.tree.get_children()))
        self.tree.bind("<Button-3>", self._context_menu)

        self.details = tk.Text(tab, height=5, wrap="word", relief="flat", borderwidth=0,
                               padx=10, pady=6, font=("Segoe UI", 9), state="disabled")
        self.details.pack(fill="x", pady=(8, 0))

        self.menu = tk.Menu(self, tearoff=False)
        for label, cmd in (("Open file", self._open_sel), ("Show in folder", self._reveal_sel),
                           ("Copy link", self._copy_sel), (None, None),
                           ("Retry", self._retry_sel), ("Cancel", self._cancel_sel),
                           ("Move to top", self._top_sel), ("Remove", self._remove_sel)):
            if label is None:
                self.menu.add_separator()
            else:
                self.menu.add_command(label=label, command=cmd)

    def _build_settings_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Settings  ")
        self.settings_scroll = ScrollFrame(tab)
        self.settings_scroll.pack(fill="both", expand=True)
        page = self.settings_scroll.inner
        page.columnconfigure(0, weight=1)

        def section(title):
            f = ttk.LabelFrame(page, text=f" {title} ", padding=(12, 8))
            f.grid(sticky="ew", pady=(0, 10))
            f.columnconfigure(1, weight=1)
            return f

        def row(f, r, label, widget, note=None):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            widget.grid(row=r, column=1, sticky="w", pady=3)
            if note:
                ttk.Label(f, text=note, foreground=self._pal()["muted"], wraplength=520
                          ).grid(row=r, column=2, sticky="w", padx=(12, 0))

        def check(f, r, text, name, note=None):
            w = ttk.Checkbutton(f, text=text, variable=self._var(name, tk.BooleanVar))
            w.grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
            if note:
                ttk.Label(f, text=note, foreground=self._pal()["muted"], wraplength=520
                          ).grid(row=r, column=2, sticky="w", padx=(12, 0))
            return w

        f = section("Video")
        row(f, 0, "Codec preference", self._combo(f, "video_codec", VIDEO_CODECS, width=42, pack=False),
            "Compatible plays on every TV/phone/editor. Above 1080p YouTube only offers VP9/AV1.")

        f = section("Files")
        tmpl = ttk.Combobox(f, values=FILENAME_TEMPLATES, width=44,
                            textvariable=self._var("filename_template", tk.StringVar))
        row(f, 0, "File name", tmpl, "yt-dlp output template, e.g. %(title)s, %(uploader)s, %(id)s")
        check(f, 1, "Put playlists and channels in their own subfolder", "playlist_subfolder")
        check(f, 2, "Number playlist items (001 - Title)", "playlist_numbering")
        check(f, 3, "Set file date to the download time (not the upload date)", "no_mtime")
        check(f, 4, "Remember downloads and skip them next time", "use_archive",
              "Useful for re-syncing playlists/channels: only new videos are downloaded.")
        ttk.Button(f, text="Forget download history", command=self._clear_archive
                   ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        f = section("Subtitles & metadata")
        check(f, 0, "Embed thumbnail as cover art", "embed_thumbnail")
        check(f, 1, "Embed metadata (title, artist, date, description)", "embed_metadata")
        check(f, 2, "Embed chapters", "embed_chapters")
        check(f, 3, "Download subtitles", "subtitles")
        row(f, 4, "Languages", ttk.Entry(f, width=24, textvariable=self._var("subtitle_langs", tk.StringVar)),
            "Comma separated, regex allowed: en.*,ar,fr - or 'all'")
        check(f, 5, "Include auto-generated subtitles", "auto_subtitles")
        check(f, 6, "Embed subtitles into the video (otherwise save .srt files)", "embed_subtitles")

        f = section("SponsorBlock (YouTube)")
        row(f, 0, "Mode", self._combo(f, "sponsorblock", SPONSORBLOCK_MODES, width=30, pack=False))
        cats = ttk.Frame(f)
        cats.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._sb_vars = {}
        current = set(self.settings.sponsorblock_categories.split(","))
        for i, (value, label) in enumerate(SPONSORBLOCK_CATEGORIES):
            v = tk.BooleanVar(value=value in current)
            v.trace_add("write", lambda *_: self._sync_sponsor_cats())
            self._sb_vars[value] = v
            ttk.Checkbutton(cats, text=label, variable=v).grid(row=i // 4, column=i % 4, sticky="w",
                                                               padx=(0, 16), pady=2)

        f = section("Network & performance")
        row(f, 0, "Simultaneous downloads", ttk.Spinbox(
            f, from_=1, to=10, width=6, textvariable=self._var("max_concurrent", tk.IntVar)),
            "Playlists are split into separate items, so they download in parallel too.")
        row(f, 1, "Connections per download", ttk.Spinbox(
            f, from_=1, to=32, width=6, textvariable=self._var("fragments", tk.IntVar)),
            "Parallel fragment downloads for streamed (DASH/HLS) formats.")
        row(f, 2, "Speed limit", ttk.Entry(f, width=10, textvariable=self._var("rate_limit", tk.StringVar)),
            "Per download, e.g. 2M or 500K. Empty = unlimited.")
        row(f, 3, "Retries", ttk.Spinbox(f, from_=0, to=100, width=6,
                                         textvariable=self._var("retries", tk.IntVar)))
        row(f, 4, "Proxy", ttk.Entry(f, width=34, textvariable=self._var("proxy", tk.StringVar)),
            "e.g. socks5://127.0.0.1:1080 or http://user:pass@host:port")
        row(f, 5, "Cookies from browser", self._combo(f, "cookies_browser", BROWSERS, width=14, pack=False),
            "Needed for age-restricted, members-only or 'confirm you're not a bot' videos. "
            "Chrome/Edge must be fully closed; Firefox works best.")
        cf = ttk.Frame(f)
        ttk.Entry(cf, width=34, textvariable=self._var("cookies_file", tk.StringVar)).pack(side="left")
        ttk.Button(cf, text="Browse…", command=self._browse_cookies).pack(side="left", padx=(6, 0))
        row(f, 6, "…or cookies.txt file", cf, "Overrides the browser option when set.")
        self.aria_check = check(f, 7, "Use aria2c for direct downloads", "use_aria2c",
                                "Multi-connection downloader, helps slow direct-file hosts.")
        check(f, 8, "Use the system certificate store", "system_certs",
              "Fixes 'certificate verify failed' behind antivirus HTTPS scanning or company proxies.")

        f = section("Interface")
        row(f, 0, "Theme", self._combo(f, "theme", [("dark", "Dark"), ("light", "Light")], width=10, pack=False))
        check(f, 1, "Watch the clipboard and add copied links automatically", "watch_clipboard")

        f = section("Advanced")
        row(f, 0, "Extra yt-dlp arguments",
            ttk.Entry(f, width=50, textvariable=self._var("extra_args", tk.StringVar)))
        self.extra_msg = ttk.Label(f, text="Any yt-dlp option, e.g.  --limit-rate 3M  --match-filter "
                                           "\"duration < 600\"", foreground=self._pal()["muted"])
        self.extra_msg.grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Button(f, text="Restore default settings", command=self._reset_settings
                   ).grid(row=2, column=0, sticky="w", pady=(10, 0))

    def _build_log_tab(self):
        tab = ttk.Frame(self.nb, padding=(0, 8, 0, 0))
        self.nb.add(tab, text="  Log  ")
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        self.log_errors_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Warnings and errors only", variable=self.log_errors_only,
                        command=self._rerender_log).pack(side="left")
        ttk.Button(bar, text="Clear", command=self._clear_log).pack(side="right")
        ttk.Button(bar, text="Copy all", command=self._copy_log).pack(side="right", padx=(0, 6))
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(body, wrap="word", relief="flat", borderwidth=0, padx=10, pady=6,
                                font=("Consolas", 9), state="disabled")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _build_about_tab(self):
        tab = ttk.Frame(self.nb, padding=(4, 12))
        self.nb.add(tab, text="  About  ")
        ttk.Label(tab, text=f"{APP_NAME} {__version__}", font=("Segoe UI Semibold", 16)).pack(anchor="w")
        ttk.Label(tab, text="Video & audio downloader for YouTube and 1000+ other sites, powered by yt-dlp.",
                  foreground=self._pal()["muted"]).pack(anchor="w", pady=(2, 12))
        self.env_frame = ttk.Frame(tab)
        self.env_frame.pack(fill="x")
        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Re-check tools", command=self._recheck_env).pack(side="left")
        self.btn_update = ttk.Button(btns, text="Update yt-dlp", command=self._update_ytdlp)
        self.btn_update.pack(side="left", padx=(6, 0))
        if self.env.frozen:
            self.btn_update.state(["disabled"])
        ttk.Button(btns, text="Open settings folder", command=lambda: open_path(str(config_dir()))
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Project page", command=lambda: __import__("webbrowser").open(PROJECT_URL)
                   ).pack(side="left", padx=(6, 0))
        ttk.Label(tab, foreground=self._pal()["muted"], wraplength=820, justify="left", text=(
            "Tips:  Ctrl+Enter adds the links.  Double-click a finished item to play it.  "
            "Right-click items for more actions.  Unfinished downloads are kept when you close the "
            "app and can be resumed next time.\nOnly download content you have the right to download."
        )).pack(anchor="w", pady=(18, 0))

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(14, 2, 14, 6))
        bar.pack(fill="x", side="bottom")
        self.status_left = ttk.Label(bar, text="Ready")
        self.status_left.pack(side="left")
        self.status_right = ttk.Label(bar, text="", cursor="hand2")
        self.status_right.pack(side="right")
        self.status_right.bind("<Button-1>", lambda e: self.nb.select(3))

    # ================================================================ settings binding

    def _var(self, name, cls):
        if name in self._vars:
            return self._vars[name]
        var = cls(value=getattr(self.settings, name))
        var.trace_add("write", lambda *_: self._on_var(name))
        self._vars[name] = var
        return var

    def _combo(self, parent, name, choices, width=16, pack=True):
        """Readonly combobox showing labels for a settings field that stores values."""
        labels = [lbl for _, lbl in choices]
        to_value = {lbl: val for val, lbl in choices}
        to_label = {val: lbl for val, lbl in choices}
        var = tk.StringVar(value=to_label.get(getattr(self.settings, name), labels[0]))
        self._combo_vars[name] = (var, to_label)

        def changed(*_):
            value = to_value.get(var.get())
            if value is not None and getattr(self.settings, name) != value:
                setattr(self.settings, name, value)
                self._setting_changed(name)
        var.trace_add("write", changed)
        cb = ttk.Combobox(parent, values=labels, textvariable=var, state="readonly", width=width)
        if pack:
            cb.pack(side="left", padx=(6, 0))
        return cb

    def _on_var(self, name):
        try:
            value = self._vars[name].get()
        except (tk.TclError, ValueError):
            return  # e.g. a spinbox that is momentarily empty
        current = getattr(self.settings, name)
        if isinstance(current, int) and not isinstance(current, bool):
            value = getattr(Settings.from_dict({name: int(value)}), name)  # clamp to range
        if value == current:
            return
        setattr(self.settings, name, value)
        self._setting_changed(name)

    def _setting_changed(self, name):
        if name == "mode":
            self._sync_mode_widgets()
        elif name == "audio_format":
            self._sync_mode_widgets()
        elif name == "max_concurrent":
            self.manager.set_max_concurrent(self.settings.max_concurrent)
        elif name == "theme":
            self._apply_theme(self.settings.theme)
        elif name == "watch_clipboard":
            self._start_clipboard_watch() if self.settings.watch_clipboard else self._stop_clipboard_watch()
        elif name == "extra_args":
            err = validate_extra_args(self.settings.extra_args)
            pal = self._pal()
            self.extra_msg.configure(text=err or "OK", foreground=pal["err"] if err else pal["ok"])
        if self._save_after:
            self.after_cancel(self._save_after)
        self._save_after = self.after(500, self._save_settings)

    def _save_settings(self):
        self._save_after = None
        try:
            self.settings.save()
        except OSError as e:
            self._append_log("error", f"Could not save settings: {e}")

    def _sync_mode_widgets(self):
        video = self.settings.mode == "video"
        for w in (self.cb_vq, self.cb_aq, self.cb_vc, self.cb_af):
            w.pack_forget()
        for w in ((self.cb_vq, self.cb_vc) if video else (self.cb_aq, self.cb_af)):
            w.pack()
        lossy = self.settings.audio_format in ("mp3", "m4a", "opus")
        self.cb_aq.state(["!disabled"] if lossy else ["disabled"])

    def _sync_sponsor_cats(self):
        self.settings.sponsorblock_categories = ",".join(k for k, v in self._sb_vars.items() if v.get())
        self._setting_changed("sponsorblock_categories")

    def _reset_settings(self):
        if not messagebox.askyesno(APP_NAME, "Restore all settings to their defaults?", parent=self):
            return
        fresh = Settings(output_dir=self.settings.output_dir, window_geometry=self.geometry())
        self.settings = fresh
        for name, var in self._vars.items():
            var.set(getattr(fresh, name))
        for name, (var, to_label) in self._combo_vars.items():
            var.set(to_label.get(getattr(fresh, name), var.get()))
        current = set(fresh.sponsorblock_categories.split(","))
        for key, var in self._sb_vars.items():
            var.set(key in current)
        self._setting_changed("theme")
        self._setting_changed("max_concurrent")
        self._sync_mode_widgets()

    # ================================================================ theme

    def _pal(self):
        return PALETTE["light" if self.settings.theme == "light" else "dark"]

    def _apply_theme(self, theme, initial=False):
        if sv_ttk:
            sv_ttk.set_theme("light" if theme == "light" else "dark")
        elif initial:
            style = ttk.Style(self)
            style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        self._dark_titlebar(theme != "light")
        if initial:
            return
        pal = self._pal()
        for t in (self.url_text, self.details, self.log_text):
            t.configure(background=pal["text_bg"], foreground=pal["text_fg"],
                        insertbackground=pal["text_fg"], selectbackground=pal["active"])
        self.url_text.tag_configure("placeholder", foreground=pal["muted"])
        for tag, key in (("done", "ok"), ("failed", "err"), ("muted", "muted"), ("active", "active")):
            self.tree.tag_configure(tag, foreground=pal[key])
        for tag, key in (("error", "err"), ("warning", "warn"), ("info", "text_fg")):
            self.log_text.tag_configure(tag, foreground=pal[key])
        self.settings_scroll.set_bg(ttk.Style(self).lookup("TFrame", "background") or pal["text_bg"])
        self.details.tag_configure("err", foreground=pal["err"])
        self.details.tag_configure("hint", foreground=pal["warn"])
        self.details.tag_configure("key", foreground=pal["muted"])
        self._update_env_labels()

    def _dark_titlebar(self, dark: bool):
        """Match the Windows 10/11 title bar to the theme."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then pre-20H1)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                             ctypes.sizeof(value)) == 0:
                    break
            # nudge Windows to repaint the non-client area
            self.wm_attributes("-alpha", 0.99)
            self.wm_attributes("-alpha", 1.0)
        except Exception:
            pass

    def _set_icon(self):
        """Draw a small download-arrow icon (no image files needed)."""
        size = 32
        img = tk.PhotoImage(width=size, height=size)
        bg, fg = "#e5484d", "#ffffff"
        img.put(bg, to=(2, 2, size - 2, size - 2))
        img.put(fg, to=(13, 6, 19, 17))
        for i in range(8):
            img.put(fg, to=(8 + i, 16 + i, 24 - i, 17 + i))
        img.put(fg, to=(7, 25, 25, 27))
        self._icon = img
        self.iconphoto(True, img)

    # ================================================================ input

    def _placeholder(self, show: bool):
        content = self.url_text.get("1.0", "end-1c")
        if show and not content.strip():
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", PLACEHOLDER, "placeholder")
            self._placeholder_on = True
        elif not show and self._placeholder_on:
            self.url_text.delete("1.0", "end")
            self._placeholder_on = False

    def _input_text(self) -> str:
        return "" if self._placeholder_on else self.url_text.get("1.0", "end-1c")

    def _on_return(self, e):
        # Enter adds; Shift+Enter inserts a newline for multi-line pastes
        if e.state & 0x0001:
            return None
        self._add_from_input()
        return "break"

    def _paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        self._placeholder(False)
        current = self._input_text().rstrip()
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", (current + "\n" if current else "") + text.strip())
        self.url_text.focus_set()

    def _add_from_input(self):
        targets = extract_targets(self._input_text())
        if not targets:
            self.bell()
            self.url_text.focus_set()
            return
        if self._add_targets(targets):
            self.url_text.delete("1.0", "end")
            if self.focus_get() is not self.url_text:
                self._placeholder(True)

    def _add_targets(self, targets, source="") -> bool:
        err = validate_extra_args(self.settings.extra_args)
        if err:
            messagebox.showerror(APP_NAME, f"Extra yt-dlp arguments are invalid:\n{err}", parent=self)
            return False
        out = self.settings.output_dir.strip()
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Can't use the download folder:\n{out}\n\n{e}", parent=self)
            return False
        added = dupes = 0
        for t in targets:
            if self.manager.add(t, self.settings):
                added += 1
            else:
                dupes += 1
        if self.settings.playlist_items:
            self._vars["playlist_items"].set("")  # a range is meant for the links just added
        msg = f"Added {added} link(s)" + (f" from {source}" if source else "")
        if dupes:
            msg += f" ({dupes} already in the queue)"
        self._append_log("info", msg)
        self.status_left.configure(text=msg)
        self.nb.select(0)
        return True

    def _browse_output(self):
        d = filedialog.askdirectory(initialdir=self.settings.output_dir, title="Download folder", parent=self)
        if d:
            self._vars["output_dir"].set(os.path.normpath(d))

    def _browse_cookies(self):
        f = filedialog.askopenfilename(title="cookies.txt (Netscape format)", parent=self,
                                       filetypes=[("Cookies", "*.txt"), ("All files", "*.*")])
        if f:
            self._vars["cookies_file"].set(os.path.normpath(f))

    # ================================================================ clipboard watch

    def _start_clipboard_watch(self):
        try:
            self._last_clip = self.clipboard_get()
        except tk.TclError:
            self._last_clip = ""
        if not self._clip_after:
            self._clip_after = self.after(1000, self._poll_clipboard)

    def _stop_clipboard_watch(self):
        if self._clip_after:
            self.after_cancel(self._clip_after)
            self._clip_after = None

    def _poll_clipboard(self):
        self._clip_after = self.after(1000, self._poll_clipboard)
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        if text == self._last_clip or len(text) > 20000:
            return
        self._last_clip = text
        urls = list(dict.fromkeys(_URL_RE.findall(text)))
        if urls:
            self._add_targets(urls, source="clipboard")

    # ================================================================ queue actions

    def _selected_jobs(self) -> list[Job]:
        ids = set(self.tree.selection())
        return [j for j in list(self.manager.jobs) if str(j.id) in ids]

    def _toggle_pause(self):
        if self.manager.paused:
            self.manager.resume()
            self.banner.pack_forget()
        else:
            self.manager.pause()
        self._update_pause_button()

    def _update_pause_button(self):
        self.btn_pause.configure(text="Resume queue" if self.manager.paused else "Pause queue",
                                 style=self._accent() if self.manager.paused else "TButton")

    def _retry_sel(self):
        for j in self._selected_jobs():
            self.manager.retry(j)

    def _cancel_sel(self):
        for j in self._selected_jobs():
            self.manager.cancel(j)

    def _remove_sel(self):
        for j in self._selected_jobs():
            self.manager.remove(j)

    def _top_sel(self):
        for j in reversed(self._selected_jobs()):
            self.manager.move(j, to_top=True)
        self._reorder_tree()

    def _copy_sel(self):
        jobs = self._selected_jobs()
        if jobs:
            self.clipboard_clear()
            self.clipboard_append("\n".join(j.url for j in jobs))

    def _existing_file(self, job: Job):
        for f in reversed(job.files):
            if os.path.exists(f):
                return f
        return None

    def _open_sel(self):
        jobs = self._selected_jobs()
        if len(jobs) == 1:
            f = self._existing_file(jobs[0])
            if f:
                open_path(f)

    def _reveal_sel(self):
        jobs = self._selected_jobs()
        f = self._existing_file(jobs[0]) if len(jobs) == 1 else None
        if f:
            reveal_in_folder(f)
        elif jobs:
            s = jobs[0].settings
            self._open_folder(os.path.join(s.output_dir, jobs[0].subdir))
        else:
            self._open_folder(self.settings.output_dir)

    def _open_folder(self, path):
        path = path if os.path.isdir(path) else self.settings.output_dir
        try:
            os.makedirs(path, exist_ok=True)
            open_path(path)
        except OSError as e:
            messagebox.showerror(APP_NAME, str(e), parent=self)

    def _context_menu(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self.menu.tk_popup(e.x_root, e.y_root)

    def _clear_archive(self):
        path = config_dir() / "archive.txt"
        if not path.exists():
            messagebox.showinfo(APP_NAME, "The download history is already empty.", parent=self)
            return
        n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        if messagebox.askyesno(APP_NAME, f"Forget {n} remembered download(s)? They will be "
                               "downloaded again if you add them.", parent=self):
            path.unlink(missing_ok=True)

    # ================================================================ periodic refresh

    def _tick(self):
        try:
            self._drain_events()
            self._drain_logs()
            self._update_summary()
            if self._queue_dirty and time.time() - self._last_queue_save > 5:
                self._save_queue()
        finally:
            self.after(self.TICK_MS, self._tick)

    def _drain_events(self):
        dirty: dict[int, Job] = {}
        structural = False
        while True:
            try:
                kind, job = self._events.get_nowait()
            except queue.Empty:
                break
            iid = str(job.id)
            if kind == "added":
                if not self.tree.exists(iid):
                    self.tree.insert("", "end", iid=iid)
                structural = True
                dirty[job.id] = job
            elif kind == "removed":
                if self.tree.exists(iid):
                    self.tree.delete(iid)
                dirty.pop(job.id, None)
                structural = True
            elif self.tree.exists(iid):
                dirty[job.id] = job
        if structural:
            self._reorder_tree()
            self._queue_dirty = True
        for job in dirty.values():
            if job.is_finished:
                self._queue_dirty = True
            self._render_row(job)
        sel = self.tree.selection()
        if len(sel) == 1 and int(sel[0]) in dirty:
            self._show_details()

    def _reorder_tree(self):
        for idx, job in enumerate(list(self.manager.jobs)):
            iid = str(job.id)
            if self.tree.exists(iid):
                self.tree.move(iid, "", idx)

    def _render_row(self, job: Job):
        st = job.status
        status = st.value + (f" · {job.detail}" if job.detail else "")
        if st in (Status.DOWNLOADING, Status.PROCESSING) or (st == Status.DONE):
            prog = progress_bar(job.progress)
        elif st in (Status.FAILED, Status.CANCELLED) and job.progress > 0:
            prog = progress_bar(job.progress)
        else:
            prog = ""
        size = human_bytes(job.total) if job.total else (human_bytes(job.downloaded) if job.downloaded else "")
        speed = f"{human_bytes(job.speed)}/s" if job.speed and st == Status.DOWNLOADING else ""
        eta = human_eta(job.eta) if job.eta is not None and st == Status.DOWNLOADING else ""
        fmt = job.format_note or _short_quality(job)
        if job.format_note and job.settings.mode == "video" and job.settings.video_container != "original":
            fmt = f"{job.format_note} {job.settings.video_container.upper()}"
        tag = {Status.DONE: "done", Status.FAILED: "failed", Status.CANCELLED: "muted",
               Status.SKIPPED: "muted"}.get(st, "active" if st in ACTIVE else "")
        self.tree.item(str(job.id), values=(job.display_title, status, prog, size, speed, eta, fmt),
                       tags=(tag,) if tag else ())

    def _update_summary(self):
        st = self.manager.stats()
        c = st["counts"]
        parts = []
        if st["active"]:
            parts.append(f"{st['active']} active")
        if st["queued"]:
            parts.append(f"{st['queued']} queued")
        if c[Status.DONE]:
            parts.append(f"{c[Status.DONE]} done")
        if c[Status.FAILED]:
            parts.append(f"{c[Status.FAILED]} failed")
        if st["speed"]:
            parts.append(f"{human_bytes(st['speed'])}/s")
        self.summary.configure(text="  ·  ".join(parts))
        if st["active"]:
            jobs = [j for j in self.manager.jobs if j.status not in (Status.CANCELLED,)]
            done = sum(1.0 if j.is_finished else j.progress for j in jobs)
            pct = int(100 * done / max(1, len(jobs)))
            self.title(f"{pct}% · {APP_NAME}")
            self.status_left.configure(text=f"Downloading… {pct}% of queue"
                                       + (f"  ·  {human_bytes(st['speed'])}/s" if st["speed"] else ""))
        elif self.title() != APP_NAME:
            self.title(APP_NAME)
            self.status_left.configure(text="Paused" if self.manager.paused and st["queued"] else "Idle")

    def _show_details(self):
        jobs = self._selected_jobs()
        t = self.details
        t.configure(state="normal")
        t.delete("1.0", "end")
        if len(jobs) == 1:
            j = jobs[0]
            t.insert("end", "Title   ", "key")
            t.insert("end", j.display_title + "\n")
            t.insert("end", "Link    ", "key")
            t.insert("end", j.url + "\n")
            if j.files:
                t.insert("end", "Saved   ", "key")
                t.insert("end", j.files[-1] + "\n")
            else:
                t.insert("end", "Folder  ", "key")
                t.insert("end", os.path.join(j.settings.output_dir, j.subdir) + "\n")
            if j.error:
                t.insert("end", "Error   ", "key")
                t.insert("end", j.error + "\n", "err")
            if j.hint:
                t.insert("end", "Tip     ", "key")
                t.insert("end", j.hint + "\n", "hint")
        elif jobs:
            t.insert("end", f"{len(jobs)} items selected")
        t.configure(state="disabled")

    # ================================================================ log

    def _drain_logs(self):
        batch = []
        for _ in range(500):
            try:
                batch.append(self._logs.get_nowait())
            except queue.Empty:
                break
        for level, msg in batch:
            self._append_log(level, msg)

    def _append_log(self, level, msg):
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        self._log_lines.append((level, line))
        if self.log_errors_only.get() and level == "info":
            return
        t = self.log_text
        at_end = t.yview()[1] > 0.98
        t.configure(state="normal")
        t.insert("end", line + "\n", level)
        if int(t.index("end-1c").split(".")[0]) > 5000:
            t.delete("1.0", "1000.0")
        t.configure(state="disabled")
        if at_end:
            t.see("end")

    def _rerender_log(self):
        t = self.log_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        only = self.log_errors_only.get()
        for level, line in self._log_lines:
            if not only or level != "info":
                t.insert("end", line + "\n", level)
        t.configure(state="disabled")
        t.see("end")

    def _clear_log(self):
        self._log_lines.clear()
        self._rerender_log()

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(line for _, line in self._log_lines))

    # ================================================================ environment

    def _update_env_labels(self):
        if not hasattr(self, "env_frame"):
            return
        pal = self._pal()
        env = self.env
        for w in self.env_frame.winfo_children():
            w.destroy()
        rows = [
            ("yt-dlp", env.ytdlp_version, True),
            ("ffmpeg", env.ffmpeg or "not found - install with:  winget install Gyan.FFmpeg", bool(env.ffmpeg)),
            ("JavaScript runtime",
             ", ".join(f"{k} ({v})" for k, v in env.js_runtimes.items())
             or "not found - install with:  winget install DenoLand.Deno", bool(env.js_runtimes)),
            ("aria2c", env.aria2c or "not found (optional)", True),
            ("Python", sys.version.split()[0], True),
            ("Settings", str(config_dir()), True),
        ]
        for r, (name, value, ok) in enumerate(rows):
            ttk.Label(self.env_frame, text="✓" if ok else "✗",
                      foreground=pal["ok"] if ok else pal["err"]).grid(row=r, column=0, padx=(0, 8), sticky="w")
            ttk.Label(self.env_frame, text=name).grid(row=r, column=1, sticky="w", padx=(0, 16), pady=1)
            ttk.Label(self.env_frame, text=value, foreground=pal["muted"] if ok else pal["err"]
                      ).grid(row=r, column=2, sticky="w")
        if hasattr(self, "aria_check"):
            self.aria_check.state(["!disabled"] if env.aria2c else ["disabled"])
        problems = env.problems()
        if hasattr(self, "status_right"):
            ok = not problems
            self.status_right.configure(
                text=("ffmpeg ✓   JS ✓" if ok else "⚠ Missing tools - see About"),
                foreground=pal["muted"] if ok else pal["warn"])
        if hasattr(self, "env_banner"):
            if problems:
                self.env_banner.configure(text="⚠  " + "\n⚠  ".join(problems), foreground=pal["warn"])
                self.env_banner.pack(fill="x", pady=(0, 8), before=self._queue_bar)
            else:
                self.env_banner.pack_forget()

    def _recheck_env(self):
        self.env = detect()
        self.manager.env = self.env
        self._update_env_labels()

    def _update_ytdlp(self):
        self.btn_update.state(["disabled"])
        self._append_log("info", "Updating yt-dlp…")
        self.nb.select(2)

        def run():
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                                   capture_output=True, text=True, creationflags=flags, timeout=600)
                out = (r.stdout + r.stderr).strip().splitlines()
                ok = r.returncode == 0
                msg = out[-1] if out else ""
            except Exception as e:
                ok, msg = False, str(e)
            self.after(0, lambda: self._update_done(ok, msg))
        threading.Thread(target=run, daemon=True).start()

    def _update_done(self, ok, msg):
        self.btn_update.state(["!disabled"])
        self._append_log("info" if ok else "error", msg or ("Update finished" if ok else "Update failed"))
        if ok:
            messagebox.showinfo(APP_NAME, "yt-dlp is up to date. Restart the app to use the new version.",
                                parent=self)

    # ================================================================ persistence

    def _queue_file(self):
        return config_dir() / "queue.json"

    def _save_queue(self):
        self._queue_dirty = False
        self._last_queue_save = time.time()
        try:
            data = self.manager.pending_snapshot()
            path = self._queue_file()
            if data:
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def _restore_queue(self):
        try:
            data = json.loads(self._queue_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, list) or not data:
            return
        self.manager.pause()
        n = 0
        for d in data:
            try:
                self.manager.add_job(Job.from_dict(d))
                n += 1
            except (KeyError, TypeError, ValueError):
                continue
        if n:
            self.banner.configure(text=f"Restored {n} unfinished download(s) from last time. "
                                       "Press 'Resume queue' to continue them.",
                                  foreground=self._pal()["active"])
            self.banner.pack(fill="x", pady=(0, 8), before=self._queue_bar)
        else:
            self.manager.resume()
        self._update_pause_button()

    def _on_close(self):
        active = [j for j in self.manager.jobs if j.is_active]
        if active and not messagebox.askyesno(
                APP_NAME, f"{len(active)} download(s) in progress.\n\nQuit anyway? They will be "
                "kept and can be resumed next time.", parent=self):
            return
        self._save_queue()
        self.settings.window_geometry = self.geometry()
        self._save_settings()
        self.withdraw()
        self.manager.shutdown(timeout=3)
        self.destroy()

    # ================================================================ misc

    def _tooltip(self, widget, text):
        tip = {"w": None}

        def show(_):
            if tip["w"]:
                return
            w = tk.Toplevel(self)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
            ttk.Label(w, text=text, padding=(8, 4), relief="solid", borderwidth=1).pack()
            tip["w"] = w

        def hide(_):
            if tip["w"]:
                tip["w"].destroy()
                tip["w"] = None
        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)


def _prepare_process():
    ensure_std_streams()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTDown.App")
        except Exception:
            pass


def main():
    _prepare_process()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
