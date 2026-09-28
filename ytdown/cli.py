"""Command-line front end sharing the GUI's engine and saved settings."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from . import __version__
from .deps import detect
from .engine import DownloadManager, Status
from .options import extract_targets
from .settings import (AUDIO_FORMATS, BROWSERS, VIDEO_CONTAINERS, VIDEO_QUALITIES, Settings,
                       config_dir)
from .util import ensure_std_streams, human_bytes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytdown", description="Download video/audio from YouTube and 1000+ sites. "
        "Run without arguments to open the GUI. Unspecified options use your saved GUI settings.")
    p.add_argument("targets", nargs="*", help="URLs or search terms")
    p.add_argument("-a", "--audio", action="store_true", help="audio only")
    p.add_argument("-q", "--quality", choices=[v for v, _ in VIDEO_QUALITIES])
    p.add_argument("-f", "--format", help="container ({}) or audio format ({})".format(
        "/".join(v for v, _ in VIDEO_CONTAINERS), "/".join(v for v, _ in AUDIO_FORMATS)))
    p.add_argument("-o", "--output", help="download folder")
    p.add_argument("-j", "--jobs", type=int, help="simultaneous downloads")
    p.add_argument("-p", "--playlist", action="store_true",
                   help="download the whole playlist when a video URL is part of one")
    p.add_argument("-I", "--items", help="playlist items, e.g. 1-5,8,10-")
    p.add_argument("--cookies-from-browser", choices=[v for v, _ in BROWSERS if v])
    p.add_argument("--gui", action="store_true", help="open the GUI (and queue any given links)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None) -> int:
    ensure_std_streams()
    args = build_parser().parse_args(argv)
    if args.gui or not args.targets:
        from .gui.app import main as gui_main
        gui_main()
        return 0

    s = Settings.load()
    if args.audio:
        s.mode = "audio"
    if args.format:
        if s.mode == "audio" and args.format in {v for v, _ in AUDIO_FORMATS}:
            s.audio_format = args.format
        elif s.mode == "video" and args.format in {v for v, _ in VIDEO_CONTAINERS}:
            s.video_container = args.format
        else:
            print(f"error: format '{args.format}' is not valid for {s.mode} mode", file=sys.stderr)
            return 2
    if args.quality:
        s.video_quality = args.quality
    if args.output:
        s.output_dir = args.output
    if args.playlist:
        s.download_playlist = True
    if args.items:
        s.playlist_items = args.items
    if args.cookies_from_browser:
        s = replace(s, cookies_browser=args.cookies_from_browser, cookies_file="")

    env = detect()
    for problem in env.problems():
        print("warning:", problem, file=sys.stderr)

    def on_log(level, msg):
        if level in ("warning", "error"):
            print(f"\r\x1b[K{level}: {msg}", file=sys.stderr)

    mgr = DownloadManager(env, on_log=on_log, archive_path=str(config_dir() / "archive.txt"),
                          max_concurrent=args.jobs or s.max_concurrent)
    for t in extract_targets("\n".join(args.targets)):
        mgr.add(t, s)

    reported = set()
    try:
        while not mgr.wait(timeout=0.5):
            _print_status(mgr, reported)
        _print_status(mgr, reported)
    except KeyboardInterrupt:
        print("\nCancelling…", file=sys.stderr)
        mgr.shutdown()
        return 130

    failed = [j for j in mgr.jobs if j.status == Status.FAILED]
    return 1 if failed else 0


def _print_status(mgr: DownloadManager, reported: set):
    for j in list(mgr.jobs):
        if j.is_finished and j.id not in reported:
            reported.add(j.id)
            line = f"[{j.status.value}] {j.display_title}"
            if j.files:
                line += f"  ->  {j.files[-1]}"
            if j.status == Status.FAILED:
                line += f"\n    {j.error}" + (f"\n    hint: {j.hint}" if j.hint else "")
            print(f"\r\x1b[K{line}")
    active = [j for j in mgr.jobs if j.is_active]
    if active and sys.stdout.isatty():
        st = mgr.stats()
        parts = [f"{j.progress * 100:5.1f}% {j.display_title[:30]}" for j in active[:3]]
        sys.stdout.write(f"\r\x1b[K{st['active']} active, {st['queued']} queued | "
                         f"{human_bytes(st['speed'])}/s | " + " | ".join(parts))
        sys.stdout.flush()
