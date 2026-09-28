"""Headless smoke tests for the Qt GUI: build every page, render cards, switch themes."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ytdown.engine import Status  # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDOWN_CONFIG_DIR", str(tmp_path / "cfg"))
    app = QApplication.instance() or QApplication([])
    from ytdown.gui.app import MainWindow
    w = MainWindow()
    w.set_setting("output_dir", str(tmp_path / "out"))
    w.manager.pause()
    w.show()
    app.processEvents()
    yield w
    w._quitting = True
    w.manager.jobs.clear()
    w.close()
    app.processEvents()


def test_jobs_render_as_cards_in_every_state(win):
    for i, st in enumerate(Status):
        job = win.manager.add(f"https://example.com/{i}", win.settings, title=f"Item {st.value}",
                              uploader="Someone", site="Youtube", duration=61)
        job.status = st
        job.progress = 0.5
        if st == Status.FAILED:
            job.error, job.hint = "[youtube] x: Sign in to confirm your age", "Use cookies"
    win._tick()
    QApplication.processEvents()
    assert win.downloads.model.rowCount() == len(Status)
    assert not win.grab().isNull()
    win.downloads.proxy.set_mode("failed")
    assert win.downloads.proxy.rowCount() == 2  # failed + cancelled
    win.downloads.proxy.set_mode("all")


def test_pages_and_themes(win):
    for key in ("settings", "activity", "about", "downloads"):
        win.go(key)
        QApplication.processEvents()
        assert not win.grab().isNull()
    for mode in ("light", "dark", "system"):
        win.set_setting("theme", mode)
        QApplication.processEvents()


def test_settings_propagate(win):
    win.set_setting("max_concurrent", 7)
    assert win.manager.max_concurrent == 7
    win.set_setting("mode", "audio")
    assert win.downloads.fmt.currentData() == win.settings.audio_format
    win.set_setting("mode", "video")
    assert win.downloads.fmt.currentData() == win.settings.video_container


def test_add_text_queues_links_and_searches(win):
    assert win.add_text("see https://example.com/a and https://example.com/b\nsome song")
    urls = [j.url for j in win.manager.jobs]
    assert urls == ["https://example.com/a", "https://example.com/b", "ytsearch1:some song"]
    assert not win.add_text("   ")


def test_queue_is_saved_and_restored(win, tmp_path):
    win.add_text("https://example.com/keep-me")
    win._save_queue()
    from ytdown.gui.app import MainWindow
    other = MainWindow()
    try:
        assert [j.url for j in other.manager.jobs] == ["https://example.com/keep-me"]
        assert other.manager.paused and other.downloads.restore_bar.isVisibleTo(other)
    finally:
        other._quitting = True
        other.manager.jobs.clear()
        other.close()
