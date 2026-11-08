"""Allowlisted probe diagnostics: classify in memory; never retain raw errors."""

from enum import StrEnum
from collections import Counter
import ipaddress
import logging
import re
import threading
import time


class NativeTrace(logging.Handler):
    """Parse native logs in memory into an allowlisted, payload-free timeline."""

    PATTERNS = {
        "connecting to ws": "signal_connect_begin",
        "received joinresponse": "signal_join_received",
        "sending publisher offer": "publisher_offer_sent",
        "received publisher answer": "publisher_answer_received",
        "received subscriber offer": "subscriber_offer_received",
        "local ice_candidate": "local_candidate",
        "remote ice_candidate": "remote_candidate",
        "connection change": "pc_connection_change",
        "wait_pc_connection timed out": "native_ice_wait_timeout",
        "empty uri": "native_empty_uri",
        "failed to create peer connection": "native_peer_creation_failed",
        "failed to connect": "native_connect_retry",
        "websocket recv error": "signal_receive_error",
        "starting rtc session": "server_rtc_session_start",
        "participant active": "server_participant_active",
        "participant disconnected": "server_participant_disconnected",
        "ice failed": "server_ice_failed",
        "sendto failed": "udp_send_failed",
        "sent stun ping": "stun_ping_sent",
        "received stun ping": "stun_ping_received",
        "received stun binding response": "stun_response_received",
        "candidate pair": "candidate_pair_activity",
    }
    CANDIDATE = re.compile(
        r"candidate:[^\s]+\s+\d+\s+(udp|tcp)\s+\d+\s+([^\s]+)\s+\d+\s+typ\s+(host|srflx|prflx|relay)",
        re.IGNORECASE)

    def __init__(self, selected_address: str | None = None):
        super().__init__(logging.DEBUG)
        self.started = time.perf_counter()
        self.counts = Counter()
        self.candidates = Counter()
        self.timeline = []
        self._guard = threading.Lock()
        self.selected_address = selected_address
        self.selected_local_candidate_observed = False
        self.source_sites = Counter()
        self.errnos = Counter()

    def observe(self, message: str) -> None:
        lower = message.lower()
        with self._guard:
            self.counts["messages_seen"] += 1
            for marker, code in self.PATTERNS.items():
                if marker in lower:
                    self.counts[code] += 1
                    if len(self.timeline) < 250:
                        entry = {"at_ms": round((time.perf_counter() - self.started) * 1000, 3), "code": code}
                        if code == "pc_connection_change":
                            for state in ("new", "connecting", "connected", "disconnected", "failed", "closed"):
                                if re.search(r"\b" + state + r"\b", lower):
                                    entry["state"] = state
                                    break
                        if code in {"pc_connection_change", "local_candidate", "remote_candidate"}:
                            for target in ("publisher", "subscriber"):
                                if re.search(r"\b" + target + r"\b", lower):
                                    entry["transport"] = target
                                    break
                        self.timeline.append(entry)
            for file, line in re.findall(r"\b([A-Za-z0-9_-]+\.(?:cc|h)):(\d+)", message):
                if len(self.source_sites) < 200:
                    self.source_sites[f"{file}:{line}"] += 1
            for errno in re.findall(r"\b(?:error|errno|err)[:=\s]+(-?\d{1,6})\b", lower):
                self.errnos[errno] += 1
            direction = "local" if "local ice_candidate" in lower else "remote" if "remote ice_candidate" in lower else "sdp"
            for protocol, address, kind in self.CANDIDATE.findall(message):
                try:
                    ip = ipaddress.ip_address(address)
                    scope = "loopback" if ip.is_loopback else "link_local" if ip.is_link_local else "private" if ip.is_private else "public"
                except ValueError:
                    scope = "hostname"
                self.candidates[f"{direction}:{protocol.lower()}:{kind.lower()}:{scope}"] += 1
                if direction == "local" and address == self.selected_address:
                    self.selected_local_candidate_observed = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.observe(record.getMessage())
        except Exception:
            # Never let diagnostics affect the SDK or forward a raw logging error.
            pass

    def snapshot(self) -> dict:
        with self._guard:
            return {"counts": dict(self.counts), "candidate_counts": dict(self.candidates),
                    "timeline": list(self.timeline), "raw_logs_retained": False,
                    "selected_local_candidate_observed": self.selected_local_candidate_observed,
                    "source_sites": dict(self.source_sites), "error_numbers": dict(self.errnos)}


