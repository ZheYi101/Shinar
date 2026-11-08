"""Worker coroutines use frozen request inputs and return original event identities."""

import asyncio
from shinar.realtime.continuous_assets import vad_path
from shinar.desktop.tasks.speech_errors import safe_speech_code


async def connect_call(
    identity, process, stt, tts, language, speak, resume, config, root, emit, current
):
    stage = "stt"
    try:
        await asyncio.to_thread(vad_path, root, verify=True)
        for route, required in ((stt, True), (tts, False)):
            if route is tts and not speak:
                continue
            try:
                stage = "stt" if required else "tts"
                emit(identity, "connection_stage", "stt" if required else "tts")
                bound = await route.bind(language)
                warm = getattr(bound, "prepare", None)
                if warm:
                    await warm()
            except Exception as error:
                if required:
                    raise
                emit(identity, "tts_unavailable", safe_speech_code(error))
        if not current(identity):
            return
        emit(identity, "connection_stage", "rtc")
        stage = "rtc"
        result = await process.start(config)
        emit(identity, "connected", (resume, result))
    except asyncio.CancelledError:
        await process.close()
        raise
    except Exception as error:
        await process.close()
        emit(
            identity,
            "failed",
            {"code": safe_speech_code(error), "stage": stage, "language": language},
        )


async def pause_call(runner, process, identity, preserve, pause_id, emit):
    try:
        await runner.cancel_input()
        if preserve:
            pending = runner.pending_input
            fields = {k: pending[0][k] for k in ("utterance", "revision")} if pending else {}
            result = await process.request(
                "pause", pending[1] if pending else b"", pause_id=pause_id, **fields
            )
            emit(identity, "pause_device", (pause_id, result))
        else:
            runner.pending_input = None
            await process.request("mute")
    except Exception:
        emit(identity, "input_control_failed")


async def resume_call(process, identity, preserve, emit):
    try:
        result = await process.request("resume", preserve_input=preserve)
        emit(identity, "resume_device", result)
    except Exception:
        emit(identity, "failed", "connection_failed")


async def discard_call(runner, process, identity, emit):
    try:
        await runner.cancel_input()
        runner.pending_input = None
        await process.request("discard_input")
        emit(identity, "input_discarded")
    except Exception:
        emit(identity, "input_control_failed")


async def send_paused_call(runner, process, identity, header, data, source, emit):
    try:
        await runner.cancel_input()
        await process.request("discard_input")
        emit(identity, "submit_paused", (header, data, source))
    except Exception:
        emit(identity, "input_control_failed")


async def restart_call(old_runner, old_process, identity, resume, emit):
    try:
        if old_runner:
            await old_runner.close()
    finally:
        if old_process:
            await old_process.close()
    emit(identity, "restart", resume)
