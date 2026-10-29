import hashlib
import io
import tarfile
from threading import Event

import httpx
import pytest

from lingualoop.local_speech.catalog import Artifact, ModelPackage, load_catalog
from lingualoop.local_speech.downloads import DownloadCancelled, ModelStore, package_lock


def package(content=b"model", **artifact_overrides):
    artifact = Artifact(
        path="model.onnx",
        url="https://models.example/model",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        **artifact_overrides,
    )
    return ModelPackage(
        id="test-model",
        revision="v1",
        name="test",
        task="stt",
        languages=["ja"],
        scenarios=["conversation"],
        streaming="batch",
        license_note="test",
        sources=["https://models.example"],
        adapter="sensevoice",
        files=[artifact],
        required_files=["model.onnx"],
        notes="test",
    )


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_catalog_pins_all_downloads_and_does_not_offer_japanese_kokoro():
    catalog = load_catalog()
    assert len(catalog) >= 8
    for item in catalog:
        if item.files:
            assert item.adapter != "candidate"
            assert all(len(f.sha256) == 64 and f.size > 0 for f in item.files)
    assert "ja" not in next(p for p in catalog if p.id == "kokoro-int8-zhen-v11").languages
    assert next(p for p in catalog if p.id == "voicevox-japanese").files == []


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "C:/evil",
        "bad\\path",
        "a/../b",
        "",
        "root/NUL",
        "root/CON.txt",
        "root/file. ",
    ],
)
def test_manifest_paths_reject_escape(name):
    with pytest.raises(ValueError):
        Artifact(path=name, url="https://models.example/x", size=1, sha256="0" * 64)


def test_install_resume_verify_uninstall_and_preserve_other_versions(tmp_path):
    store, model = ModelStore(tmp_path), package()
    part = tmp_path / "downloads" / (model.files[0].sha256 + ".part")
    part.parent.mkdir()
    part.write_bytes(b"mo")

    def handler(request):
        assert request.headers["Range"] == "bytes=2-"
        return httpx.Response(206, headers={"Content-Range": "bytes 2-4/5"}, content=b"del")

    with client(handler) as transport:
        path = store.install(model, client=transport)
    assert (path / "model.onnx").read_bytes() == b"model"
    assert store.installed(model)
    assert store.verify(model)
    sibling = path.parent / "old-version"
    sibling.mkdir()
    (sibling / "keep").write_text("previous version")
    (path / "model.onnx").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="损坏"):
        store.verify(model)
    store.uninstall(model)
    assert (sibling / "keep").exists()
    assert not store.installed(model)


def test_server_ignoring_range_restarts_safely(tmp_path):
    store, model = ModelStore(tmp_path), package()
    blob = tmp_path / "downloads" / (model.files[0].sha256 + ".part")
    blob.parent.mkdir()
    blob.write_bytes(b"mo")
    with client(lambda _: httpx.Response(200, content=b"model")) as transport:
        store.install(model, client=transport)
    assert store.verify(model)


@pytest.mark.parametrize(
    "headers,body",
    [({"Content-Range": "bytes 1-4/5"}, b"odel"), ({"Content-Range": "bytes 2-4/9"}, b"del")],
)
def test_bad_range_is_not_appended(tmp_path, headers, body):
    store, model = ModelStore(tmp_path), package()
    part = tmp_path / "downloads" / (model.files[0].sha256 + ".part")
    part.parent.mkdir()
    part.write_bytes(b"mo")
    with client(lambda _: httpx.Response(206, headers=headers, content=body)) as transport:
        with pytest.raises(ValueError, match="续传范围"):
            store.install(model, client=transport)
    assert part.read_bytes() == b"mo"
    assert not store.installed(model)


def test_corrupt_download_is_discarded(tmp_path):
    store, model = ModelStore(tmp_path), package()
    with client(lambda _: httpx.Response(200, content=b"wrong")) as transport:
        with pytest.raises(ValueError, match="校验失败"):
            store.install(model, client=transport)
    assert not list((tmp_path / "downloads").glob("*.part"))
    assert not store.installed(model)


def test_cancel_and_package_lock_prevent_partial_install(tmp_path):
    store, model, cancel = ModelStore(tmp_path), package(), Event()

    def progress(*_):
        cancel.set()

    with client(lambda _: httpx.Response(200, content=b"model")) as transport:
        with pytest.raises(DownloadCancelled):
            store.install(model, client=transport, cancel=cancel, progress=progress)
    assert not store.installed(model)
    with package_lock(tmp_path, model):
        with pytest.raises(RuntimeError, match="正在"):
            store.uninstall(model)


@pytest.mark.parametrize(
    "member_name,kind",
    [
        ("root/../escape", "file"),
        ("root/link", "symlink"),
        ("other/evil", "file"),
        ("root/huge", "huge"),
    ],
)
def test_archive_rejects_escape_links_and_expansion(tmp_path, member_name, kind):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:bz2") as archive:
        member = tarfile.TarInfo(member_name)
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "outside"
            archive.addfile(member)
        else:
            data = b"x" * (100 if kind == "huge" else 1)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    model = package(output.getvalue(), archive_root="root", unpacked_limit=10)
    with client(lambda _: httpx.Response(200, content=output.getvalue())) as transport:
        with pytest.raises(ValueError):
            ModelStore(tmp_path).install(model, client=transport)
    assert not list((tmp_path / "staging").iterdir())