class ProbePhase(StrEnum):
    CONFIGURATION = "configuration"
    SERVER_STARTUP = "server_startup"
    CLIENT_CONNECT = "client_connect"
    WORKER_CONNECT = "worker_connect"
    TEXT_AUDIO = "text_audio"
    CANCEL = "cancel"
    FRESH_GENERATION = "fresh_generation"
    REJOIN = "rejoin"
    SOCKET_AUDIT = "socket_audit"
    CLEANUP = "cleanup"
    COMPLETE = "complete"


class ProbeError(StrEnum):
    ICE_CONFIG_EMPTY_URI = "ice_config_empty_uri"
    ICE_CONFIG_INVALID = "ice_config_invalid"
    ICE_HANDSHAKE_TIMEOUT = "ice_handshake_timeout"
    SIGNALING_CONNECTION = "signaling_connection"
    OPERATION_DEADLINE = "operation_deadline"
    ASSERTION_FAILED = "assertion_failed"
    UNKNOWN_CONNECT_ERROR = "unknown_connect_error"
    OPERATION_FAILED = "operation_failed"
    SOCKET_SCOPE_VIOLATION = "socket_scope_violation"
    SERVER_STARTUP_FAILED = "server_startup_failed"


class NativeCreationEvidence(StrEnum):
    CONNECT_COMPLETED = "connect_completed"
    REJECTED_BEFORE_ICE = "rejected_before_ice"
    PASSED_INFERRED_FROM_ICE_TIMEOUT = "passed_inferred_from_ice_timeout"
    NOT_OBSERVED = "not_observed"


def native_creation_evidence(error: ProbeError | None) -> NativeCreationEvidence:
    if error is None:
        return NativeCreationEvidence.CONNECT_COMPLETED
    if error in {ProbeError.ICE_CONFIG_EMPTY_URI, ProbeError.ICE_CONFIG_INVALID}:
        return NativeCreationEvidence.REJECTED_BEFORE_ICE
    if error is ProbeError.ICE_HANDSHAKE_TIMEOUT:
        # Explicit inference: this error is emitted by Rust's post-creation
        # wait_pc_connection, not a directly observed peer-creation callback.
        return NativeCreationEvidence.PASSED_INFERRED_FROM_ICE_TIMEOUT
    return NativeCreationEvidence.NOT_OBSERVED


def classify_probe_error(exc: BaseException, phase: ProbePhase) -> ProbeError:
    # Some native errors arrive wrapped. Scan a bounded chain in memory only;
    # no substring, URL, key, prompt or raw exception becomes report content.
    messages = []
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        messages.append(str(current).lower())
        current = current.__cause__ or current.__context__
    message = "\n".join(messages)
    if "non_loopback_server_socket" in message:
        return ProbeError.SOCKET_SCOPE_VIOLATION
    if "livekit_server_exited_at_startup" in message or "livekit_expected_loopback_sockets_missing" in message:
        return ProbeError.SERVER_STARTUP_FAILED
    if "empty uri" in message:
        return ProbeError.ICE_CONFIG_EMPTY_URI
    if any(marker in message for marker in (
        "ice server parsing failed", "invalid ice server", "invalid ice configuration",
        "explicit_ice_server_urls_required", "invalid_probe_stun_url",
    )):
        return ProbeError.ICE_CONFIG_INVALID
    if "wait_pc_connection timed out" in message:
        return ProbeError.ICE_HANDSHAKE_TIMEOUT
    if isinstance(exc, TimeoutError):
        return ProbeError.OPERATION_DEADLINE
    if isinstance(exc, AssertionError):
        return ProbeError.ASSERTION_FAILED
    if phase in {ProbePhase.CLIENT_CONNECT, ProbePhase.WORKER_CONNECT, ProbePhase.REJOIN}:
        if any(marker in message for marker in (
            "signaling", "signal connection", "websocket", "connection refused", "unauthorized",
        )):
            return ProbeError.SIGNALING_CONNECTION
        if type(exc).__name__ == "ConnectError":
            return ProbeError.UNKNOWN_CONNECT_ERROR
    return ProbeError.OPERATION_FAILED
