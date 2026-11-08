import importlib.util
from pathlib import Path

import httpx
import pytest


def script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_stream_reader_enforces_transfer_limit():
    module = script("prepare_speech_evaluation")
    response = httpx.Response(200, content=b"abcdefghij")
    reader = module.BoundedReader(response, limit=4)
    with pytest.raises(ValueError, match="limit"):
        reader.read(5)


def test_complete_process_exit_cannot_hide_missing_or_duplicated_corpus(tmp_path):
    import json

    module = script("evaluate_local_speech")
    request = {
        "model": {"id": "m", "language": "ja"},
        "items": [{"id": "a"}, {"id": "b"}],
        "repeats": 1,
    }
    report = {
        "schema": "strict-speech-evaluation-v1",
        "model": request["model"],
        "rows": [{"item_id": "a", "repeat": 0}, {"item_id": "a", "repeat": 0}],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        module.validate_report(path, request)
    report["rows"][1]["item_id"] = "b"
    path.write_text(json.dumps(report), encoding="utf-8")
    module.validate_report(path, request)


def test_range_download_resumes_and_checks_pinned_digest(tmp_path):
    import hashlib

    module = script("prepare_speech_candidates")
    data = b"abcdefghij"
    path = tmp_path / "model.bin"
    path.with_name("model.bin.part").write_bytes(data[:3])
    ranges = []

    def respond(request):
        header = request.headers["Range"]
        ranges.append(header)
        start, end = map(int, header.removeprefix("bytes=").split("-"))
        return httpx.Response(
            206,
            content=data[start : end + 1],
            headers={"Content-Range": f"bytes {start}-{end}/{len(data)}"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        module.download_ranges(
            client,
            "https://official.example/model",
            hashlib.sha256(data).hexdigest(),
            len(data),
            path,
            block_size=4,
        )
    assert ranges == ["bytes=3-6", "bytes=7-9"]
    assert path.read_bytes() == data
    assert not path.with_name("model.bin.part").exists()


def test_bad_range_or_hash_cannot_promote_candidate(tmp_path):
    module = script("prepare_speech_candidates")
    path = tmp_path / "model.bin"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"abcd"))
    ) as client:
        with pytest.raises(ValueError, match="range"):
            module.download_ranges(client, "https://official.example/model", "0" * 64, 4, path)
    assert not path.exists()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(206, content=b"abcd", headers={"Content-Range": "bytes 0-3/4"})
        )
    ) as client:
        with pytest.raises(ValueError, match="hash"):
            module.download_ranges(client, "https://official.example/model", "0" * 64, 4, path)
    assert not path.exists()


def test_candidate_archive_rejects_traversal_and_symlinks(tmp_path):
    import zipfile

    module = script("prepare_speech_candidates")
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../outside", "data")
    with pytest.raises(ValueError):
        module.extract_zip(path, tmp_path / "models")
    with zipfile.ZipFile(path, "w") as archive:
        link = zipfile.ZipInfo("link")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "outside")
    with pytest.raises(ValueError, match="Unsafe"):
        module.extract_zip(path, tmp_path / "models")


def test_blind_pack_escapes_text_hides_identity_and_does_not_default_scores(tmp_path):
    module = script("report_speech_evaluation")
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"public synthetic audio fixture")
    reports = [
        {
            "model": {"id": "secret-model-name", "task": "tts", "language": "en"},
            "rows": [
                {
                    "repeat": 0,
                    "preview": str(audio),
                    "item_id": "test",
                    "text": "<script>bad</script>",
                    "category": "short",
                }
            ],
        }
    ]
    module.listening_pack(reports, tmp_path / "result")
    page = (tmp_path / "result/listening/index.html").read_text(encoding="utf-8")
    assert "secret-model-name" not in page
    assert "&lt;script&gt;bad&lt;/script&gt;" in page
    assert '<option value="">未评分</option>' in page
    assert "pack_id:packId" in page
    assert "PACK_ID" not in page
    assert (tmp_path / "result/listening/audio/L001.wav").read_bytes() == audio.read_bytes()


@pytest.mark.parametrize("name,link", [("../outside", False), ("link", True)])
def test_candidate_tar_rejects_escape_and_links(tmp_path, name, link):
    import io
    import tarfile

    module = script("prepare_speech_candidates")
    path = tmp_path / "bad.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "outside"
            archive.addfile(member)
        else:
            member.size = 4
            archive.addfile(member, io.BytesIO(b"data"))
    with pytest.raises(ValueError):
        module.extract_tar(path, tmp_path / "models")
    assert not (tmp_path / "outside").exists()


