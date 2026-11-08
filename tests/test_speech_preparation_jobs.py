"""Independent job identities, cancellation and a bounded shared download cache."""

import hashlib
from threading import Event, Thread

import httpx
import pytest

from shinar.desktop.speech_jobs import SpeechPreparationJobs
from shinar.local_speech.catalog import Artifact
from shinar.local_speech.downloads import (
    DownloadCancelled,
    ModelStore,
    TransferEvent,
    package_lock,
)
from test_desktop_workflow import qt_app, until  # noqa: F401


def test_parallel_jobs_have_separate_progress_cancel_retry_and_capacity(qt_app):
    queue = SpeechPreparationJobs(concurrency=2)
    gates = {name: Event() for name in ("stt", "tts", "third", "fourth")}
    starts = []

    def operation(name):
        def run(cancel, stage, transfer):
            starts.append(name)
            stage("speech_setup_model")
            transfer(TransferEvent(name + ".onnx", "downloading", 123, 1024))
            while not gates[name].is_set():
                if cancel.wait(0.01):
                    raise DownloadCancelled()

        return run

    try:
        ids = {
            name: queue.enqueue(
                name, name, "stt" if name == "stt" else "tts", "en", operation(name)
            )
            for name in gates
        }
        until(lambda: len(starts) == 2 and all(r["component"] for r in queue.rows()[:2]))
        assert queue.active_count == 4
        assert [r["state"] for r in queue.rows()] == ["running", "running", "queued", "queued"]
        assert queue.enqueue("stt", "duplicate", "stt", "ja", operation("stt")) == ids["stt"]
        assert queue.rowCount() == 4
        queue.cancel(ids["fourth"])
        assert "fourth" not in starts
        queue.cancel(ids["stt"])
        until(lambda: "third" in starts)
        assert queue.rows()[0]["state"] == "cancelled"
        assert queue.rows()[1]["state"] == "running"
        gates["stt"].set()
        queue.retry(ids["stt"])
        assert queue.rows()[-1]["jobId"] != ids["stt"]
        gates["tts"].set()
        until(lambda: starts.count("stt") == 2)
        gates["third"].set()
        until(lambda: not queue.active_count)
        assert all(r["state"] in {"cancelled", "completed"} for r in queue.rows())
    finally:
        queue.close()
        for gate in gates.values():
            gate.set()


def test_failed_job_does_not_expose_provider_body_or_stop_other_jobs(qt_app):
    queue = SpeechPreparationJobs()

    def fail(*_):
        raise RuntimeError("secret-token and private HTTP request body")

    try:
        queue.enqueue("bad", "Bad", "stt", "en", fail)
        queue.enqueue("good", "Good", "tts", "ja", lambda *_: None)
        until(lambda: not queue.active_count)
        assert [r["state"] for r in queue.rows()] == ["failed", "completed"]
        assert all("secret" not in str(r) and "HTTP request" not in str(r) for r in queue.rows())
    finally:
        queue.close()


def test_shared_blob_is_downloaded_once_and_waiter_can_cancel(tmp_path):
    blob = b"shared model resource"
    artifact = Artifact(
        path="shared.onnx",
        url="https://models.example/shared",
        size=len(blob),
        sha256=hashlib.sha256(blob).hexdigest(),
    )
    started, release, cancel = Event(), Event(), Event()
    requests, results, errors = [], [], []

    def serve(request):
        requests.append(request)
        started.set()
        assert release.wait(5)
        return httpx.Response(200, content=blob)

    def fetch(abort=None):
        try:
            store = ModelStore(tmp_path, wait_for_locks=True)
            with httpx.Client(transport=httpx.MockTransport(serve)) as client:
                results.append(store._fetch(artifact, client, abort, lambda *_: None))
        except Exception as error:
            errors.append(error)

    first = Thread(target=fetch)
    second = Thread(target=fetch, args=(cancel,))
    first.start()
    assert started.wait(2)
    second.start()
    cancel.set()
    second.join(2)
    assert not second.is_alive() and isinstance(errors[0], DownloadCancelled)
    release.set()
    first.join(3)
    fetch()
    assert len(requests) == 1
    assert len(results) == 2 and results[0].read_bytes() == blob


def test_close_cancels_shared_component_wait_without_installing(tmp_path, qt_app):
    from types import SimpleNamespace

    package = SimpleNamespace(id="shared-runtime")
    queue = SpeechPreparationJobs()
    entered = Event()

    def operation(cancel, *_):
        entered.set()
        with package_lock(tmp_path, package, wait=True, cancel=cancel):
            pytest.fail("The owning lock must still be held")

    with package_lock(tmp_path, package):
        queue.enqueue("model", "Model", "stt", "en", operation)
        assert entered.wait(1)
        queue.close()
        queue._jobs[0].thread.join(2)
        assert not queue._jobs[0].thread.is_alive()


def test_close_stops_its_installer_process_before_returning(qt_app, tmp_path):
    import sys
    from shinar.local_speech.runtime import run_bounded
    marker = tmp_path / "started"
    queue = SpeechPreparationJobs()
    def operation(cancel, *_):
        run_bounded([sys.executable, "-c", "import sys,time; from pathlib import Path; Path(sys.argv[1]).write_text('ready'); time.sleep(30)", str(marker)], cancel=cancel)
    queue.enqueue("installer", "Installer", "stt", "en", operation)
    until(lambda: marker.exists())
    queue.close()
    assert not queue._jobs[0].thread.is_alive()
