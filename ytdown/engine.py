"""Download queue and workers, driving yt-dlp in-process.

Each Job runs in its own worker thread (up to `max_concurrent` at once). A job
extracts its URL exactly once: if the result is a playlist/channel/search it is
expanded into one child job per entry (so playlist items download in parallel),
otherwise the already-extracted info is handed straight to the download step.
"""

from __future__ import annotations

import itertools
import os
import re
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, sanitize_filename

from .deps import Environment
from .options import build_args, clean_error, hint_for
from .settings import Settings


class Status(str, Enum):
    QUEUED = "Queued"
    STARTING = "Starting"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    DONE = "Done"
    SKIPPED = "Skipped"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


ACTIVE = {Status.STARTING, Status.DOWNLOADING, Status.PROCESSING}
FINISHED = {Status.DONE, Status.SKIPPED, Status.FAILED, Status.CANCELLED}

_PP_NAMES = {
    "Merger": "Merging video + audio", "FFmpegMerger": "Merging video + audio",
    "ExtractAudio": "Converting audio", "FFmpegExtractAudio": "Converting audio",
    "VideoRemuxer": "Remuxing", "FFmpegVideoRemuxer": "Remuxing",
    "VideoConvertor": "Converting video", "FFmpegVideoConvertor": "Converting video",
    "EmbedThumbnail": "Embedding thumbnail", "FFmpegMetadata": "Writing metadata",
    "Metadata": "Writing metadata", "EmbedSubtitle": "Embedding subtitles",
    "FFmpegEmbedSubtitle": "Embedding subtitles", "SponsorBlock": "Fetching SponsorBlock",
    "ModifyChapters": "Cutting segments", "FixupM3u8": "Fixing stream",
    "FFmpegFixupM3u8": "Fixing stream", "FixupM4a": "Fixing container",
    "MoveFiles": "Finishing", "MoveFilesAfterDownload": "Finishing",
    "SubtitlesConvertor": "Converting subtitles", "ThumbnailsConvertor": "Converting thumbnail",
}

_ids = itertools.count(1)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# yt-dlp announces side files it writes before/around the media download
_SIDE_FILE = re.compile(r"^\[\w+\] Writing [^:]*? to: (.+)$")


@dataclass(eq=False)
class Job:
    url: str
    settings: Settings
    title: str = ""
    subdir: str = ""
    prefix: str = ""
    noplaylist: Optional[bool] = None
    ie_key: Optional[str] = None
    depth: int = 0
    id: int = field(default_factory=lambda: next(_ids))
    status: Status = Status.QUEUED
    detail: str = ""
    progress: float = 0.0
    downloaded: int = 0
    total: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    format_note: str = ""
    files: list = field(default_factory=list)
    temp_files: set = field(default_factory=set)
    error: str = ""
    hint: str = ""
    log: deque = field(default_factory=lambda: deque(maxlen=400))
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    remove_when_done: bool = False

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.url.startswith("ytsearch"):
            return "Search: " + self.url.split(":", 1)[1]
        return self.url

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    @property
    def is_finished(self) -> bool:
        return self.status in FINISHED

    def reset(self):
        self.status = Status.QUEUED
        self.detail = self.error = self.hint = ""
        self.progress, self.downloaded = 0.0, 0
        self.total = self.speed = self.eta = None
        self.files = []
        self.cancel_event = threading.Event()
        self.started_at = self.finished_at = None

    def to_dict(self) -> dict:
        return {"url": self.url, "settings": self.settings.to_dict(), "title": self.title,
                "subdir": self.subdir, "prefix": self.prefix, "noplaylist": self.noplaylist,
                "ie_key": self.ie_key, "depth": self.depth}

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(url=str(d["url"]), settings=Settings.from_dict(d.get("settings") or {}),
                   title=str(d.get("title") or ""), subdir=str(d.get("subdir") or ""),
                   prefix=str(d.get("prefix") or ""), noplaylist=d.get("noplaylist"),
                   ie_key=d.get("ie_key"), depth=int(d.get("depth") or 0))


