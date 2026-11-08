import pytest

from shinar.realtime.diagnostics import (
    NativeCreationEvidence, ProbeError, ProbePhase, classify_probe_error, native_creation_evidence,
)
from shinar.realtime.local_server import validate_probe_stun_url
from shinar.realtime.local_server import validate_rtc_address


def test_exact_audited_loopback_stun_endpoint_is_valid():
    assert validate_probe_stun_url("stun:127.0.0.1:17882", 17882) == "stun:127.0.0.1:17882"


@pytest.mark.parametrize("url,port", [
    ("", 17882), ("stun:localhost:17882", 17882), ("stun:127.0.0.1:17883", 17882),
    ("stun:127.0.0.1:017882", 17882), ("stun:8.8.8.8:17882", 17882),
    ("stun:user@127.0.0.1:17882", 17882), ("stun:127.0.0.1:17882?transport=udp", 17882),
    ("stun:127.0.0.1:17882#fragment", 17882), ("stun://127.0.0.1:17882", 17882),
    ("turn:127.0.0.1:17882", 17882), ("stun:[::1]:17882", 17882),
    ("stun:127.0.0.1:17882", 65536), ("stun:127.0.0.1:1", True),
])
def test_probe_rejects_dns_external_unexpected_port_and_noncanonical_urls(url, port):
    with pytest.raises(ValueError, match="invalid_probe_stun_url"):
        validate_probe_stun_url(url, port)


@pytest.mark.parametrize("exc,phase,expected", [
    (ValueError("ICE server parsing failed: Empty uri."), ProbePhase.CLIENT_CONNECT,
     ProbeError.ICE_CONFIG_EMPTY_URI),
    (ValueError("ICE server parsing failed: Invalid hostname format"), ProbePhase.CLIENT_CONNECT,
     ProbeError.ICE_CONFIG_INVALID),
    (ValueError("explicit_ice_server_urls_required"), ProbePhase.CLIENT_CONNECT,
     ProbeError.ICE_CONFIG_INVALID),
    (RuntimeError("engine: wait_pc_connection timed out"), ProbePhase.WORKER_CONNECT,
     ProbeError.ICE_HANDSHAKE_TIMEOUT),
    (RuntimeError("ice connection timed out"), ProbePhase.CLIENT_CONNECT,
     ProbeError.OPERATION_FAILED),
    (RuntimeError("ice connect timeout"), ProbePhase.CLIENT_CONNECT,
     ProbeError.OPERATION_FAILED),
    (RuntimeError("websocket failed at ws://host/?access_token=secret"), ProbePhase.CLIENT_CONNECT,
     ProbeError.SIGNALING_CONNECTION),
    (TimeoutError(), ProbePhase.CLIENT_CONNECT, ProbeError.OPERATION_DEADLINE),
    (AssertionError("private dialogue content"), ProbePhase.CANCEL, ProbeError.ASSERTION_FAILED),
    (RuntimeError("non_loopback_server_socket"), ProbePhase.SERVER_STARTUP,
     ProbeError.SOCKET_SCOPE_VIOLATION),
    (RuntimeError("livekit_server_exited_at_startup"), ProbePhase.SERVER_STARTUP,
     ProbeError.SERVER_STARTUP_FAILED),
])
def test_error_classification_uses_only_allowlisted_codes(exc, phase, expected):
    assert classify_probe_error(exc, phase) is expected


def test_wrapped_and_unknown_errors_do_not_leak_raw_message():
    class ConnectError(Exception):
        pass
    error = ConnectError("access_token=private-key secret-user-dialogue")
    assert classify_probe_error(error, ProbePhase.CLIENT_CONNECT) is ProbeError.UNKNOWN_CONNECT_ERROR
    error.__cause__ = ValueError("ICE server parsing failed: Empty uri. secret")
    classified = classify_probe_error(error, ProbePhase.CLIENT_CONNECT)
    assert classified is ProbeError.ICE_CONFIG_EMPTY_URI
    assert "secret" not in classified.value and "private-key" not in classified.value


def test_native_creation_evidence_distinguishes_observation_inference_and_unknown():
    assert native_creation_evidence(None) is NativeCreationEvidence.CONNECT_COMPLETED
    assert native_creation_evidence(ProbeError.ICE_CONFIG_EMPTY_URI) is NativeCreationEvidence.REJECTED_BEFORE_ICE
    assert native_creation_evidence(ProbeError.ICE_HANDSHAKE_TIMEOUT) is NativeCreationEvidence.PASSED_INFERRED_FROM_ICE_TIMEOUT
    assert native_creation_evidence(ProbeError.OPERATION_DEADLINE) is NativeCreationEvidence.NOT_OBSERVED
    assert native_creation_evidence(ProbeError.UNKNOWN_CONNECT_ERROR) is NativeCreationEvidence.NOT_OBSERVED
    for error in ProbeError:
        assert isinstance(native_creation_evidence(error), NativeCreationEvidence)


def test_only_exact_os_owned_rfc1918_address_may_be_selected():
    assert validate_rtc_address("10.2.3.4", {"10.2.3.4"}) == "10.2.3.4"
    assert validate_probe_stun_url("stun:10.2.3.4:17882", 17882, "10.2.3.4", owned={"10.2.3.4"})
    for address in ("10.2.3.5", "198.18.0.1", "169.254.1.2", "0.0.0.0", "8.8.8.8", "224.0.0.1"):
        with pytest.raises(ValueError):
            validate_rtc_address(address, {"10.2.3.4", address} if address != "10.2.3.5" else {"10.2.3.4"})
    with pytest.raises(ValueError):
        validate_probe_stun_url("stun:10.2.3.5:17882", 17882, "10.2.3.4", owned={"10.2.3.4"})


def test_native_trace_only_exposes_whitelisted_metadata():
    from shinar.realtime.diagnostics import NativeTrace
    trace = NativeTrace("10.2.3.4")
    trace.observe('local ice_candidate candidate:123 1 udp 12345 10.2.3.4 50000 typ host token=secret')
    trace.observe('received JoinResponse access_token=secret private-user-text')
    trace.observe('unrecognized secret')
    snapshot = trace.snapshot()
    assert snapshot["selected_local_candidate_observed"] is True
    assert snapshot["candidate_counts"] == {"local:udp:host:private": 1}
    assert snapshot["counts"]["signal_join_received"] == 1
    assert "secret" not in str(snapshot) and "10.2.3.4" not in str(snapshot)
