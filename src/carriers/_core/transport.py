"""HTTP transport: a protocol, and a dependency-free urllib implementation.

Keeping the transport behind a Protocol is what lets the whole test suite run
without a network, and lets a caller swap in ``requests``/``httpx`` without
either carrier package knowing.
"""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol

from .errors import CarrierTransportError


def decode_response_body(raw: bytes, headers: Mapping[str, str]) -> str:
    """Decode a response body, decompressing first when the server compressed it.

    The magic-byte sniff backs up the Content-Encoding header rather than
    trusting either alone, so gzipped bodies decode even when mislabeled.
    """
    encoding = ""
    for name, value in headers.items():
        if name.lower() == "content-encoding":
            encoding = (value or "").lower()
            break
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            # Some servers send raw deflate with no zlib header.
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> object:
        if not self.text:
            return None
        return json.loads(self.text)


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
    ) -> HttpResponse:
        ...

    def close(self) -> None:
        ...


class UrlLibTransport:
    """Small urllib-based transport to keep the SDK dependency-free."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
    ) -> HttpResponse:
        req = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                headers_map = dict(response.headers.items())
                payload = decode_response_body(response.read(), headers_map)
                return HttpResponse(
                    status_code=response.status,
                    headers=headers_map,
                    text=payload,
                )
        except urllib.error.HTTPError as exc:
            # An HTTPError is still a response — the carrier answered, just
            # with a 4xx/5xx. The client turns it into a typed error.
            headers_map = dict(exc.headers.items())
            payload = decode_response_body(exc.read(), headers_map)
            return HttpResponse(
                status_code=exc.code,
                headers=headers_map,
                text=payload,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CarrierTransportError(
                f"{method.upper()} {url} failed before a response was received: {exc}",
                cause=exc,
            ) from exc

    def close(self) -> None:
        return None


__all__ = ["HttpResponse", "Transport", "UrlLibTransport", "decode_response_body"]
