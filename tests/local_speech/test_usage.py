import os
from types import SimpleNamespace

from shinar.local_speech.usage import cached_model_bytes, storage_usage


def test_storage_snapshot_counts_copies_but_not_hard_links_or_external_links(tmp_path):
    root = tmp_path / "speech"
    for name in ("models", "downloads", "runtimes"):
        (root / name).mkdir(parents=True)
    (root / "models/model.onnx").write_bytes(b"m" * 1024**2)
    source = root / "downloads/wheel"
    source.write_bytes(b"w" * 2 * 1024**2)
    os.link(source, root / "runtimes/wheel")
    (root / "report.json").write_bytes(b"x" * 1024**2)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "not-ours").write_bytes(b"z" * 1024**2)
    try:
        (root / "external").symlink_to(outside, target_is_directory=True)
    except OSError:
        pass  # Creating Windows symlinks can require Developer Mode.
    usage = storage_usage(root)
    assert usage == {"installedMiB": 3.0, "cacheMiB": 0.0, "otherMiB": 1.0,
                     "totalMiB": 4.0, "incomplete": False}
    assert storage_usage(tmp_path / "missing")["totalMiB"] == 0.0
    assert not storage_usage(tmp_path / "missing")["incomplete"]


def test_model_cache_includes_retained_partials_and_deduplicates_assets(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads/same").write_bytes(b"model")
    (tmp_path / "downloads/next.part").write_bytes(b"part")
    assets = [SimpleNamespace(sha256=name) for name in ("same", "same", "next", "absent")]
    assert cached_model_bytes(tmp_path, assets) == 9
