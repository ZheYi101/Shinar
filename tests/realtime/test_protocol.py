import json

import pytest

from shinar.realtime import PcmFrame, TurnEvent, TurnReceiver, TurnRef
from shinar.realtime.local_server import server_config


def test_complete_requires_explicit_done_and_strict_sequence():
    ref = TurnRef("s", "t", 1)
    receiver = TurnReceiver("s")
    assert receiver.accept(TurnEvent(ref, "start", 0))
    assert not receiver.accept(TurnEvent(ref, "text_delta", 2, "out of order"))
    assert receiver.accept(TurnEvent(ref, "text_delta", 1, "hello"))
    assert receiver.completed_text is None
    assert not receiver.accept(TurnEvent(ref, "text_delta", 1, "duplicate"))
    assert receiver.accept(TurnEvent(ref, "text_done", 2))
    assert receiver.completed_text == "hello"
    assert not receiver.accept(TurnEvent(ref, "text_delta", 3, "late"))


def test_cancel_closes_old_sid_and_draft_before_new_generation():
    old, fresh = TurnRef("s", "old", 1), TurnRef("s", "fresh", 2)
    receiver = TurnReceiver("s")
    assert receiver.accept(TurnEvent(old, "start", 0))
    assert receiver.accept(TurnEvent(old, "text_delta", 1, "partial"))
    assert receiver.accept(TurnEvent(old, "audio_bind", 2, track_sid="old-sid"))
    assert receiver.accept_audio("old-sid")
    receiver.cancel(old)
    assert receiver.completed_text is None and receiver.draft == ""
    assert not receiver.accept_audio("old-sid")
    assert not receiver.accept(TurnEvent(old, "text_done", 3))
    assert not receiver.accept(TurnEvent(old, "start", 0))
    assert receiver.accept(TurnEvent(old, "cancel_ack", 3))
    assert receiver.accept(TurnEvent(fresh, "start", 0))
    assert not receiver.accept_audio("old-sid")
    assert receiver.accept(TurnEvent(fresh, "audio_bind", 1, track_sid="fresh-sid"))
    assert receiver.accept_audio("fresh-sid")
    assert not receiver.accept(TurnEvent(old, "text_delta", 4, "late"))


def test_foreign_session_and_nonincreasing_generation_rejected():
    receiver = TurnReceiver("s")
    assert not receiver.accept(TurnEvent(TurnRef("other", "t", 3), "start", 0))
    assert receiver.accept(TurnEvent(TurnRef("s", "t", 3), "start", 0))
    assert not receiver.accept(TurnEvent(TurnRef("s", "another", 3), "start", 0))
    assert not receiver.accept(TurnEvent(TurnRef("s", "old", 2), "start", 0))


def test_event_wire_roundtrip_and_size_bound():
    event = TurnEvent(TurnRef("s", "t", 1), "text_delta", 1, "日本語")
    assert TurnEvent.decode(event.encode()) == event
    with pytest.raises(ValueError, match="too_large"):
        TurnEvent(event.ref, "text_delta", 2, "x" * 12001).encode()


@pytest.mark.parametrize("payload", [b"[]", b"null", b"{}", b"not json",
    json.dumps({"ref": {"session_id": "s", "turn_id": "t", "generation": True},
                "kind": "start", "seq": 0, "text": "", "track_sid": ""}).encode(),
    json.dumps({"ref": {"session_id": "s", "turn_id": "t", "generation": 1},
                "kind": "unknown", "seq": 0, "text": "", "track_sid": ""}).encode()])
def test_invalid_events_fail_closed(payload):
    with pytest.raises((ValueError, KeyError)):
        TurnEvent.decode(payload)


def test_pcm_contract_and_no_vendor_import_needed():
    assert len(PcmFrame(bytes(1920)).data) == 1920
    for data in (b"", b"x", bytes(9602)):
        with pytest.raises(ValueError):
            PcmFrame(data)
    with pytest.raises(ValueError):
        PcmFrame(bytes(1920), sample_rate=16000)


def test_local_config_disables_wildcard_tcp_fallback_and_filters_udp():
    config = server_config(17880, 17881, 17882, "ephemeral", "ephemeral")
    assert config["bind_addresses"] == ["127.0.0.1"]
    assert config["rtc"]["tcp_port"] == 0
    assert config["rtc"]["ips"]["includes"] == ["127.0.0.1/32"]
    assert config["rtc"]["use_external_ip"] is False
    assert config["turn"]["enabled"] is False
