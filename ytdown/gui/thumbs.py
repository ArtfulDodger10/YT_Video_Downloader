"""Background thumbnail fetching with a small in-memory cache."""

from __future__ import annotations

import ssl
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


class ThumbnailLoader(QObject):
    loaded = Signal(str)            # url, emitted on the GUI thread once cached
    _fetched = Signal(str, bytes)   # internal: worker thread -> GUI thread

    def __init__(self, max_items: int = 500, parent=None):
        super().__init__(parent)
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._max = max_items
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
        self._ssl = ssl.create_default_context()  # OS trust store (works behind HTTPS scanning)
        self.proxy = ""
        self._fetched.connect(self._store, Qt.QueuedConnection)

    def get(self, url: str):
        if not url:
            return None
        pm = self._cache.get(url)
        if pm is not None:
            self._cache.move_to_end(url)
            return pm
        if url not in self._pending and url not in self._failed:
            self._pending.add(url)
            self._pool.submit(self._fetch, url)
        return None

    def _fetch(self, url: str):
        data = b""
        try:
            handlers = [urllib.request.HTTPSHandler(context=self._ssl)]
            if self.proxy.startswith(("http://", "https://")):
                handlers.append(urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
            opener = urllib.request.build_opener(*handlers)
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with opener.open(req, timeout=15) as r:
                data = r.read(5_000_000)
        except Exception:
            data = b""
        self._fetched.emit(url, data)

    def _store(self, url: str, data: bytes):
        self._pending.discard(url)
        img = QImage()
        if not data or not img.loadFromData(data):
            self._failed.add(url)
            return
        if img.width() > 640:
            img = img.scaledToWidth(640, Qt.SmoothTransformation)
        self._cache[url] = QPixmap.fromImage(img)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        self.loaded.emit(url)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
