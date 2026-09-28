"""About page: version, detected tools (with one-click installs) and links."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from PySide6 import __version__ as qt_version
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from .. import APP_NAME, __version__
from ..settings import config_dir
from ..util import open_path
from . import theme
from .widgets import button, label

REPO = "ArtfulDodger10/YT_Video_Downloader"
PROJECT_URL = f"https://github.com/{REPO}"
WINGET = {"ffmpeg": "Gyan.FFmpeg", "deno": "DenoLand.Deno"}
DOWNLOAD_PAGES = {"ffmpeg": "https://ffmpeg.org/download.html", "deno": "https://deno.com/"}


class AboutPage(QWidget):
    _update_result = Signal(str, str)  # kind, message
    _release_result = Signal(object)

    def __init__(self, win):
        super().__init__()
        self.setObjectName("Page")
        self.win = win
        self._update_result.connect(self._on_update_done)
        self._release_result.connect(self._on_release)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 22, 28, 22)
        v.setSpacing(16)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.logo = QLabel()
        hero.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(label(APP_NAME, "H1"))
        names.addWidget(label(f"Version {__version__}  ·  Video & audio downloader powered by yt-dlp", "Muted"))
        hero.addLayout(names)
        hero.addStretch(1)
        v.addLayout(hero)

        self.tools_card = QFrame()
        self.tools_card.setObjectName("Card")
        self.tools = QGridLayout(self.tools_card)
        self.tools.setContentsMargins(20, 16, 20, 16)
        self.tools.setHorizontalSpacing(16)
        self.tools.setVerticalSpacing(10)
        self.tools.setColumnStretch(2, 1)
        v.addWidget(self.tools_card)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        recheck = button("Re-check tools", "retry")
        recheck.clicked.connect(self.win.recheck_env)
        actions.addWidget(recheck)
        self.update_btn = button("Update yt-dlp", "download")
        self.update_btn.setToolTip("Sites change often; a newer yt-dlp usually fixes broken downloads")
        self.update_btn.clicked.connect(self.update_ytdlp)
        actions.addWidget(self.update_btn)
        rel = button("Check for app updates", "sparkle")
        rel.clicked.connect(self.check_release)
        actions.addWidget(rel)
        cfg = button("Open settings folder", "folder")
        cfg.clicked.connect(lambda: open_path(str(config_dir())))
        actions.addWidget(cfg)
        actions.addStretch(1)
        v.addLayout(actions)

        links = QHBoxLayout()
        links.setSpacing(4)
        for text, icon, url in (("GitHub", "external", PROJECT_URL),
                                ("Report a problem", "alert", PROJECT_URL + "/issues/new/choose"),
                                ("Supported sites", "globe",
                                 "https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md")):
            b = button(text, icon, flat=True)
            b.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            links.addWidget(b)
        links.addStretch(1)
        v.addLayout(links)
        v.addStretch(1)
        v.addWidget(label("Only download content you own or have permission to download, and respect "
                          "each site's terms of service. DRM-protected services are not supported.",
                          "Faint", wrap=True))
        self.refresh()

    def refresh(self):
        t = theme.current()
        self.logo.setPixmap(self.win.windowIcon().pixmap(64, 64))
        while self.tools.count():
            w = self.tools.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        env = self.win.env
        self.tools.addWidget(label("Components", "H2"), 0, 0, 1, 4)
        rows = [
            ("yt-dlp", env.ytdlp_version, True, None),
            ("ffmpeg", env.ffmpeg or "Not found: HD merging, audio conversion and embedding won't work",
             bool(env.ffmpeg), "ffmpeg"),
            ("JavaScript runtime", ", ".join(f"{k}  ({p})" for k, p in env.js_runtimes.items())
             or "Not found: YouTube will offer only a few low-quality formats",
             bool(env.js_runtimes), "deno"),
            ("aria2c", env.aria2c or "Not installed (optional)", True, None),
            ("Python / Qt", f"{sys.version.split()[0]}  /  {qt_version}", True, None),
            ("Settings folder", str(config_dir()), True, None),
        ]
        for r, (name, value, ok, fix) in enumerate(rows, start=1):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {t['ok'] if ok else t['err']}; font-size: 9pt")
            self.tools.addWidget(dot, r, 0)
            self.tools.addWidget(label(name), r, 1)
            val = label(value, "Muted" if ok else "Error", wrap=True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.tools.addWidget(val, r, 2)
            if fix and not ok:
                b = button("Install", "download", primary=True)
                b.clicked.connect(lambda _=False, f=fix: self.install(f))
                self.tools.addWidget(b, r, 3)
        self.update_btn.setVisible(not env.frozen)

    def install(self, tool: str):
        if sys.platform == "win32" and shutil.which("winget"):
            # A visible console so the user sees (and can answer) winget's prompts.
            subprocess.Popen(["cmd", "/c", "start", f"Install {tool}", "cmd", "/k",
                              f"winget install -e --id {WINGET[tool]} && echo. && "
                              f"echo Done. Close this window and press Re-check tools in {APP_NAME}."])
            self.win.toast(f"Installing {tool} in a new window…")
        else:
            webbrowser.open(DOWNLOAD_PAGES[tool])

    def update_ytdlp(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Updating…")

        def run():
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                                   capture_output=True, text=True, creationflags=flags, timeout=600)
                out = (r.stdout + r.stderr).strip().splitlines()
                self._update_result.emit("ok" if r.returncode == 0 else "err", out[-1] if out else "")
            except Exception as e:
                self._update_result.emit("err", str(e))
        threading.Thread(target=run, daemon=True).start()

    def _on_update_done(self, kind, msg):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Update yt-dlp")
        self.win.log("info" if kind == "ok" else "error", f"yt-dlp update: {msg}")
        if kind == "ok":
            QMessageBox.information(self, "Update yt-dlp", "yt-dlp is up to date.\n"
                                    "Restart the app to use the new version.")
        else:
            QMessageBox.warning(self, "Update yt-dlp", f"The update failed:\n{msg}")

    def check_release(self):
        def run():
            try:
                req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                             headers={"Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._release_result.emit(json.load(r))
            except Exception as e:
                self._release_result.emit({"error": str(e)})
        threading.Thread(target=run, daemon=True).start()

    def _on_release(self, data):
        if "error" in data or not data.get("tag_name"):
            QMessageBox.information(self, "Updates", "Couldn't check for updates right now.")
            return
        latest = data["tag_name"].lstrip("v")
        if _ver(latest) > _ver(__version__):
            if QMessageBox.question(self, "Update available",
                                    f"{APP_NAME} {latest} is available (you have {__version__}).\n"
                                    "Open the download page?") == QMessageBox.Yes:
                webbrowser.open(data.get("html_url") or PROJECT_URL + "/releases")
        else:
            QMessageBox.information(self, "Updates", f"You have the latest version ({__version__}).")


def _ver(s: str):
    return tuple(int(p) if p.isdigit() else 0 for p in s.split(".")[:3])

