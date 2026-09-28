"""End-to-end engine tests against a local HTTP server (no internet needed)."""

import functools
import http.server
import os
import subprocess
import threading
import time

import pytest

from ytdown.deps import detect
from ytdown.engine import DownloadManager, Status
from ytdown.settings import Settings

ENV = detect()
needs_ffmpeg = pytest.mark.skipif(not ENV.ffmpeg, reason="ffmpeg not installed")


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static files; /slow/* is throttled so cancellation and concurrency can be observed."""

    def log_message(self, *a):
        pass

    def copyfile(self, source, outputfile):
        if "/slow/" not in self.path:
            return super().copyfile(source, outputfile)
        while chunk := source.read(16 * 1024):
            try:
                outputfile.write(chunk)
            except OSError:
                return
            time.sleep(0.05)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("www")
    (root / "slow").mkdir()
    if ENV.ffmpeg:
        subprocess.run([ENV.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / "clip.mp4")],
                       check=True)
    for i in range(4):
        (root / "slow" / f"big{i}.mp4").write_bytes(os.urandom(3 * 1024 * 1024))
    handler = functools.partial(_Handler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.root = root
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield httpd
    httpd.shutdown()


def settings(tmp_path, **kw):
    base = dict(output_dir=str(tmp_path), video_container="original", embed_thumbnail=False,
                embed_metadata=False, embed_chapters=False, retries=0)
    base.update(kw)
    return Settings(**base)


def wait_for(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


@needs_ffmpeg
def test_video_download(server, tmp_path):
    m = DownloadManager(ENV)
    job = m.add(f"{server.url}/clip.mp4", settings(tmp_path))
    assert m.wait(60)
    assert job.status == Status.DONE, job.error
    assert os.path.getsize(job.files[-1]) > 1000
    assert job.progress == 1.0
    assert job.total == os.path.getsize(job.files[-1])


@needs_ffmpeg
def test_audio_conversion(server, tmp_path):
    m = DownloadManager(ENV)
    job = m.add(f"{server.url}/clip.mp4", settings(tmp_path, mode="audio", audio_format="mp3"))
    assert m.wait(60)
    assert job.status == Status.DONE, job.error
    assert job.files[-1].endswith(".mp3") and os.path.exists(job.files[-1])


@needs_ffmpeg
def test_second_download_is_reported_as_already_downloaded(server, tmp_path):
    m = DownloadManager(ENV)
    m.add(f"{server.url}/clip.mp4", settings(tmp_path))
    m.wait(60)
    again = m.add(f"{server.url}/clip.mp4", settings(tmp_path))
    m.wait(60)
    assert again.status == Status.DONE and again.detail == "Already downloaded"


def test_duplicate_url_is_not_queued_twice(server, tmp_path):
    m = DownloadManager(ENV)
    m.pause()
    assert m.add(f"{server.url}/x.mp4", settings(tmp_path))
    assert m.add(f"{server.url}/x.mp4", settings(tmp_path)) is None


def test_missing_file_fails_then_retry_succeeds(server, tmp_path):
    m = DownloadManager(ENV)
    job = m.add(f"{server.url}/later.mp4", settings(tmp_path))
    m.wait(60)
    assert job.status == Status.FAILED
    assert "404" in job.error

    (server.root / "later.mp4").write_bytes(os.urandom(50_000))  # the file appears...
    m.retry(job)  # ...and the same job is retried
    m.wait(60)
    assert job.status == Status.DONE, job.error


def test_cancel_then_remove_deletes_partial_files(server, tmp_path):
    m = DownloadManager(ENV)
    job = m.add(f"{server.url}/slow/big0.mp4", settings(tmp_path))
    assert wait_for(lambda: job.status == Status.DOWNLOADING and job.downloaded > 0)
    m.cancel(job)
    assert wait_for(lambda: job.status == Status.CANCELLED)
    leftovers = [p for p in os.listdir(tmp_path)]
    assert leftovers, "partial file should be kept so the download can resume"
    m.remove(job)
    assert os.listdir(tmp_path) == []
    assert job not in m.jobs


def test_concurrency_limit_and_pause(server, tmp_path):
    m = DownloadManager(ENV, max_concurrent=2)
    m.pause()
    jobs = [m.add(f"{server.url}/slow/big{i}.mp4", settings(tmp_path)) for i in range(4)]
    time.sleep(0.3)
    assert all(j.status == Status.QUEUED for j in jobs)
    m.resume()
    peak = 0
    end = time.time() + 20
    while time.time() < end and not all(j.is_finished for j in jobs):
        peak = max(peak, sum(j.is_active for j in jobs))
        if sum(j.status == Status.DOWNLOADING for j in jobs) == 2:
            break
        time.sleep(0.02)
    assert peak <= 2
    assert sum(j.status == Status.QUEUED for j in jobs) >= 2
    m.shutdown(timeout=10)
    assert all(not j.is_active for j in jobs)


def test_queue_snapshot_roundtrip(tmp_path):
    from ytdown.engine import Job
    m = DownloadManager(ENV)
    m.pause()
    m.add("https://example.com/a", settings(tmp_path, mode="audio"), subdir="List", prefix="01 - ")
    snap = m.pending_snapshot()
    restored = Job.from_dict(snap[0])
    assert restored.settings.mode == "audio"
    assert (restored.subdir, restored.prefix) == ("List", "01 - ")
