# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-09-28

A complete rewrite of the original single-script downloader.

### Added
- Modern Qt interface: sidebar navigation, download cards with thumbnails, animated progress,
  dark / light / system themes, toasts, empty states and hover actions.
- **Link preview** before downloading: thumbnail, title, channel, duration and the qualities
  that are actually available, as one-click chips. The preview's info is reused for the
  download, so it starts immediately.
- **Download queue** with configurable parallel downloads, pause / resume, cancel, retry
  (resuming partial files), "retry all failed", filters (All / Active / Completed / Failed).
- **Playlists and channels** split into separate items that download in parallel into a
  numbered subfolder, with an item range (`1-10,15`).
- Paste or drop many links at once; plain text searches YouTube; clipboard watching.
- Video in any available resolution (up to 4K/8K) as MP4/MKV/WEBM with a *Compatible* (H.264/AAC) or *Best* (AV1/VP9) codec
  preference; audio as MP3/M4A/OPUS/FLAC/WAV or the original stream.
- Embedding of thumbnails, metadata, chapters and subtitles; SponsorBlock mark / remove.
- Cookies from the browser or a cookies.txt, proxy, speed limit, retries, aria2c support,
  and the system certificate store (fixes antivirus / corporate HTTPS interception).
- Download history to skip videos you already have.
- Tray icon with notifications, optional background mode, single-instance handling
  (`YTDown.exe --gui URL` adds to the running window).
- Unfinished downloads are restored after closing the app.
- Clear error messages with a suggested fix; full Activity log.
- About page with tool detection and one-click install of ffmpeg / Deno via winget,
  in-app yt-dlp updater (source installs) and an update check for new releases.
- Command-line interface sharing the same engine and settings.
- Portable mode (`portable_data` folder next to the app) and `YTDOWN_CONFIG_DIR`.
- Windows builds via PyInstaller, GitHub Actions CI and release automation, offline test suite.

### Fixed (compared with 1.x)
- The window froze with no progress while downloading.
- Only one download at a time and no way to cancel.
- Playlists could not be downloaded.
- YouTube downloads limited to low quality (no JavaScript runtime support).
- "Best" MP4s that did not play on many devices (AV1/Opus inside MP4).
- Failures behind antivirus HTTPS scanning (`CERTIFICATE_VERIFY_FAILED`).
- Two videos whose titles differ only by letter case overwrote each other on Windows.
- The same video queued twice raced on one file.
- Occasional YouTube "HTTP Error 403" failures (now retried automatically with fresh info).

## [1.0.0]
- Initial Tkinter script: single URL, MP4/MP3, fixed quality presets.
