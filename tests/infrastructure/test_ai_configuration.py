import os

import pytest

from lingualoop.infrastructure import ai_configuration as module
from lingualoop.infrastructure.ai_configuration import AIConnection, AIConfigurationStore


def fake_crypt(value, *, decrypt=False):
    return bytes(c ^ 123 for c in value)


def test_encrypted_atomic_settings_and_replacement_preserve_previous_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_crypt", fake_crypt)
    store = AIConfigurationStore(tmp_path / "ai-services.json")
    connection = AIConnection.validated("https://example.test", "reason", "", "private-test-key")
    assert connection.base_url == "https://example.test/v1" and connection.dialogue_model == "reason"
    assert "private-test-key" not in repr(connection)
    store.save(connection)
    previous = store.path.read_bytes()
    assert b"private-test-key" not in previous and store.load() == connection
    monkeypatch.setattr(module, "_crypt", lambda *a, **kw: (_ for _ in ()).throw(ValueError("encrypt failed")))
    with pytest.raises(ValueError):
        store.save(connection)
    assert store.path.read_bytes() == previous
    store.clear()
    assert not store.path.exists()


@pytest.mark.parametrize("url", ["file:///private", "https://u:p@example.test", "https://example.test?key=x", "https://example.test/#x", "https://example.test:invalid"])
def test_bad_endpoints_are_rejected_without_echoing_secret(url):
    with pytest.raises(ValueError, match="ai_api_invalid_url") as error:
        AIConnection.validated(url, "reason", "chat", "hidden-test-key")
    assert "hidden-test-key" not in str(error.value)


def test_corrupt_configuration_fails_without_falling_back_or_overwriting(tmp_path):
    path = tmp_path / "ai-services.json"
    path.write_text('{"protected_key":"bad"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ai_api_config_unreadable"):
        AIConfigurationStore(path).load()
    assert path.read_text(encoding="utf-8") == '{"protected_key":"bad"}'


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_windows_dpapi_round_trip_and_tampering(tmp_path):
    store = AIConfigurationStore(tmp_path / "ai-services.json")
    connection = AIConnection.validated("http://127.0.0.1:1234/v1", "model", "model", "dummy-local-DPAPI-key")
    store.save(connection)
    assert b"dummy-local-DPAPI-key" not in store.path.read_bytes()
    assert store.load() == connection
    encrypted = module._crypt(b"secret-dummy")
    with pytest.raises(ValueError):
        module._crypt(encrypted[:-5], decrypt=True)
