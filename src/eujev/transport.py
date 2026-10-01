"""Standard-library HTTP transport and interfaces for custom transports."""

from __future__ import annotations

import ssl
from email.message import Message
from typing import Any, Protocol, cast
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class HTTPResponse(Protocol):
    """A streaming response; the SDK always closes it after reading."""

    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Message: ...

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class Transport(Protocol):
    """Send exactly one request without retries or following redirects.

    Return non-2xx responses normally. Implementations must be thread-safe to
    share a Client across threads, and must honor timeout (seconds, or None).
    The caller owns the transport; the SDK only closes individual responses.
    """

    def send(self, request: Request, *, timeout: float | None) -> HTTPResponse: ...


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        return None


class HTTPTransport:
    """urllib transport with redirects disabled and optional TLS configuration.

    Each send creates its own opener, so requests do not share mutable handler
    state. urllib's usual proxy environment variables are respected.
    """

    def __init__(self, *, ssl_context: ssl.SSLContext | None = None) -> None:
        self._ssl_context = ssl_context

    def send(self, request: Request, *, timeout: float | None) -> HTTPResponse:
        opener = build_opener(_NoRedirects(), HTTPSHandler(context=self._ssl_context))
        try:
            return cast(HTTPResponse, opener.open(request, timeout=timeout))
        except HTTPError as error:
            # urllib uses an exception for HTTP failures; its body is still a stream.
            return cast(HTTPResponse, error)
