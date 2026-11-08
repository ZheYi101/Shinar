"""Real localhost RTC probe using two participants + synthetic PCM, never AI APIs."""

import argparse
import asyncio
from array import array
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shinar.realtime import PcmFrame, TurnRef
from shinar.realtime.diagnostics import NativeTrace, ProbeError, ProbePhase, classify_probe_error, native_creation_evidence
from shinar.realtime.local_server import (
    ARCHIVE_SHA256, RELEASE_URL, SERVER_VERSION, LocalServer, ensure_server, hidden_flags, socket_snapshot,
    validate_probe_stun_url,
    validate_rtc_address,
)


async def wait_until(predicate, timeout: float = 6) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() > deadline:
            raise RuntimeError("probe_condition_timeout")
        await asyncio.sleep(.01)


def token(key: str, secret: str, room: str, identity: str) -> str:
    from livekit import api
    return (api.AccessToken(key, secret).with_identity(identity).with_ttl(timedelta(minutes=5))
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True,
                                        can_subscribe=True, can_publish_data=True)).to_jwt())


def synthetic_pcm(frame_index: int) -> PcmFrame:
    # Deterministic 440Hz sine, 20ms; not speech, TTS, microphone or an audio recording.
    pcm = array("h", (int(4000 * math.sin(2 * math.pi * 440 * (frame_index * 960 + n) / 48000))
                      for n in range(960)))
    if sys.byteorder != "little":
        pcm.byteswap()
    return PcmFrame(pcm.tobytes())