def test_roundtrip_keeps_tts_models_and_judges_separate_without_repeat_inflation(tmp_path):
    import json

    from shinar.local_speech.evaluation_metrics import error_metrics

    module = script("report_speech_evaluation")
    (tmp_path / "source-items.json").write_text(
        json.dumps({"a": {"tts_model": "voice-a"}, "b": {"tts_model": "voice-b"}}), encoding="utf-8"
    )
    for judge, hypothesis in [("judge-a", "cat"), ("judge-b", "bat")]:
        folder = tmp_path / judge
        folder.mkdir()
        (folder / "request.json").write_text(
            json.dumps(
                {"items": [{"id": "a", "reference": "cat"}, {"id": "b", "reference": "cat"}]}
            ),
            encoding="utf-8",
        )
        rows = [
            {
                "item_id": item,
                "repeat": repeat,
                "hypothesis": hypothesis,
                "accuracy": error_metrics("cat", hypothesis, "en"),
            }
            for item in ["a", "b"]
            for repeat in [0, 1]
        ]
        (folder / "report.json").write_text(
            json.dumps({"model": {"id": judge, "language": "en"}, "rows": rows}), encoding="utf-8"
        )
    scores = module.roundtrip_scores(tmp_path)
    assert len(scores) == 4
    assert all(row["utterances"] == 1 for row in scores)
    assert {row["cer"] for row in scores if row["judge"] == "judge-a"} == {0}
    assert {row["wer"] for row in scores if row["judge"] == "judge-b"} == {1}


def test_changed_roundtrip_suite_cannot_overwrite_previous_audio(tmp_path, monkeypatch):
    import json
    import sys

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = script("evaluate_tts_intelligibility")
    audio, report_path = tmp_path / "new.wav", tmp_path / "report.json"
    audio.write_bytes(b"new public audio")
    report_path.write_text("{}", encoding="utf-8")
    report = {
        "model": {"task": "tts"},
        "report_path": str(report_path),
        "rows": [{"repeat": 0, "item_id": "a", "preview": str(audio)}],
    }
    monkeypatch.setattr(module, "collect", lambda _: [report])
    output = tmp_path / "roundtrip"
    output.mkdir()
    (output / "suite.json").write_text(json.dumps({"previous": "suite"}), encoding="utf-8")
    old_audio = output / "previous.wav"
    old_audio.write_bytes(b"previous reviewed audio")
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_tts_intelligibility", "--runs", str(tmp_path), "--output", str(output)],
    )
    with pytest.raises(ValueError, match="suite changed"):
        module.main()
    assert old_audio.read_bytes() == b"previous reviewed audio"
    assert json.loads((output / "suite.json").read_text(encoding="utf-8")) == {"previous": "suite"}


def test_interrupted_benchmark_preserves_request_and_progress(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys

    module = script("evaluate_local_speech")
    root, run = tmp_path / "strict", tmp_path / "run"
    corpus = root / "corpus/zh"
    corpus.mkdir(parents=True)
    audio = b"public audio not decoded in this preservation test"
    (corpus / "a.wav").write_bytes(audio)
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "a",
                        "file": "a.wav",
                        "reference": "你好",
                        "duration_s": 1,
                        "sha256": hashlib.sha256(audio).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "test-candidates.json").write_text(
        json.dumps(
            [
                {
                    "id": "test-model",
                    "task": "stt",
                    "adapter": "vosk",
                    "language": "zh",
                    "path": "unused",
                }
            ]
        ),
        encoding="utf-8",
    )
    destination = run / "test-model--zh"
    destination.mkdir(parents=True)
    request = destination / "request.json"
    request.write_bytes(b'{"previous":"request"}')
    progress = destination / "progress-0010.json"
    progress.write_bytes(b"previous timing observations")
    monkeypatch.setattr(module, "load_catalog", lambda: [])
    monkeypatch.setattr(module, "detect_hardware", lambda _: {})
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("must not restart this attempt")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_local_speech",
            "--root",
            str(root),
            "--cache",
            str(tmp_path / "cache"),
            "--run-dir",
            str(run),
            "--ids",
            "test-model",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    assert exit_info.value.code == 1
    assert request.read_bytes() == b'{"previous":"request"}'
    assert progress.read_bytes() == b"previous timing observations"
    assert "incomplete attempt preserved" in (run / "failures.json").read_text(encoding="utf-8")
