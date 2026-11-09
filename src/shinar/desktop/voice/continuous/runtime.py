"""Qt-owned resources and the narrow capabilities supplied to call collaborators."""

from collections import deque
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QMicrophonePermission, Qt

from shinar.realtime.audio_process import AudioSessionProcess
from shinar.local_speech.installation import managed_status
from shinar.realtime.continuous_assets import vad_path
from shinar.desktop.voice.routing import SpeechRoute
from shinar.desktop.voice.continuous.state import CallEvent


class CallRuntime:
    """This adapter alone knows the Qt facade and the surrounding desktop objects."""

    def __init__(self, facade, voice):
        self._facade, self._voice, self._vm = facade, voice, voice.vm
        self.worker = voice.worker
        database = self._vm.workbench.storage_path or Path.cwd() / "build/voice.sqlite3"
        self.root = Path(database).parent / "voice-runtime"
        self.process_factory = AudioSessionProcess
        self.bridge_factory = None
        self.bridge = self.process = self.runner = None
        self.jobs = set()
        self.timings = {}
        self.faults = deque(maxlen=32)
        self.capture_pending = 0
        self._capture_lock = Lock()
        self.coordinator = self.preparation = None

    @property
    def voice_pending(self):
        return self._voice.pending_job

    @property
    def operation_busy(self):
        return self._vm.operationBusy

    @property
    def session_active(self):
        return self._vm.sessionActive

    @property
    def workbench(self):
        return self._vm.workbench

    @property
    def draft(self):
        return self._vm.draft

    @property
    def draft_revision(self):
        return self._vm.draft_revision

    @property
    def pause_ms(self):
        return self._vm.preferences.voicePauseMs

    @property
    def turn_errors(self):
        return self._voice.turn_errors

    @property
    def speech_errors(self):
        return self._voice.speech_errors

    @property
    def speech_error_codes(self):
        return self._voice.speech_error_codes

    def source(self):
        return self._vm.source_context_provider()

    def language(self):
        return self._vm.speech_language()

    def speak_enabled(self):
        return self._voice.speak_enabled()

    def suspend_preflight(self):
        self._voice.preflight.suspendMicrophone()

    def route(self, task):
        return SpeechRoute(self._vm, task)

    def new_token(self, task):
        return self._vm.new_presentation_token(task)

    def confirm(self, token, turn, session, draft):
        return self._vm.confirm_presentation(token, turn, session, draft)

    def present(self, event):
        return self._vm.present_conversation(event)

    def notify(self):
        if not self.coordinator.snapshot.closed:
            self._facade.changed.emit()
            self._voice.notify()

    def components_changed(self):
        self._facade.componentsChanged.emit()

    def storage_changed(self):
        self._facade.setupStorageChanged.emit()

    def emit(self, identity, kind, value=None, generation=0):
        self._facade.eventReceived.emit(CallEvent(identity, kind, generation, value))

    def post(self, operation):
        job = "call-" + uuid4().hex
        self.jobs.add(job)
        self.worker.submit_job(job, operation)
        return job

    def job_done(self, job, result, error):
        if job in self.jobs:
            self.jobs.discard(job)
            self.worker.forget_job(job)

    def vad(self):
        return vad_path(self.root)

    def create_process(self, identity):
        process = self.process_factory(
            identity, lambda header, data: self.emit(identity, "transport", (header, data))
        )
        if type(process) is AudioSessionProcess:
            status = managed_status(self.root, "rtc-cpu")
            if status.get("prepared"):
                process.python = status["python"]
            roots = [self.root]
            local = self._vm.local_speech
            if local and any(local.enabled(task) for task in ("stt", "tts")):
                roots.append(local.store.root)
            process.configure_storage(roots)
        return process

    def new_bridge(self):
        if self.bridge_factory:
            bridge = self.bridge_factory()
        else:
            from shinar.desktop.voice.pcm_audio import PcmAudioBridge

            bridge = PcmAudioBridge(self._vm.audio, self._facade)
        bridge.capture.connect(self.capture)
        bridge.rendered.connect(self.rendered)
        bridge.credit.connect(self.credit)
        bridge.drained.connect(self.coordinator.output_drained)
        bridge.fault.connect(self.coordinator.device_fault)
        return bridge

    def request_permission(self, continuation, *, starting=False):
        snapshot = self.coordinator.snapshot
        if snapshot.permission_pending:
            return
        app, permission = QCoreApplication.instance(), QMicrophonePermission()
        identity = snapshot.identity

        def complete(status):
            if not self.coordinator.current(identity):
                return
            allowed = status == Qt.PermissionStatus.Granted
            self.coordinator.permission_result(allowed, starting)
            if allowed:
                continuation()

        status = app.checkPermission(permission)
        if status != Qt.PermissionStatus.Undetermined:
            complete(status)
            return
        self.coordinator.permission_requested(starting)
        app.requestPermission(permission, self._facade, lambda result: complete(result.status()))

    def capture(self, header, data):
        snapshot = self.coordinator.snapshot
        if snapshot.muted or snapshot.connection != "active":
            return
        with self._capture_lock:
            overflow = self.capture_pending + len(data) > self.bridge.input_format.bytesForDuration(
                200000
            )
            if not overflow:
                self.capture_pending += len(data)
        if overflow:
            self.coordinator.device_fault("input_gap")
            return
        process = self.process

        async def send():
            try:
                await process.send("capture", data, **header)
            finally:
                with self._capture_lock:
                    self.capture_pending -= len(data)

        self.post(send)

    def rendered(self, header, data):
        if self.process and header["generation"] == self.coordinator.snapshot.audio_generation:
            process = self.process
            self.post(lambda: process.send("rendered", data, **header))
            if self.runner:
                self.timings.setdefault(
                    "device_first_submit_ms", (perf_counter() - self.runner.started_at) * 1000
                )

    def credit(self):
        if self.process:
            process = self.process
            self.post(lambda: process.send("credit"))

    def record_fault(self, code, *, stage=None):
        state = self.coordinator.snapshot
        self.faults.append(
            {
                "at": perf_counter(),
                "code": code,
                "input": state.input,
                "output": state.output,
                "capture_pending": self.capture_pending,
                "stage": stage,
            }
        )

    async def aclose(self):
        runner, process = self.runner, self.process
        self.runner = self.process = None
        try:
            if runner:
                await runner.close()
        finally:
            if process:
                await process.close()