async def exercise(server: LocalServer, result: dict) -> None:
    from shinar.realtime.livekit_transport import LiveKitTransport, TOPIC
    from shinar.realtime import TurnEvent
    session = "probe-" + uuid.uuid4().hex
    room = session
    started = time.perf_counter()
    now_ms = lambda: round((time.perf_counter() - started) * 1000, 3)
    received: list = []
    audio_counts: dict[int, int] = {}
    audio_nonzero: dict[int, int] = {}
    reverse_audio = {"frames": 0, "nonzero": 0}
    event_times: dict[str, float] = {}

    def on_event(event):
        received.append(event)
        if event.kind == "text_delta":
            event_times.setdefault(f"text_first_delta_g{event.ref.generation}", now_ms())
            event_times[f"last_delta_g{event.ref.generation}"] = now_ms()
        if event.kind == "cancel_ack":
            event_times["cancel_ack"] = now_ms()

    def on_audio(ref, frame):
        audio_counts[ref.generation] = audio_counts.get(ref.generation, 0) + 1
        if any(frame.data):
            audio_nonzero[ref.generation] = audio_nonzero.get(ref.generation, 0) + 1
        event_times.setdefault(f"audio_first_frame_g{ref.generation}", now_ms())

    def on_reverse_audio(ref, frame):
        reverse_audio["frames"] += 1
        reverse_audio["nonzero"] += bool(any(frame.data))

    result["phase"] = ProbePhase.CONFIGURATION.value
    stun_url = validate_probe_stun_url(server.stun_url, server.stun_port, server.rtc_address)
    client = LiveKitTransport(session, "worker", ice_server_urls=(stun_url,),
                              single_peer_connection=server.single_peer_connection,
                              on_event=on_event, on_audio=on_audio)
    worker = LiveKitTransport(session, "client", ice_server_urls=(stun_url,),
                              single_peer_connection=server.single_peer_connection, on_audio=on_reverse_audio)
    result["room_loop_is_current"] = {
        "client": client.room._loop is asyncio.get_running_loop(),
        "worker": worker.room._loop is asyncio.get_running_loop()}

    async def connect_peer(transport, identity: str, phase: ProbePhase):
        print(json.dumps({"probe_stage": phase.value}), flush=True)
        result["phase"] = phase.value
        attempt_started = time.perf_counter()
        record = {"identity": identity, "phase": phase.value}
        try:
            await transport.connect(server.url, token(server.key, server.secret, room, identity))
        except asyncio.CancelledError:
            record.update(status="cancelled", error_code=ProbeError.OPERATION_DEADLINE.value,
                          native_rtc_creation=native_creation_evidence(ProbeError.OPERATION_DEADLINE).value)
            raise
        except Exception as exc:
            code = classify_probe_error(exc, phase)
            record.update(status="failed", error_type=type(exc).__name__, error_code=code.value,
                          native_rtc_creation=native_creation_evidence(code).value)
            raise
        else:
            record.update(status="connected", native_rtc_creation=native_creation_evidence(None).value)
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - attempt_started) * 1000, 3)
            result.setdefault("connection_attempts", []).append(record)

    try:
        await connect_peer(client, "client", ProbePhase.CLIENT_CONNECT)
        await connect_peer(worker, "worker", ProbePhase.WORKER_CONNECT)
        result["transport_connected_ms"] = {
            "client": round(client.metrics["transport_connected_ms"], 3),
            "worker": round(worker.metrics["transport_connected_ms"], 3)}
        await wait_until(lambda: len(client.room.remote_participants) == 1
                         and len(worker.room.remote_participants) == 1)
        await asyncio.gather(client.wait_for_peer(), worker.wait_for_peer())
        result["phase"] = ProbePhase.TEXT_AUDIO.value
        first = TurnRef(session, "turn-1", 1)
        event_times["turn1_start"] = now_ms()
        await worker.start_turn(first)
        for delta in ("local ", "text ", "stream"):
            await worker.send_delta(first, delta)
        await worker.complete_text(first)
        for index in range(75):
            await worker.send_audio(first, synthetic_pcm(index))
            await asyncio.sleep(.02)
        await wait_until(lambda: audio_counts.get(1, 0) >= 30 and client.receiver.completed_text is not None)
        assert client.receiver.completed_text == "local text stream", "text_completion_mismatch"
        first_events = [event for event in received if event.ref == first]
        assert [event.seq for event in first_events] == list(range(len(first_events))), "text_sequence_mismatch"
        assert sum(event.kind == "text_done" for event in first_events) == 1, "completion_count_mismatch"
        result["text_order_and_completion"] = True

        uplink = TurnRef(session, "input-probe", 1)
        await client.start_turn(uplink)
        await client.send_delta(uplink, "uplink")
        await client.complete_text(uplink)
        for index in range(50):
            await client.send_audio(uplink, synthetic_pcm(index))
            await asyncio.sleep(.02)
        await wait_until(lambda: reverse_audio["nonzero"] >= 20 and worker.receiver.completed_text == "uplink")
        result["bidirectional_pcm"] = dict(reverse_audio)

        second = TurnRef(session, "turn-2", 2)
        await worker.start_turn(second)
        await worker.send_delta(second, "unfinished draft")
        for index in range(40):
            await worker.send_audio(second, synthetic_pcm(index))
            await asyncio.sleep(.02)
        await wait_until(lambda: audio_counts.get(2, 0) >= 15 and client.receiver.draft)
        result["phase"] = ProbePhase.CANCEL.value
        old_sid = client.receiver.track_sid
        event_times["cancel_request"] = now_ms()
        await client.request_cancel(second)
        accepted_at_cancel = audio_counts.get(2, 0)
        await wait_until(lambda: "cancel_ack" in event_times)
        assert not await worker.send_delta(second, "late"), "cancelled_sender_delta_accepted"
        assert not await worker.complete_text(second), "cancelled_sender_completed"
        assert not await worker.send_audio(second, synthetic_pcm(99)), "cancelled_sender_audio_accepted"
        # Deliberate stale data over the real channel, bypassing only the sender guard.
        before_rejected = client.receiver.rejected_events
        await worker.room.local_participant.publish_data(
            TurnEvent(second, "text_delta", 999, "late").encode(), reliable=True,
            destination_identities=["client"], topic=TOPIC)
        await wait_until(lambda: client.receiver.rejected_events > before_rejected)
        await asyncio.sleep(.25)
        assert audio_counts.get(2, 0) == accepted_at_cancel, "old_audio_presented_after_cancel"
        assert client.receiver.completed_text is None and client.receiver.draft == "", "draft_became_complete"
        assert not client.receiver.accept_audio(old_sid), "old_sid_accepted"
        result["cancel"] = {"sender_rejected_late_text_audio": True,
                            "real_channel_stale_event_rejected": True,
                            "presented_old_frames_after_request": audio_counts.get(2, 0) - accepted_at_cancel,
                            "unfinished_draft_not_completed": True}

        result["phase"] = ProbePhase.FRESH_GENERATION.value
        third = TurnRef(session, "turn-3", 3)
        await worker.start_turn(third)
        await worker.send_delta(third, "fresh")
        await worker.complete_text(third)
        for index in range(60):
            await worker.send_audio(third, synthetic_pcm(index))
            await asyncio.sleep(.02)
        await wait_until(lambda: audio_counts.get(3, 0) >= 25 and client.receiver.completed_text == "fresh")
        assert not client.receiver.accept_audio(old_sid), "old_sid_accepted_in_new_turn"
        result["fresh_generation_after_cancel"] = True
        result["audio_frames_presented"] = dict(audio_counts)
        result["nonzero_pcm_frames_presented"] = dict(audio_nonzero)
        assert all(audio_nonzero.get(gen, 0) >= minimum for gen, minimum in ((1, 25), (2, 10), (3, 20)))
        result["event_timeline_ms"] = event_times
        result["latency_ms"] = {
            "text_first_delta": round(event_times["text_first_delta_g1"] - event_times["turn1_start"], 3),
            "audio_first_frame": round(event_times["audio_first_frame_g1"] - event_times["turn1_start"], 3),
            "cancel_ack": round(event_times["cancel_ack"] - event_times["cancel_request"], 3),
            "last_old_delta_relative_cancel": round(event_times["last_delta_g2"] - event_times["cancel_request"], 3),
        }
        result["phase"] = ProbePhase.SOCKET_AUDIT.value
        expected = {("tcp", "127.0.0.1", server.http_port), ("udp", server.rtc_address, server.udp_port)}
        result["server_socket_audit_during_rtc"] = await asyncio.to_thread(socket_snapshot, server.pid, expected)
        result["phase"] = ProbePhase.REJOIN.value
        await worker.close()
        await wait_until(lambda: len(client.room.remote_participants) == 0)
        # An explicit disconnect/new Room reconnect tests token + participant lifecycle.
        await connect_peer(worker, "worker", ProbePhase.REJOIN)
        await wait_until(lambda: len(client.room.remote_participants) == 1)
        reconnect = TurnRef(session, "turn-4", 4)
        await worker.start_turn(reconnect)
        await worker.send_delta(reconnect, "reconnected")
        await worker.complete_text(reconnect)
        await wait_until(lambda: client.receiver.completed_text == "reconnected")
        result["explicit_leave_rejoin"] = True
        result["phase"] = ProbePhase.COMPLETE.value
    finally:
        cleanup = await asyncio.gather(worker.close(), client.close(), return_exceptions=True)
        result["sdk_cleanup_error_count"] = sum(isinstance(item, BaseException) for item in cleanup)
        result["sdk_python_tasks_streams_cleanup"] = (
            not worker._tasks and not client._tasks and not worker._streams and not client._streams)
        result["sdk_task_errors"] = worker.metrics["task_errors"] + client.metrics["task_errors"]
        result["receiver_rejected_events"] = client.receiver.rejected_events
        result["receiver_rejected_audio_frames"] = client.receiver.rejected_frames


