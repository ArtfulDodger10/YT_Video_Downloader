import json

from ytdown.settings import Settings


def test_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    s = Settings(output_dir=str(tmp_path), mode="audio", audio_format="flac", max_concurrent=5)
    s.save(path)
    assert Settings.load(path) == s


def test_bad_values_are_ignored_and_ranges_clamped(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "output_dir": str(tmp_path), "mode": "hologram", "max_concurrent": 999,
        "fragments": 0, "embed_thumbnail": "yes", "retries": True, "unknown_key": 1,
        "video_quality": "1080",
    }))
    s = Settings.load(path)
    assert s.mode == "video"
    assert s.max_concurrent == 10
    assert s.fragments == 1
    assert s.embed_thumbnail is True
    assert s.retries == 10
    assert s.video_quality == "1080"


def test_corrupt_or_wrong_type_file_gives_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    assert Settings.load(path).mode == "video"
    path.write_text("[1, 2, 3]")
    assert Settings.load(path).mode == "video"
    assert Settings.load(tmp_path / "missing.json").output_dir
