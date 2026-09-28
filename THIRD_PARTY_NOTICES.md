# Third-party notices

YTDown's own code is MIT-licensed (see `LICENSE`). The Windows release bundles the
components below; each remains under its own license. Source code for every component
is available at the links given.

| Component | License | Source |
|---|---|---|
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| yt-dlp-ejs | Unlicense, MIT, ISC | https://github.com/yt-dlp/ejs |
| Qt 6 / PySide6 / Shiboken6 | LGPL-3.0 | https://code.qt.io/ · https://pypi.org/project/PySide6-Essentials/ |
| mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| requests | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | MIT | https://github.com/urllib3/urllib3 |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| charset-normalizer | MIT | https://github.com/jawah/charset_normalizer |
| pycryptodomex | BSD-2-Clause / Public Domain | https://github.com/Legrandin/pycryptodome |
| brotli | MIT | https://github.com/google/brotli |
| Python | PSF License | https://www.python.org/ |
| FFmpeg (only if bundled) | LGPL-2.1-or-later build | https://github.com/BtbN/FFmpeg-Builds · https://ffmpeg.org/ |

Notes

- **Qt / PySide6** are used as unmodified, dynamically loaded libraries (the `.dll` files in
  the release folder), which you may replace with your own builds as permitted by the LGPL.
- **mutagen** (used by yt-dlp to embed cover art and metadata) is GPL-licensed. Its complete
  source is available at the link above.
- **FFmpeg**: release zips include the *LGPL* build from BtbN/FFmpeg-Builds as separate
  `ffmpeg.exe`/`ffprobe.exe` programs, unmodified. Corresponding source is linked above.
- No component above is modified by this project.