async def diagnostic_exercise(server, result):
    from livekit.rtc._ffi_client import FfiClient
    queue = FfiClient.instance.queue.subscribe(asyncio.get_running_loop())
    events = {}
    ticks = []
    async def monitor():
        while True:
            event = await queue.get()
            kind = event.WhichOneof("message")
            if kind in {"connect", "disconnect", "room_event"}:
                events[kind] = events.get(kind, 0) + 1
    async def heartbeat():
        while True:
            ticks.append(time.perf_counter())
            await asyncio.sleep(.1)
    tasks = [asyncio.create_task(monitor()), asyncio.create_task(heartbeat())]
    try:
        await exercise(server, result)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        FfiClient.instance.queue.unsubscribe(queue)
        result["ffi_event_counts"] = events
        result["loop_heartbeat"] = {"ticks": len(ticks), "max_gap_ms": round(
            max((b-a for a,b in zip(ticks,ticks[1:])), default=0)*1000, 3)}


def rtc_child() -> int:
    """Ephemeral secrets arrive over stdin, never command arguments/files/logs."""
    payload = json.load(sys.stdin)
    print(json.dumps({"probe_stage": "child_started"}), flush=True)
    logger = logging.getLogger("livekit")
    trace = NativeTrace(payload.get("candidate_address")) if payload.get("diagnostic") else None
    logger.disabled = trace is None
    if trace:
        logger.handlers[:] = [trace]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
    result: dict = {}
    try:
        action = diagnostic_exercise if trace else exercise
        asyncio.run(asyncio.wait_for(action(SimpleNamespace(**payload), result), timeout=payload["timeout_seconds"]))
        result["rtc_exercise_passed"] = (result["sdk_python_tasks_streams_cleanup"]
                                         and result["sdk_task_errors"] == 0
                                         and result["sdk_cleanup_error_count"] == 0)
    except Exception as exc:
        result["rtc_exercise_passed"] = False
        result["error_type"] = type(exc).__name__
        phase = ProbePhase(result.get("phase", ProbePhase.CONFIGURATION.value))
        result["error_phase"] = phase.value
        result["error_code"] = classify_probe_error(exc, phase).value
    if trace:
        result["native_trace"] = trace.snapshot()
        logger.handlers[:] = []
    print(json.dumps(result))
    return 0 if result["rtc_exercise_passed"] else 1


