# YTDown

A fast, no-nonsense video & audio downloader for Windows (also runs on macOS/Linux).
Paste links, press **Download**, done. Works with YouTube and the 1000+ other sites
supported by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

No ads, no accounts, no browser extensions.

## Features

- **Download queue** with several downloads at once (configurable), live progress, speed, ETA and size
- **Playlists & channels**: split into separate items that download in parallel, saved to their own
  numbered folder; pick a range like `1-10,15`
- **Paste anything**: several links at once, links inside text, or plain words to search YouTube
- **Video**: Best / 4K / 1440p / 1080p / 720p … as MP4, MKV or WEBM, with either
  *Compatible* (H.264/AAC, plays everywhere) or *Best quality* (AV1/VP9) codecs
- **Audio**: MP3, M4A, OPUS, FLAC, WAV or the original stream, with a bitrate choice
- **Extras**: thumbnail as cover art, metadata, chapters, subtitles (embedded or .srt),
  SponsorBlock (mark or cut sponsor segments)
- **Reliable**: cancel, retry and resume; partial files are cleaned up on removal; unfinished
  downloads survive closing the app; duplicate links and same-named files are handled safely
- **Access**: cookies from your browser or a cookies.txt (age-restricted / members-only videos),
  proxy, speed limit, optional aria2c, and a fix for antivirus/corporate-proxy HTTPS scanning
- **Skip what you already have**: optional download history, handy for re-syncing a playlist
- **Clipboard watch** (optional): copied links are added automatically
- Dark and light themes, clear error messages with a suggested fix, full log
- **Command line** too: `ytdown URL...` uses the same engine and your saved settings

## Install

### Option A: ready-made app (no Python needed)
Build it once with `.\build.ps1` (see *Building*) and copy `dist\YTDown\` anywhere. Run `YTDown.exe`.

### Option B: from source
Requires **Python 3.10+**.

```bash
git clone https://github.com/ArtfulDodger10/YT_Video_Downloader
cd YT_Video_Downloader
pip install -r requirements.txt
python -m ytdown
```

Or double-click `YTDown.pyw`.

### Recommended tools
| Tool | Why | Install (Windows) |
|---|---|---|
| **ffmpeg** | merging HD video + audio, audio conversion, embedding | `winget install Gyan.FFmpeg` |
| **Deno** or **Node.js** | YouTube needs a JavaScript runtime or only low-quality formats appear | `winget install DenoLand.Deno` |
| aria2c *(optional)* | multi-connection downloads for slow direct-file hosts | `winget install aria2.aria2` |

The app also finds `ffmpeg.exe`/`ffprobe.exe` placed next to it (or in an `ffmpeg\bin` folder),
so you can ship a fully portable folder. The **About** tab shows what was detected.

## Usage

**GUI**: paste links (one per line) and press **Enter** or **Download**. Shift+Enter adds a new line.
Double-click a finished item to play it, right-click for more actions. Settings save automatically.

**Command line** (unspecified options use your saved GUI settings):

```bash
python -m ytdown "https://youtu.be/..."                 # video, saved settings
python -m ytdown -a -f mp3 URL1 URL2                     # audio as MP3
python -m ytdown -q 1080 -f mkv -o D:\Videos URL         # 1080p MKV into D:\Videos
python -m ytdown -I 1-20 -j 4 "https://youtube.com/playlist?list=..."
python -m ytdown "ytsearch3:lofi hip hop"                # top 3 search results
```

`YTDown.exe` accepts the same arguments (without console output; exit code 0 means success).

## Troubleshooting

Failed items show the error and a **Tip** under the list. The usual ones:

- *"Sign in to confirm you're not a bot" / age-restricted*: Settings > Network > **Cookies from browser**
  (Firefox is most reliable; close Chrome/Edge completely first) or pick a `cookies.txt` file.
- *"certificate verify failed"*: keep **Use the system certificate store** enabled (default on Windows).
- *Only 360p available on YouTube*: install Deno or Node.js, then **About > Re-check tools**.
- *Sites change all the time*: **About > Update yt-dlp** (source installs), or rebuild the exe.

## Building

```powershell
.\build.ps1                                   # dist\YTDown\YTDown.exe  (fast start)
.\build.ps1 -OneFile                          # dist\YTDown.exe         (single file)
.\build.ps1 -WithFfmpeg C:\ffmpeg\bin         # also bundle ffmpeg + ffprobe
```

## Development

```bash
pip install -e .[dev]
pytest            # offline tests: option building, settings, and a real download engine
                  # run against a local HTTP server (needs ffmpeg for the media tests)
```

Layout: `ytdown/engine.py` (queue + yt-dlp workers), `ytdown/options.py` (settings to yt-dlp
arguments), `ytdown/settings.py`, `ytdown/deps.py` (tool detection), `ytdown/cli.py`,
`ytdown/gui/app.py`.

## Legal

Only download content you own or have permission to download, and respect each site's terms.

## Author

[ArtfulDodger10](https://github.com/ArtfulDodger10)
