"""Shared test doubles.

Every suite in this repo runs without a network. ``FakeTransport`` satisfies
the ``carriers._core.transport.Transport`` protocol and hands back a scripted
list of responses, recording each request so assertions can inspect the URL,
headers and body the client actually built.
"""
from __future__ import annotations

import json

from carriers._core.errors import CarrierTransportError
from carriers._core.transport import HttpResponse


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.closed = False

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self):
        self.closed = True


def json_response(status, payload, headers=None):
    response_headers = {"Content-Type": "application/json"}
    if headers:
        response_headers.update(headers)
    return HttpResponse(status, response_headers, json.dumps(payload))


def transport_error(message="connection reset"):
    return CarrierTransportError(message)


class RecordingSleep:
    """Stands in for ``time.sleep`` so retry tests are instant."""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


__all__ = ["FakeTransport", "RecordingSleep", "json_response", "transport_error"]
