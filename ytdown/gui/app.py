"""Main window. Worker threads never touch widgets: they push events into queues that a
100 ms timer drains on the GUI thread, so the UI stays smooth with hundreds of downloads."""

from __future__ import annotations

import getpass
import json
import os
import queue
import sys
import time
from importlib import resources

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QGuiApplication, QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..deps import detect
from ..engine import DownloadManager, Job, Status
from ..options import _URL_RE, extract_targets, validate_extra_args
from ..settings import Settings, config_dir
from ..util import ensure_std_streams, human_bytes, open_path
from . import icons, theme
from .about import AboutPage
from .activity import ActivityPage
from .downloads import DownloadsPage
from .settings_page import SettingsPage
from .thumbs import ThumbnailLoader
from .widgets import Toast, label, refresh_icon

NAV = [("downloads", "Downloads", "download"), ("settings", "Settings", "settings"),
       ("activity", "Activity", "activity"), ("about", "About", "info")]


def app_icon() -> QIcon:
    try:
        data = resources.files("ytdown").joinpath("assets/icon.png").read_bytes()
        pm = QPixmap()
        pm.loadFromData(data)
        if not pm.isNull():
            return QIcon(pm)
    except (OSError, ModuleNotFoundError):
        pass
    return icons.icon("download", "#7c6cff", 64)


