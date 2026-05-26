# YT.DOWN

A simple video downloader with a GUI. Paste a URL, pick a folder, and click download. No browser extensions, no ads, no accounts.
Built with Python + yt-dlp.

---

## Before you run it

You need these two installed:

```bash
pip install yt-dlp
```

And **ffmpeg** — grab it from [ffmpeg.org](https://ffmpeg.org/download.html) and make sure it's on your PATH. If it's not, the app will tell you when it opens.

---

## Running it

```bash
python downloader_gui.py
```

A window opens. Paste your URL, choose where to save, hit Download.

---

## What it can do

- Download video as MP4
- Download audio only as MP3
- Pick quality (best, 1080p, 720p, 480p, 360p)
- Works with YouTube, Vimeo, Twitter, TikTok, and a lot more — basically anything yt-dlp supports
- "List available formats" button if you're curious what's there before downloading

---

## Requirements

- Python 3.9 or higher
- yt-dlp
- ffmpeg

---

## Author

[ArtfulDodger10](https://github.com/ArtfulDodger10)