class _JobLogger:
    """Receives yt-dlp's messages for a single job."""

    def __init__(self, manager: "DownloadManager", job: Job,
                 watch: Optional[Callable[[str], None]] = None):
        self.m, self.job, self.watch = manager, job, watch

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self._emit("info", msg)

    def info(self, msg):
        self._emit("info", msg)

    def warning(self, msg):
        self._emit("warning", msg)

    def error(self, msg):
        self._emit("error", msg)

    def _emit(self, level, msg):
        msg = _ANSI.sub("", str(msg)).rstrip()
        if not msg:
            return
        self.job.log.append(msg)
        if self.watch:
            self.watch(msg)
        self.m._log(level, f"#{self.job.id} {msg}")


EventHandler = Callable[[str, Job], None]  # ("added" | "changed" | "removed", job)
LogHandler = Callable[[str, str], None]    # (level, message)


class DownloadManager:
    MAX_DEPTH = 3

    def __init__(self, env: Environment, on_event: Optional[EventHandler] = None,
                 on_log: Optional[LogHandler] = None, archive_path: Optional[str] = None,
                 max_concurrent: int = 3):
        self.env = env
        self.on_event = on_event or (lambda kind, job: None)
        self.on_log = on_log or (lambda level, msg: None)
        self.archive_path = archive_path
        self.jobs: list[Job] = []
        self.max_concurrent = max(1, max_concurrent)
        self.paused = False
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._threads: dict[int, threading.Thread] = {}
        self._claims: dict[str, str] = {}  # lower-cased output path stem -> video id
        self._stem_locks: dict[str, threading.Lock] = {}

    # ---- public API (thread-safe) ---------------------------------------

    def add(self, url: str, settings: Settings, **kw) -> Optional[Job]:
        """Queue a URL. Returns None if the same URL is already queued or running."""
        with self._lock:
            if any(j.url == url and not j.is_finished for j in self.jobs):
                return None
            job = Job(url=url, settings=replace(settings), **kw)
            self.jobs.append(job)
        self.on_event("added", job)
        self._pump()
        return job

    def add_job(self, job: Job) -> Job:
        with self._lock:
            self.jobs.append(job)
        self.on_event("added", job)
        self._pump()
        return job

    def cancel(self, job: Job):
        with self._lock:
            if job.status == Status.QUEUED:
                job.status = Status.CANCELLED
                job.finished_at = time.time()
            elif job.is_active:
                job.cancel_event.set()
                job.detail = "Cancelling…"
            else:
                return
        self.on_event("changed", job)
        self._pump()

    def retry(self, job: Job):
        with self._lock:
            if job not in self.jobs or not job.is_finished or job.status == Status.DONE:
                return
            job.reset()
        self.on_event("changed", job)
        self._pump()

    def remove(self, job: Job, delete_partial: bool = True):
        with self._lock:
            if job not in self.jobs:
                return
            if job.is_active:
                job.remove_when_done = True
                job.cancel_event.set()
                return
            self.jobs.remove(job)
        if delete_partial and job.status != Status.DONE:
            self._delete_partials(job)
        self.on_event("removed", job)

    def clear_finished(self):
        with self._lock:
            done = [j for j in self.jobs if j.status in (Status.DONE, Status.SKIPPED)]
            for j in done:
                self.jobs.remove(j)
        for j in done:
            self.on_event("removed", j)

    def move(self, job: Job, to_top: bool = True):
        with self._lock:
            if job in self.jobs:
                self.jobs.remove(job)
                if to_top:
                    self.jobs.insert(0, job)
                else:
                    self.jobs.append(job)
        self.on_event("changed", job)

    def set_max_concurrent(self, n: int):
        self.max_concurrent = max(1, int(n))
        self._pump()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False
        self._pump()

    def stats(self) -> dict:
        with self._lock:
            counts = {s: 0 for s in Status}
            speed = 0.0
            for j in self.jobs:
                counts[j.status] += 1
                if j.status == Status.DOWNLOADING and j.speed:
                    speed += j.speed
        return {"counts": counts, "speed": speed,
                "active": sum(counts[s] for s in ACTIVE), "queued": counts[Status.QUEUED]}

    def pending_snapshot(self) -> list[dict]:
        """Unfinished jobs, for restoring the queue on next launch."""
        with self._lock:
            return [j.to_dict() for j in self.jobs if not j.is_finished]

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until nothing is queued or running (or paused with nothing running)."""
        end = None if timeout is None else time.time() + timeout
        with self._idle:
            while True:
                busy = any(j.is_active for j in self.jobs) or (
                    not self.paused and any(j.status == Status.QUEUED for j in self.jobs))
                if not busy:
                    return True
                remaining = None if end is None else end - time.time()
                if remaining is not None and remaining <= 0:
                    return False
                self._idle.wait(0.25 if remaining is None else min(0.25, remaining))

    def shutdown(self, timeout: float = 5.0):
        """Cancel running downloads and wait briefly for workers to stop."""
        self.paused = True
        with self._lock:
            threads = list(self._threads.values())
            for j in self.jobs:
                if j.is_active:
                    j.cancel_event.set()
        end = time.time() + timeout
        for t in threads:
            t.join(max(0.0, end - time.time()))

    # ---- scheduling ------------------------------------------------------

    def _pump(self):
        started = []
        with self._lock:
            if not self.paused:
                running = sum(1 for j in self.jobs if j.is_active)
                for job in self.jobs:
                    if running >= self.max_concurrent:
                        break
                    if job.status == Status.QUEUED:
                        job.status = Status.STARTING
                        job.detail = "Fetching info…"
                        job.started_at = time.time()
                        t = threading.Thread(target=self._worker, args=(job,),
                                             name=f"job-{job.id}", daemon=True)
                        self._threads[job.id] = t
                        started.append((job, t))
                        running += 1
            self._idle.notify_all()
        for job, t in started:
            self.on_event("changed", job)
            t.start()

    def _worker(self, job: Job):
        try:
            self._run(job)
        except DownloadCancelled:
            self._finish(job, Status.CANCELLED, "Cancelled")
        except DownloadError as e:
            if job.cancel_event.is_set():
                self._finish(job, Status.CANCELLED, "Cancelled")
            else:
                self._fail(job, clean_error(e.msg if getattr(e, "msg", None) else e))
        except SystemExit:
            self._fail(job, "Invalid yt-dlp options (check Settings > Advanced > Extra arguments).")
        except Exception as e:  # never let a worker die silently
            job.log.append(traceback.format_exc())
            self._fail(job, f"Unexpected error: {clean_error(e)}")
        finally:
            remove = False
            with self._lock:
                self._threads.pop(job.id, None)
                if job.remove_when_done and job in self.jobs:
                    self.jobs.remove(job)
                    remove = True
                self._idle.notify_all()
            if remove:
                if job.status != Status.DONE:
                    self._delete_partials(job)
                self.on_event("removed", job)
            else:
                self.on_event("changed", job)
            self._pump()

    # ---- the actual download ----------------------------------------------

    def _run(self, job: Job):
        argv = build_args(job.settings, self.env, subdir=job.subdir, prefix=job.prefix,
                          noplaylist=job.noplaylist, archive_path=self.archive_path)
        opts = yt_dlp.parse_options(argv).ydl_opts
        state = {"downloaded_any": False, "skip_msg": ""}

        def watch(msg):
            low = msg.lower()
            if "recorded in the archive" in low or "has already been downloaded" in low:
                state["skip_msg"] = msg
            m = _SIDE_FILE.match(msg)
            if m:
                job.temp_files.add(m.group(1).strip())
        logger = _JobLogger(self, job, watch)

        opts.update({
            "logger": logger,
            "progress_hooks": [lambda d: self._progress_hook(job, d, state)],
            "postprocessor_hooks": [lambda d: self._pp_hook(job, d)],
            "post_hooks": [lambda path: job.files.append(path)],
            "extract_flat": "in_playlist",
            "noprogress": True,
        })
        self._check_cancel(job)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ie = ydl.extract_info(job.url, download=False, process=False, ie_key=job.ie_key)
            for _ in range(3):  # follow plain redirects (short links etc.)
                if ie and ie.get("_type") == "url" and ie.get("url"):
                    ie = ydl.extract_info(ie["url"], download=False, process=False,
                                          ie_key=ie.get("ie_key"))
                else:
                    break
            if not ie:
                raise DownloadError("Nothing to download (extractor returned no result).")
            self._check_cancel(job)

            if ie.get("_type") in ("playlist", "multi_video"):
                flat = ydl.process_ie_result(ie, download=False)
                self._expand(job, flat or ie)
                return

            if ie.get("title") and not job.title:
                job.title = ie["title"]
                self.on_event("changed", job)
            stem = self._claim_filename(ydl, ie, job)
            lock = self._stem_lock(stem)
            # Two jobs for the same output (e.g. a link that also appears in a search or
            # playlist) run one after the other; the second then sees the finished file.
            while not lock.acquire(timeout=0.3):
                self._check_cancel(job)
                if job.detail != "Waiting for a duplicate to finish…":
                    job.detail = "Waiting for a duplicate to finish…"
                    self.on_event("changed", job)
            try:
                job.detail = ""
                ydl.process_ie_result(ie, download=True)
            finally:
                lock.release()

        self._check_cancel(job)
        if job.files:
            detail = "Already downloaded" if not state["downloaded_any"] and state["skip_msg"] else ""
            try:
                job.total = os.path.getsize(job.files[-1])  # real size after merging/converting
            except OSError:
                pass
            job.progress = 1.0
            self._finish(job, Status.DONE, detail)
        elif state["skip_msg"]:
            self._finish(job, Status.SKIPPED, "Already downloaded (archive)")
        else:
            self._finish(job, Status.SKIPPED, "Nothing downloaded (filtered or unavailable)")

    def _expand(self, job: Job, playlist: dict):
        self._check_cancel(job)
        entries = [e for e in (playlist.get("entries") or []) if e]
        title = playlist.get("title") or playlist.get("id") or "Playlist"
        is_search = (playlist.get("extractor_key") or "").lower().endswith("search") \
            or job.url.startswith("ytsearch")
        if job.depth >= self.MAX_DEPTH:
            raise DownloadError("Playlist nesting too deep.")
        if not entries:
            self._finish(job, Status.SKIPPED, "Playlist is empty (or all items already downloaded)")
            return
        s = job.settings
        subdir = job.subdir
        if s.playlist_subfolder and not is_search:
            subdir = "/".join(p for p in (job.subdir, sanitize_filename(title, restricted=False)) if p)
        numbered = s.playlist_numbering and not is_search
        indices = [e.get("playlist_index") or n for n, e in enumerate(entries, 1)]
        width = max(2, len(str(max(indices))))
        children = []
        with self._lock:
            queued = {j.url for j in self.jobs if not j.is_finished}
        for idx, e in zip(indices, entries):
            url = e.get("url") or e.get("webpage_url")
            if not url or url in queued:
                continue
            queued.add(url)
            children.append(Job(
                url=url, settings=replace(s, playlist_items=""), title=e.get("title") or "",
                subdir=subdir, prefix=f"{idx:0{width}d} - " if numbered else "",
                noplaylist=True, ie_key=e.get("ie_key"), depth=job.depth + 1))
        with self._lock:
            pos = self.jobs.index(job) if job in self.jobs else len(self.jobs)
            self.jobs[pos:pos + 1] = children
            job.remove_when_done = False
            job.status = Status.DONE
        self._log("info", f"#{job.id} '{title}': queued {len(children)} item(s)")
        self.on_event("removed", job)
        for c in children:
            self.on_event("added", c)
        # the parent's `finally` will call _pump(); the parent is no longer in self.jobs

    def _stem_lock(self, stem: Optional[str]) -> threading.Lock:
        with self._lock:
            return self._stem_locks.setdefault(stem or f"\0{id(object())}", threading.Lock())

    def _claim_filename(self, ydl, ie: dict, job: Job) -> Optional[str]:
        """Give different videos that would share an output name (e.g. identical titles in a
        playlist, or titles differing only in case on Windows) distinct names by appending
        the video id. Without this, parallel jobs overwrite each other's files and later
        ones are wrongly skipped as 'already downloaded'."""
        vid = str(ie.get("id") or job.url)

        def stem():
            name = ydl.prepare_filename(dict(ie, ext="__ext__"))
            return name.rsplit(".__ext__", 1)[0].lower()

        try:
            key = stem()
        except Exception:
            return None
        with self._lock:
            owner = self._claims.setdefault(key, vid)
            if owner == vid:
                return key
            tmpl = ydl.params["outtmpl"]["default"]
            if tmpl.endswith(".%(ext)s"):
                tmpl = tmpl[: -len(".%(ext)s")] + " [%(id)s].%(ext)s"
            else:
                tmpl += " [%(id)s]"
            ydl.params["outtmpl"]["default"] = tmpl
            try:
                key = stem()
                self._claims.setdefault(key, vid)
            except Exception:
                key = None
        self._log("info", f"#{job.id} another video has the same file name; adding its id")
        return key

    # ---- hooks -----------------------------------------------------------

    def _progress_hook(self, job: Job, d: dict, state: dict):
        self._check_cancel(job)
        info = d.get("info_dict") or {}
        if d["status"] != "downloading":
            return
        # Only files we are actively writing count as ours (never a pre-existing file).
        for key in ("tmpfilename", "filename"):
            if d.get(key):
                job.temp_files.add(d[key])
        state["downloaded_any"] = True
        if not job.title and info.get("title"):
            job.title = info["title"]
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        frac = done / total if total else None
        if frac is None and d.get("fragment_count"):
            frac = (d.get("fragment_index") or 0) / d["fragment_count"]

        reqs = info.get("requested_formats") or []
        if len(reqs) > 1:
            # video and audio are downloaded one after the other: account for both
            ids = [f.get("format_id") for f in reqs]
            i = ids.index(info.get("format_id")) if info.get("format_id") in ids else 0
            parts = state.setdefault("parts", {})
            prev_total = parts.get(i, (0, None))[1]
            parts[i] = (done, total or prev_total)
            sizes = [parts[k][1] if k in parts and parts[k][1] else
                     (f.get("filesize") or f.get("filesize_approx")) for k, f in enumerate(reqs)]
            job.downloaded = int(sum(p[0] for p in parts.values()))
            if all(sizes):
                job.total = int(sum(sizes))
                job.progress = job.downloaded / job.total
            else:
                job.total = None
                job.progress = (i + (frac or 0)) / len(reqs)
            job.detail = f"Part {i + 1}/{len(reqs)}"
            heights = [f.get("height") for f in reqs if f.get("height")]
            if heights and not job.format_note:
                job.format_note = f"{max(heights)}p"
        else:
            job.total = int(total) if total else None
            job.downloaded = done
            job.progress = frac or 0.0
            job.detail = ""
            if info.get("height") and not job.format_note:
                job.format_note = f"{info['height']}p"
        if not job.format_note and job.settings.mode == "audio":
            job.format_note = job.settings.audio_format.upper()
        job.progress = min(max(job.progress, 0.0), 1.0)
        job.speed, job.eta = d.get("speed"), d.get("eta")
        job.status = Status.DOWNLOADING
        self.on_event("changed", job)

    def _pp_hook(self, job: Job, d: dict):
        if d.get("status") == "started":
            self._check_cancel(job)
            name = d.get("postprocessor") or ""
            job.status = Status.PROCESSING
            job.detail = _PP_NAMES.get(name, name)
            job.speed = job.eta = None
            job.progress = 1.0 if job.progress > 0.99 else job.progress
            self.on_event("changed", job)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _check_cancel(job: Job):
        if job.cancel_event.is_set():
            raise DownloadCancelled("Cancelled by user")

    def _finish(self, job: Job, status: Status, detail: str = ""):
        job.status, job.detail = status, detail
        job.speed = job.eta = None
        job.finished_at = time.time()
        if status == Status.DONE:
            job.progress = 1.0
        self._log("info" if status != Status.FAILED else "error",
                  f"#{job.id} {status.value}: {job.display_title}" + (f" ({detail})" if detail else ""))

    def _fail(self, job: Job, error: str):
        job.error = error
        job.hint = hint_for(error)
        self._finish(job, Status.FAILED, error.splitlines()[0][:200] if error else "Failed")

    def _log(self, level: str, msg: str):
        try:
            self.on_log(level, msg)
        except Exception:
            pass

    @staticmethod
    def _delete_partials(job: Job):
        """Remove leftovers of an unfinished download (.part, .ytdl, un-merged streams)."""
        for path in list(job.temp_files):
            for candidate in (path, path + ".part", path + ".ytdl"):
                if candidate in job.files:
                    continue
                try:
                    if os.path.isfile(candidate):
                        os.remove(candidate)
                except OSError:
                    pass
        job.temp_files.clear()