class MainWindow(QMainWindow):
    TICK_MS = 100

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.env = detect()
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._logs: queue.SimpleQueue = queue.SimpleQueue()
        self._notified: set[int] = set()
        self._queue_dirty = False
        self._last_queue_save = 0.0
        self._quitting = False
        self._tray_hint_shown = False
        self.tray = None

        self.manager = DownloadManager(
            self.env, on_event=lambda k, j: self._events.put((k, j)),
            on_log=lambda lvl, msg: self._logs.put((lvl, msg)),
            archive_path=str(config_dir() / "archive.txt"),
            max_concurrent=self.settings.max_concurrent)
        self.thumbs = ThumbnailLoader(parent=self)
        self.thumbs.proxy = self.settings.proxy
        self.thumbs.loaded.connect(self._thumb_loaded)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(980, 640)
        self.resize(1200, 780)
        self.setAcceptDrops(True)
        theme.apply(QApplication.instance(), self.settings.theme, config_dir() / "cache")
        self._build()
        self._restore_geometry()
        self._setup_tray()
        self._restore_queue()
        self.recheck_env(initial=True)
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_settings)
        QGuiApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self._last_clip = QGuiApplication.clipboard().text()
        self._timer = QTimer(self, interval=self.TICK_MS, timeout=self._tick)
        self._timer.start()

    # ================================================================ layout

    def _build(self):
        central = QWidget()
        central.setObjectName("Central")
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.pages = {
            "downloads": DownloadsPage(self),
            "settings": SettingsPage(self),
            "activity": ActivityPage(self),
            "about": AboutPage(self),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.downloads: DownloadsPage = self.pages["downloads"]
        self.toaster = Toast(central)
        self.downloads.env_bar.action.clicked.connect(lambda: self.go("about"))
        self.downloads.restore_bar.action.clicked.connect(self._resume_restored)
        self.go("downloads")
        self._refresh_icons()

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 18, 14, 14)
        v.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(34, 34))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(APP_NAME, "Brand"))
        names.addWidget(label(f"v{__version__}", "BrandSub"))
        brand.addLayout(names)
        brand.addStretch(1)
        v.addLayout(brand)
        v.addSpacing(22)

        self.nav = {}
        group = QButtonGroup(self)
        for key, text, icon in NAV:
            b = QPushButton(f"  {text}")
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("iconName", icon)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            group.addButton(b)
            self.nav[key] = b
            v.addWidget(b)
        badge_host = QHBoxLayout(self.nav["downloads"])
        badge_host.setContentsMargins(0, 0, 10, 0)
        badge_host.addStretch(1)
        self.badge = label("", "NavBadge")
        self.badge.hide()
        badge_host.addWidget(self.badge)

        v.addStretch(1)
        self.tool_pill = label("", "ToolPill", wrap=True)
        self.tool_pill.setCursor(Qt.PointingHandCursor)
        self.tool_pill.mousePressEvent = lambda e: self.go("about")
        v.addWidget(self.tool_pill)
        return side

    def go(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)

    def toast(self, text: str):
        self.toaster.show_message(text)

    def log(self, level: str, msg: str):
        self._logs.put((level, msg))

    # ================================================================ theme

    def _is_dark(self) -> bool:
        return theme.current()["bg"] == theme.DARK["bg"]

    def _refresh_icons(self):
        t = theme.current()
        for b in self.findChildren(QPushButton):
            if b.objectName() == "NavButton":
                b.setIcon(icons.icon(b.property("iconName"), t["muted"], 18))
            else:
                refresh_icon(b)
        self.downloads.refresh_theme()
        self.pages["about"].refresh()
        for bar in (self.downloads.env_bar, self.downloads.restore_bar):
            bar.refresh()
        self._update_tool_pill()
        self._dark_titlebar(self._is_dark())

    def _dark_titlebar(self, dark: bool):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            val = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (current, then pre-20H1)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                             ctypes.sizeof(val)) == 0:
                    break
        except Exception:
            pass

    # ================================================================ settings

    def set_setting(self, name: str, value, sync: bool = True):
        if getattr(self.settings, name) == value:
            return
        if name == "output_dir" and not str(value).strip():
            return
        setattr(self.settings, name, value)
        self._save_timer.start()
        if name == "max_concurrent":
            self.manager.set_max_concurrent(value)
        elif name == "theme":
            theme.apply(QApplication.instance(), value, config_dir() / "cache")
            self._refresh_icons()
            self.downloads.view.viewport().update()
        elif name == "proxy":
            self.thumbs.proxy = value
        elif name == "watch_clipboard" and value:
            self._last_clip = QGuiApplication.clipboard().text()
        elif name == "extra_args":
            self.pages["settings"].update_extra_msg()
        if sync and name in ("mode", "video_quality", "audio_quality", "video_container",
                             "audio_format", "output_dir", "download_playlist", "playlist_items"):
            self.downloads.sync_from_settings()

    def replace_settings(self, fresh: Settings):
        self.settings = fresh
        self._save_settings()
        self.manager.set_max_concurrent(fresh.max_concurrent)
        self.thumbs.proxy = fresh.proxy
        theme.apply(QApplication.instance(), fresh.theme, config_dir() / "cache")
        self._refresh_icons()
        self.downloads.sync_from_settings()
        self.pages["settings"].sync()

    def _save_settings(self):
        try:
            self.settings.save()
        except OSError as e:
            self.log("error", f"Could not save settings: {e}")

    # ================================================================ adding

    def add_text(self, text: str, source: str = "") -> bool:
        return self.add_targets(extract_targets(text), source=source)

    def add_targets(self, targets, first_extra=None, source: str = "") -> bool:
        if not targets:
            return False
        err = validate_extra_args(self.settings.extra_args)
        if err:
            QMessageBox.warning(self, APP_NAME, f"The extra yt-dlp arguments in Settings are invalid:\n\n{err}")
            return False
        out = self.settings.output_dir.strip()
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Can't use the download folder:\n{out}\n\n{e}")
            return False
        added = dupes = 0
        for i, t in enumerate(targets):
            kw = dict(first_extra or {}) if i == 0 else {}
            if self.manager.add(t, self.settings, **kw):
                added += 1
            else:
                dupes += 1
        if self.settings.playlist_items:
            self.set_setting("playlist_items", "")  # a range is meant for the links just added
        if added:
            msg = "Added to downloads" if added == 1 else f"Added {added} downloads"
            if source:
                msg += f" from {source}"
            self.toast(msg + (f" ({dupes} already queued)" if dupes else ""))
        elif dupes:
            self.toast("Already in the queue")
        self.go("downloads")
        return True

    def toggle_pause(self):
        if self.manager.paused:
            self.manager.resume()
            self.downloads.restore_bar.hide()
        else:
            self.manager.pause()
            self.toast("Queue paused: running downloads will finish")
        self.downloads.update_counts()
        self._update_tray_menu()

    def open_folder(self, path: str):
        path = path if os.path.isdir(path) else self.settings.output_dir
        try:
            os.makedirs(path, exist_ok=True)
            open_path(path)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, str(e))

    # ================================================================ environment

    def recheck_env(self, initial: bool = False):
        if not initial:
            self.env = detect()
            self.manager.env = self.env
        problems = self.env.problems()
        if problems:
            self.downloads.env_bar.set("\n".join(problems), "How to fix", level="warn")
        else:
            self.downloads.env_bar.hide()
        self.pages["about"].refresh()
        self.pages["settings"].sync()
        self._update_tool_pill()
        if not initial:
            self.toast("All tools found" if not problems else "Some tools are still missing")

    def _update_tool_pill(self):
        if not hasattr(self, "tool_pill"):
            return
        t = theme.current()

        def dot(ok):
            return f"<span style='color:{t['ok'] if ok else t['err']}'>●</span>"
        self.tool_pill.setText(f"{dot(bool(self.env.ffmpeg))} ffmpeg &nbsp;&nbsp; "
                               f"{dot(bool(self.env.js_runtimes))} JS runtime<br>"
                               f"<span style='color:{t['faint']}'>yt-dlp {self.env.ytdlp_version}</span>")

    # ================================================================ periodic refresh

    def _tick(self):
        dirty, structural, finished = set(), False, []
        while True:
            try:
                kind, job = self._events.get_nowait()
            except queue.Empty:
                break
            if kind in ("added", "removed"):
                structural = True
            dirty.add(job.id)
            if job.is_finished and job.id not in self._notified:
                self._notified.add(job.id)
                finished.append(job)
            elif not job.is_finished:
                self._notified.discard(job.id)
        if structural:
            self.downloads.model.sync()
            self._queue_dirty = True
        if dirty:
            self.downloads.model.refresh(dirty)
            self.downloads.update_counts()
        if any(j.is_active for j in self.manager.jobs):
            self.downloads.view.viewport().update()  # animated progress bars
        self._drain_logs()
        self._update_title()
        if finished:
            self._queue_dirty = True
            self._notify(finished)
        if self._queue_dirty and time.time() - self._last_queue_save > 4:
            self._save_queue()

    def _drain_logs(self):
        items = []
        for _ in range(1000):
            try:
                items.append(self._logs.get_nowait())
            except queue.Empty:
                break
        if items:
            self.pages["activity"].append_many(items)

    def _update_title(self):
        st = self.manager.stats()
        pending = st["active"] + st["queued"]
        self.badge.setText(str(pending))
        self.badge.setVisible(pending > 0)
        speed = st["speed"]
        self.downloads.speed_label.setText(f"↓ {human_bytes(speed)}/s" if speed else "")
        if st["active"]:
            jobs = [j for j in self.manager.jobs if j.status != Status.CANCELLED]
            done = sum(1.0 if j.is_finished else j.progress for j in jobs)
            title = f"{int(100 * done / max(1, len(jobs)))}% · {APP_NAME}"
        else:
            title = APP_NAME
        if self.windowTitle() != title:
            self.setWindowTitle(title)
            if self.tray:
                self.tray.setToolTip(title)

    def _thumb_loaded(self, url: str):
        m = self.downloads.model
        for row in m.rows_with_thumbnail(url):
            idx = m.index(row)
            m.dataChanged.emit(idx, idx)
        self.downloads.thumbnail_loaded(url)

    def _notify(self, jobs):
        if not self.settings.notify_done or not self.tray or (self.isActiveWindow() and self.isVisible()):
            return
        listed = {id(j) for j in self.manager.jobs}
        done = [j for j in jobs if j.status == Status.DONE and id(j) in listed]
        failed = [j for j in jobs if j.status == Status.FAILED and id(j) in listed]
        if done:
            text = done[0].display_title if len(done) == 1 else f"{len(done)} downloads finished"
            self.tray.showMessage("Download complete", text, self.windowIcon(), 4000)
        if failed:
            text = failed[0].display_title if len(failed) == 1 else f"{len(failed)} downloads failed"
            self.tray.showMessage("Download failed", text, QSystemTrayIcon.Warning, 5000)

    # ================================================================ tray

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("Show " + APP_NAME, self._show_window)
        self._tray_pause = QAction("Pause downloads", self)
        self._tray_pause.triggered.connect(self.toggle_pause)
        menu.addAction(self._tray_pause)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_window() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.messageClicked.connect(self._show_window)
        self.tray.show()

    def _update_tray_menu(self):
        if self.tray:
            self._tray_pause.setText("Resume downloads" if self.manager.paused else "Pause downloads")

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._quitting = True
        self.close()

    # ================================================================ clipboard, drops, IPC

    def _clipboard_changed(self):
        text = QGuiApplication.clipboard().text()
        previous, self._last_clip = self._last_clip, text
        if not self.settings.watch_clipboard or text == previous or len(text) > 20000:
            return
        urls = list(dict.fromkeys(_URL_RE.findall(text)))
        if urls:
            self.add_targets(urls, source="clipboard")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        text = md.text() if md.hasText() else "\n".join(u.toString() for u in md.urls())
        if not self.add_text(text, source="drop"):
            self.toast("No links found in what you dropped")

    def handle_ipc(self, payload: str):
        self._show_window()
        text = payload.strip()
        if text and text != "__show__":
            self.add_text(text)

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
            self.downloads.restore_bar.set(f"Restored {n} unfinished download{'s' if n > 1 else ''} "
                                           "from last time.", "Resume", level="info")
        else:
            self.manager.resume()

    def _resume_restored(self):
        self.manager.resume()
        self.downloads.restore_bar.hide()
        self.downloads.update_counts()

    def _restore_geometry(self):
        g = self.settings.window_geometry
        if g and "x" not in g:  # ignore the old Tk "WxH+X+Y" format
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))

    def closeEvent(self, e):
        if not self._quitting and self.settings.close_to_tray and self.tray:
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(APP_NAME, "Still running in the tray. Right-click the icon to quit.",
                                      self.windowIcon(), 3000)
                self._tray_hint_shown = True
            return
        active = [j for j in self.manager.jobs if j.is_active]
        if active and QMessageBox.question(
                self, APP_NAME, f"{len(active)} download(s) in progress.\n\nQuit anyway? They will be "
                "kept and can be resumed next time.") != QMessageBox.Yes:
            self._quitting = False
            e.ignore()
            return
        self._timer.stop()
        self._save_queue()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self._save_settings()
        self.hide()
        if self.tray:
            self.tray.hide()
        self.manager.shutdown(timeout=3)
        self.thumbs.shutdown()
        e.accept()
        QApplication.instance().quit()


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"ytdown-{user}"


def main(targets=None):
    ensure_std_streams()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTDown.App")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))

    # Single instance: pass links to the running window instead of opening a second one.
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if sock.waitForConnected(300):
        sock.write(("\n".join(targets or []) or "__show__").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(_server_name())
    server = QLocalServer()
    server.listen(_server_name())

    win = MainWindow()

    def on_connection():
        conn = server.nextPendingConnection()
        conn.waitForReadyRead(500)
        win.handle_ipc(bytes(conn.readAll()).decode("utf-8", "replace"))
        conn.disconnectFromServer()
    server.newConnection.connect(on_connection)
    win.show()
    win._dark_titlebar(win._is_dark())
    if targets:
        win.add_targets(list(targets))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
