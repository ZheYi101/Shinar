import asyncio

import httpx
import pytest

from shinar.infrastructure.ai_configuration import AIConnection
from shinar.providers.service_probe import probe_models


def test_metadata_probe_never_calls_chat_or_sends_learning_content():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"id": "reason"}, {"id": "chat"}, {"id": "chat"}]})

    connection = AIConnection.validated("https://example.test/v1", "reason", "chat", "dummy-only")
    models = asyncio.run(probe_models(connection, transport=httpx.MockTransport(respond)))
    assert models == ["chat", "reason"] and len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.path == "/v1/models"
    assert calls[0].content == b"" and calls[0].headers["authorization"] == "Bearer dummy-only"


@pytest.mark.parametrize("status,code", [(401, "auth_failed"), (404, "models_unsupported"), (429, "rate_limited"), (302, "connection_failed")])
def test_auth_failures_and_redirects_are_sanitized(status, code):
    def respond(request):
        return httpx.Response(status, headers={"Location": "https://untrusted.test"}, text="do-not-echo-this-response")

    connection = AIConnection.validated("https://example.test/v1", "r", "c", "dummy-only")
    with pytest.raises(ValueError, match="ai_api_" + code) as error:
        asyncio.run(probe_models(connection, transport=httpx.MockTransport(respond)))
    assert "dummy-only" not in str(error.value) and "do-not-echo" not in str(error.value)


def test_catalog_filters_invalid_ids_without_inventing_models():
    connection = AIConnection.validated("https://example.test/v1", "r", "c", "dummy-only")
    rows = [None, {"id": 42}, {"id": ""}, {"id": " bad "}, {"id": "bad\nmodel"},
            {"id": "x" * 257}, {"id": "provider/model-v1"}, {"id": "a"}, {"id": "a"}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": rows}))
    assert asyncio.run(probe_models(connection, transport=transport)) == ["a", "provider/model-v1"]
