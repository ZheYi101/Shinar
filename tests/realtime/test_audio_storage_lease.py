"""RTC ownership keeps maintenance out until the actual subprocess has ended."""

import asyncio
import hashlib
import io
from threading import Thread
import zipfile

import pytest

from shinar.local_speech.storage_lease import StorageBusyError, storage_lease
from shinar.realtime.audio_process import AudioSessionProcess


def maintenance_blocked(root):
    outcome = []

    def attempt():
        try:
            with storage_lease(root, exclusive=True):
                outcome.append(False)
        except StorageBusyError:
            outcome.append(True)

    thread = Thread(target=attempt)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    return outcome == [True]


class ControlledProcess:
    pid, returncode, stdin = 123456, None, None

    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.exited, self.waiting = asyncio.Event(), asyncio.Event()

    async def wait(self):
        self.waiting.set()
        await self.exited.wait()
        self.returncode = 0
        return 0


def test_idle_call_and_pending_actual_exit_keep_all_directories_leased(tmp_path, monkeypatch):
    import shinar.realtime.audio_process as module

    roots = [tmp_path / "voice-runtime", tmp_path / "speech-library"]

    async def run():
        child = ControlledProcess()

        async def spawn(*args, **kwargs):
            return child

        async def request(*args, **kwargs):
            return {"ok": True}

        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
        audio = AudioSessionProcess("call", lambda *args: None)
        monkeypatch.setattr(audio, "request", request)
        audio.configure_storage(roots)
        roots.append(tmp_path / "not-in-frozen-request")
        await audio.start({})
        assert audio.storage_roots == tuple(roots[:2])
        await asyncio.sleep(.01)  # No STT/TTS process or active turn is required.
        assert all(maintenance_blocked(root) for root in audio.storage_roots)
        closing = asyncio.create_task(audio.close())
        await child.waiting.wait()
        assert not closing.done()
        assert all(maintenance_blocked(root) for root in audio.storage_roots)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert all(maintenance_blocked(root) for root in audio.storage_roots)
        child.exited.set()
        await audio.close()
        assert all(not maintenance_blocked(root) for root in audio.storage_roots)

    asyncio.run(run())


def test_spawn_failure_releases_retained_storage(tmp_path, monkeypatch):
    import shinar.realtime.audio_process as module

    async def run():
        async def spawn(*args, **kwargs):
            raise OSError("simulated spawn failure")

        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
        audio = AudioSessionProcess("call", lambda *args: None)
        audio.configure_storage((tmp_path,))
        with pytest.raises(OSError, match="spawn failure"):
            await audio.start({})
        assert not maintenance_blocked(tmp_path)

    asyncio.run(run())


def test_cancel_during_spawn_waits_for_actual_child_before_releasing(tmp_path, monkeypatch):
    import shinar.realtime.audio_process as module

    async def run():
        child = ControlledProcess()
        spawning, finish_spawn = asyncio.Event(), asyncio.Event()

        async def spawn(*args, **kwargs):
            spawning.set()
            await finish_spawn.wait()
            return child

        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
        audio = AudioSessionProcess("call", lambda *args: None)
        audio.configure_storage((tmp_path,))
        starting = asyncio.create_task(audio.start({}))
        await spawning.wait()
        starting.cancel()
        assert maintenance_blocked(tmp_path)
        finish_spawn.set()
        await child.waiting.wait()
        assert maintenance_blocked(tmp_path)
        child.exited.set()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not maintenance_blocked(tmp_path)

    asyncio.run(run())


def test_start_protocol_failure_stops_child_before_releasing(tmp_path, monkeypatch):
    import shinar.realtime.audio_process as module

    async def run():
        child = ControlledProcess()

        async def spawn(*args, **kwargs):
            return child

        async def request(kind, **kwargs):
            if kind == "start":
                raise RuntimeError("start protocol failed")
            child.exited.set()
            return {}

        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
        audio = AudioSessionProcess("call", lambda *args: None)
        monkeypatch.setattr(audio, "request", request)
        audio.configure_storage((tmp_path,))
        with pytest.raises(RuntimeError, match="protocol failed"):
            await audio.start({})
        assert child.returncode == 0
        assert not maintenance_blocked(tmp_path)

    asyncio.run(run())


def test_server_archive_extraction_holds_its_actual_cache_parent(tmp_path, monkeypatch):
    import shinar.realtime.local_server as module

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("livekit-server.exe", b"not executed")
    content = output.getvalue()
    monkeypatch.setattr(module, "ARCHIVE_SHA256", hashlib.sha256(content).hexdigest())
    cache = tmp_path / "actual-runtime/sfu"
    cache.mkdir(parents=True)
    (cache / module.ARCHIVE_NAME).write_bytes(content)
    observed = []
    executable = module.ensure_server(cache, on_transfer=lambda event: observed.append(
        maintenance_blocked(cache.parent)
    ))
    assert executable.read_bytes() == b"not executed"
    assert observed and all(observed)
    assert not maintenance_blocked(cache.parent)
