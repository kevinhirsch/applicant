"""lens 12 #30 — humanize model-endpoint ping errors.

``_fetch_models`` used to return ``str(exc)`` verbatim as ``ping_error``, which the
admin/onboarding UI shows straight to the user ("Offline — ${d.ping_error}"),
leaking raw socket/TLS exception text. It must instead return a plain-language,
actionable message and never the raw exception text (the raw detail still goes
to the log line, not the returned value).
"""

from __future__ import annotations

import json

import httpx
import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.model_endpoint_service import (
    ModelEndpointService,
    _humanize_ping_error,
)


def _service(transport: httpx.BaseTransport) -> ModelEndpointService:
    return ModelEndpointService(config_store=InMemoryAppConfigStore(), transport=transport)


def _raising_transport(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise exc

    return httpx.MockTransport(handler)


# === direct unit mapping ====================================================
def test_connect_refused_maps_to_plain_message():
    exc = httpx.ConnectError("[Errno 111] Connection refused")
    msg = _humanize_ping_error(exc)
    assert msg == "Couldn't reach the server — is it running and the address right?"
    assert "Errno 111" not in msg
    assert "Connection refused" not in msg


def test_dns_failure_maps_to_address_message():
    exc = httpx.ConnectError(
        "[Errno -2] Name or service not known: getaddrinfo failed for host.invalid"
    )
    msg = _humanize_ping_error(exc)
    assert msg == "Couldn't find that server address."
    assert "Errno" not in msg
    assert "host.invalid" not in msg


def test_timeout_maps_to_plain_message():
    for exc in (
        httpx.ConnectTimeout("timed out connecting to 10.0.0.5:8080 after 30s"),
        httpx.ReadTimeout("timed out reading response from 10.0.0.5:8080"),
    ):
        msg = _humanize_ping_error(exc)
        assert msg == "The server didn't respond in time."
        assert "10.0.0.5" not in msg


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://example.invalid/v1/models")
    response = httpx.Response(status, request=request, text="secret-trace-detail")
    return httpx.HTTPStatusError(f"{status} error", request=request, response=response)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejection_maps_to_plain_message(status):
    msg = _humanize_ping_error(_status_error(status))
    assert msg == "The server rejected the API key."
    assert "secret-trace-detail" not in msg


def test_unmapped_http_status_falls_back_to_generic_message():
    msg = _humanize_ping_error(_status_error(500))
    assert msg == "Couldn't reach the model server."
    assert "secret-trace-detail" not in msg


def test_json_decode_error_falls_back_to_generic_message():
    exc = json.JSONDecodeError("Expecting value", "not json {internal-detail}", 0)
    msg = _humanize_ping_error(exc)
    assert msg == "Couldn't reach the model server."
    assert "internal-detail" not in msg


# === end-to-end through the service (raw text never reaches ping_error) ====
def test_fetch_models_never_leaks_raw_exception_text():
    raw = "[Errno 111] Connection refused while connecting to 10.9.9.9:1234"
    svc = _service(_raising_transport(httpx.ConnectError(raw)))
    models, online, error = svc._fetch_models("http://10.9.9.9:1234/v1", "")
    assert models == []
    assert online is False
    assert error == "Couldn't reach the server — is it running and the address right?"
    assert "10.9.9.9" not in error
    assert "Errno" not in error


def test_test_endpoint_surfaces_humanized_timeout_error():
    svc = _service(_raising_transport(httpx.ConnectTimeout("connect timed out after 30.0s")))
    result = svc.test_endpoint(base_url="https://example.invalid/v1")
    assert result["online"] is False
    assert result["ping_error"] == "The server didn't respond in time."
    assert "30.0s" not in result["ping_error"]


def test_add_endpoint_surfaces_humanized_auth_error():
    svc = _service(_raising_transport(_status_error(401)))
    result = svc.add_endpoint(base_url="https://example.invalid/v1", api_key="bad-key")
    assert result["online"] is False
    assert result["ping_error"] == "The server rejected the API key."
