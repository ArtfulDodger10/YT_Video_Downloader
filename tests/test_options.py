import itertools
from pathlib import Path

import pytest
import yt_dlp

from ytdown.deps import Environment
from ytdown.options import (build_args, clean_error, extract_targets, hint_for,
                            validate_extra_args)
from ytdown.settings import (AUDIO_FORMATS, SPONSORBLOCK_MODES, VIDEO_CODECS, VIDEO_CONTAINERS,
                             VIDEO_QUALITIES, Settings)

FFMPEG_DIR = str(Path("tools"))  # platform-neutral fake location
ENV = Environment(ytdlp_version="x", ffmpeg=str(Path("tools") / "ffmpeg.exe"), js_runtimes={"node": "node"},
                  has_ejs=True)


def opts(s, **kw):
    return yt_dlp.parse_options(build_args(s, ENV, **kw)).ydl_opts


def flag_value(args, flag):
    return args[args.index(flag) + 1]


@pytest.mark.parametrize("quality,container,codec", list(itertools.product(
    [v for v, _ in VIDEO_QUALITIES], [v for v, _ in VIDEO_CONTAINERS], [v for v, _ in VIDEO_CODECS])))
def test_every_video_combination_is_valid_for_ytdlp(tmp_path, quality, container, codec):
    s = Settings(output_dir=str(tmp_path), video_quality=quality, video_container=container,
                 video_codec=codec, subtitles=True, sponsorblock="remove")
    o = opts(s)
    assert o["format"] == "bv*+ba/b"
    if container != "original":
        assert o["merge_output_format"] == container


@pytest.mark.parametrize("fmt,sb", list(itertools.product(
    [v for v, _ in AUDIO_FORMATS], [v for v, _ in SPONSORBLOCK_MODES])))
def test_every_audio_combination_is_valid_for_ytdlp(tmp_path, fmt, sb):
    s = Settings(output_dir=str(tmp_path), mode="audio", audio_format=fmt, sponsorblock=sb)
    o = opts(s)
    keys = [pp["key"] for pp in o["postprocessors"]]
    assert "FFmpegExtractAudio" in keys
    if fmt in ("webm", "wav", "original"):
        assert "EmbedThumbnail" not in keys


def test_compatible_1080_prefers_h264_aac(tmp_path):
    a = build_args(Settings(output_dir=str(tmp_path), video_quality="1080"), ENV)
    assert flag_value(a, "-S") == "res:1080,vcodec:h264,acodec:aac"


def test_webm_prefers_vp9_opus_and_best_has_no_codec_bias(tmp_path):
    a = build_args(Settings(output_dir=str(tmp_path), video_container="webm"), ENV)
    assert flag_value(a, "-S") == "vcodec:vp9,acodec:opus"
    a = build_args(Settings(output_dir=str(tmp_path), video_codec="best"), ENV)
    assert "-S" not in a


def test_output_template_escapes_prefix_and_subdir(tmp_path):
    s = Settings(output_dir=str(tmp_path))
    o = opts(s, subdir="100% Hits", prefix="01 - ")
    assert o["outtmpl"]["default"] == "100%% Hits/01 - %(title)s.%(ext)s"
    assert o["paths"]["home"] == str(tmp_path)


def test_empty_template_falls_back(tmp_path):
    o = opts(Settings(output_dir=str(tmp_path), filename_template="  "))
    assert o["outtmpl"]["default"] == "%(title)s.%(ext)s"


def test_network_and_tool_flags(tmp_path):
    s = Settings(output_dir=str(tmp_path), fragments=8, rate_limit="2M", proxy="socks5://h:1",
                 cookies_browser="firefox", system_certs=True, use_archive=True)
    o = opts(s, archive_path=str(tmp_path / "a.txt"))
    assert o["concurrent_fragment_downloads"] == 8
    assert o["ratelimit"] == 2 * 1024 * 1024
    assert o["proxy"] == "socks5://h:1"
    assert o["cookiesfrombrowser"][0] == "firefox"
    assert "no-certifi" in o["compat_opts"]
    assert o["download_archive"] == str(tmp_path / "a.txt")
    assert o["ffmpeg_location"] == FFMPEG_DIR
    assert "node" in o["js_runtimes"]


def test_cookie_file_wins_over_browser(tmp_path):
    s = Settings(output_dir=str(tmp_path), cookies_browser="chrome", cookies_file="c.txt")
    o = opts(s)
    assert o["cookiefile"] == "c.txt"
    assert not o.get("cookiesfrombrowser")


def test_playlist_flags(tmp_path):
    assert opts(Settings(output_dir=str(tmp_path)))["noplaylist"] is True
    assert opts(Settings(output_dir=str(tmp_path), download_playlist=True))["noplaylist"] is False
    assert opts(Settings(output_dir=str(tmp_path), playlist_items="1-3,7"))["playlist_items"] == "1-3,7"


def test_extra_args_are_appended(tmp_path):
    o = opts(Settings(output_dir=str(tmp_path), extra_args='--match-filter "duration < 600"'))
    assert o["match_filter"] is not None


def test_validate_extra_args():
    assert validate_extra_args("") is None
    assert validate_extra_args("--limit-rate 3M") is None
    assert validate_extra_args("--definitely-not-an-option")
    assert validate_extra_args('"unclosed')
    assert "URL" in validate_extra_args("https://example.com/v")


def test_extract_targets():
    text = """
    look at https://youtu.be/abc123?si=x, and (https://vimeo.com/42).
    https://youtu.be/abc123?si=x
    lofi hip hop
    ytsearch5:cats
    """
    assert extract_targets(text) == [
        "https://youtu.be/abc123?si=x", "https://vimeo.com/42",
        "ytsearch1:lofi hip hop", "ytsearch5:cats"]
    assert extract_targets("   \n  ") == []


@pytest.mark.parametrize("msg,needle", [
    ("ERROR: [youtube] x: Sign in to confirm you're not a bot", "Cookies"),
    ("Unable to download API page: [SSL: CERTIFICATE_VERIFY_FAILED]", "certificate"),
    ("HTTP Error 429: Too Many Requests", "Rate-limited"),
    ("ffmpeg not found. Please install", "ffmpeg"),
    ("Requested format is not available", "Best available"),
    ("Some unknown failure", ""),
])
def test_hints(msg, needle):
    h = hint_for(msg)
    assert (needle in h) if needle else h == ""


def test_clean_error():
    raw = ("\x1b[0;31mERROR:\x1b[0m [youtube] x: Unable to download; please report this issue on  "
           "https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the template")
    assert clean_error(raw) == "[youtube] x: Unable to download"


@pytest.mark.parametrize("w,h,label", [
    (1920, 1080, "1080p"), (1920, 872, "1080p"), (1080, 1920, "1080p"), (2560, 1080, "1080p"),
    (3840, 1600, "2160p"), (640, 480, "480p"), (1440, 1080, "1080p"), (None, 360, "360p"),
    (176, 144, "144p"),
])
def test_quality_label(w, h, label):
    from ytdown.engine import quality_label
    assert quality_label(w, h) == label
