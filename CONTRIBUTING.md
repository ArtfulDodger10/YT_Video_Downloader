# Contributing

Thanks for helping improve YTDown! Bug reports, ideas and pull requests are all welcome.

## Reporting bugs

Use the **Bug report** issue form. The most useful things to include:

- the app version (sidebar, or *About*) and your OS,
- the link that fails, if you can share it,
- the error shown on the card, and the relevant lines from the **Activity** page.

Many download failures come from the site itself changing. Before reporting, try
**About > Update yt-dlp** (or the latest release). If plain `yt-dlp` fails the same way,
please report it to [yt-dlp](https://github.com/yt-dlp/yt-dlp/issues) instead.

## Development setup

```bash
git clone https://github.com/ArtfulDodger10/YT_Video_Downloader
cd YT_Video_Downloader
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e .[dev]
python -m ytdown                  # run the app
```

## Checks

```bash
ruff check .                      # lint
pytest                            # tests (offline; media tests need ffmpeg)
```

Both run in CI on every pull request, on Windows and Linux.

## Code layout

| Path | What it does |
|---|---|
| `ytdown/engine.py` | Download queue and workers driving yt-dlp in-process |
| `ytdown/options.py` | Settings → yt-dlp arguments, link parsing, error hints |
| `ytdown/probe.py` | Link preview (title, thumbnail, qualities, playlist size) |
| `ytdown/settings.py` | Settings dataclass and persistence |
| `ytdown/deps.py` | Detection of ffmpeg, JS runtimes and aria2c |
| `ytdown/cli.py` | Command-line front end |
| `ytdown/gui/` | Qt interface (`app.py` main window, one module per page) |

Guidelines:

- Worker threads must never touch widgets; they report through the manager's events.
- New settings go in `Settings` (with a sensible default) and are translated to yt-dlp
  arguments in `options.build_args`; add a test in `tests/test_options.py`.
- Keep the UI text short and plain; explain *what to do*, not internals.

## Releases

Maintainers bump `ytdown/__init__.py:__version__`, add a `CHANGELOG.md` entry and push a tag
like `v2.1.0`. GitHub Actions builds the Windows zip and publishes the release.