def run_rtc_child(server: LocalServer, result: dict, *, timeout_seconds: float = 45,
                  candidate_address: str | None = None, single_peer_connection: bool = True) -> None:
    child_env = os.environ.copy()
    if server.diagnostic:
        child_env.update(LIVEKIT_RTC_DEBUG="1", RUST_LOG="livekit=debug,livekit_api=debug,livekit_signaling=debug,libwebrtc=debug")
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--rtc-child"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, creationflags=hidden_flags(), env=child_env)
    result["rtc_child_pid"] = child.pid
    try:
        payload = {"url": server.url, "key": server.key, "secret": server.secret, "pid": server.pid,
                   "udp_port": server.udp_port, "stun_port": server.stun_port,
                   "http_port": server.http_port,
                   "rtc_address": server.rtc_address,
                   "timeout_seconds": timeout_seconds,
                   "candidate_address": candidate_address,
                   "diagnostic": server.diagnostic,
                   "single_peer_connection": single_peer_connection,
                   "stun_url": validate_probe_stun_url(f"stun:{server.rtc_address}:{server.stun_port}", server.stun_port,
                                                       server.rtc_address)}
        stdout, stderr = child.communicate(input=json.dumps(payload), timeout=timeout_seconds + 15)
        # Native libraries may print before Python's final JSON record.
        records = [json.loads(line) for line in stdout.splitlines() if line.startswith('{"')]
        completed = [record for record in records if "rtc_exercise_passed" in record]
        result["child_stages"] = [r["probe_stage"] for r in records if "probe_stage" in r]
        if completed:
            result.update(completed[-1])
        else:
            result.update(rtc_exercise_passed=False, error_code="native_child_no_result",
                          child_stdout_bytes=len(stdout.encode()))
        trace = NativeTrace()
        trace.observe(stderr)
        result["child_stderr_trace"] = trace.snapshot()
    except subprocess.TimeoutExpired:
        result.update(rtc_exercise_passed=False, error_code="operation_deadline")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        result["rtc_child_exit_code"] = child.returncode
        result["rtc_child_socket_cleanup"] = not socket_snapshot(child.pid)
        result["rtc_child_exited"] = child.poll() is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-server", action="store_true")
    parser.add_argument("--output", default="build/livekit-probe/results.json")
    parser.add_argument("--port-base", type=int, default=17880)
    parser.add_argument("--diagnostic", action="store_true", help="extract payload-free native/FFI/server stages")
    parser.add_argument("--rtc-bind-ip", default="127.0.0.1", help="one OS-owned RFC1918 IPv4, or 127.0.0.1")
    parser.add_argument("--candidate-address", help="report only whether this local ICE candidate was collected")
    parser.add_argument("--timeout-seconds", type=float, default=45)
    parser.add_argument("--dual-peer-connection", action="store_true", help="use the SDK's compatible dual-PC negotiation")
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 120:
        parser.error("timeout must be between 1 and 120 seconds")
    # SDK informational connection logs may embed a token URL. Persist only our
    # aggregate metadata; no SDK payload/log forwarding, including on failure.
    logging.getLogger("livekit").disabled = True
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    # Probe output/config/archive must remain under this repository's ignored build/.
    if not output.is_relative_to((root / "build").resolve()):
        parser.error("output must be inside the repository build directory")
    cache = root / "build" / "livekit-probe"
    result = {"probe": "real-localhost-rtc" if args.rtc_bind_ip == "127.0.0.1" else "local-private-interface",
              "utc": datetime.now(timezone.utc).isoformat(), "rtc_bind_ip": args.rtc_bind_ip,
              "python": sys.version.split()[0], "server_version": SERVER_VERSION,
              "server_archive_sha256": ARCHIVE_SHA256, "server_source": RELEASE_URL,
              "limits": ["synthetic_text_and_pcm_only", "no_stt_tts_llm_calls", "no_device_playback",
                         "no_vad_aec_or_natural_voice_interrupt", "no_involuntary_network_recovery",
                         "rtc_tcp_fallback_disabled"],
              "rtc_options": {"single_peer_connection": not args.dual_peer_connection,
                              "ice_servers": [{"urls": [f"stun:{args.rtc_bind_ip}:{args.port_base + 3}"]}],
                              "public_ice_server_fallback_blocked": True},
              "phase": ProbePhase.CONFIGURATION.value}
    server = None
    try:
        result["sdk_versions"] = {name: version(name) for name in ("livekit", "livekit-api")}
        validate_rtc_address(args.rtc_bind_ip)
        if args.candidate_address:
            validate_rtc_address(args.candidate_address)
        validate_probe_stun_url(f"stun:{args.rtc_bind_ip}:{args.port_base + 3}", args.port_base + 3, args.rtc_bind_ip)
        executable = ensure_server(cache, download=args.download_server)
        server = LocalServer(executable, cache, http_port=args.port_base,
                             tcp_port=args.port_base + 1, udp_port=args.port_base + 2,
                             diagnostic=args.diagnostic)
        server.rtc_address = args.rtc_bind_ip
        result["phase"] = ProbePhase.SERVER_STARTUP.value
        with server:
            result["server_pid"] = server.pid
            result["server_socket_audit_at_start"] = server.bindings
            result["server_http_status"] = server.http_status
            run_rtc_child(server, result, timeout_seconds=args.timeout_seconds,
                          candidate_address=args.candidate_address or args.rtc_bind_ip,
                          single_peer_connection=not args.dual_peer_connection)
        result["server_cleanup"] = server.cleaned
        result["stun_binding_responses"] = server._stun.requests
        if args.diagnostic:
            result["server_trace"] = server.safe_trace
        result["passed"] = (result["rtc_exercise_passed"] and result["server_cleanup"]
                            and result["rtc_child_socket_cleanup"] and result["rtc_child_exited"])
    except Exception as exc:
        result["passed"] = False
        # No raw SDK/network error strings: those can contain credentials or token URLs.
        result["error_type"] = type(exc).__name__
        phase = ProbePhase(result.get("phase", ProbePhase.CONFIGURATION.value))
        result["error_phase"] = phase.value
        result["error_code"] = classify_probe_error(exc, phase).value
        if server:
            result["server_pid"] = server.pid
            result["server_cleanup"] = server.cleaned
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(rtc_child() if sys.argv[1:] == ["--rtc-child"] else main())
