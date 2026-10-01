"""Exceptions raised by the SDK."""

from __future__ import annotations

from copy import deepcopy
from email.message import Message
from http import HTTPStatus

from ._json import loads


class EujevError(Exception):
    """Base class for errors raised while making a decision."""


class RequestError(EujevError):
    """The request could not be encoded as JSON; no request was sent."""


class TransportError(EujevError):
    """Sending the HTTP request failed. __cause__ retains the original error."""


class ResponseError(EujevError):
    """Reading or decoding a successful response failed."""


class ResponseTooLargeError(ResponseError):
    """A response exceeded the 4 MiB read limit."""

    def __init__(self) -> None:
        super().__init__("eujev: response body exceeds 4 MiB")


class APIError(EujevError):
    """A non-2xx HTTP response, including redirects and non-JSON errors.

    body contains at most 4 MiB of raw bytes. headers is a case-insensitive
    email.message.Message, retaining repeated headers. A read error or size
    limit error, if present, is available as __cause__.
    """

    def __init__(
        self,
        status_code: int,
        body: bytes,
        headers: Message,
        *,
        body_truncated: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = deepcopy(headers)
        self.body = body
        self.body_truncated = body_truncated
        self.request_id = headers.get("X-Request-ID", "")
        self.retry_after = headers.get("Retry-After", "")
        self.message = ""
        self.code = ""
        self.contact_url = ""
        try:
            payload = loads(body)
        except (ValueError, UnicodeError, RecursionError):
            payload = None
        if isinstance(payload, dict) and all(
            payload.get(key) is None or isinstance(payload[key], str)
            for key in ("error", "code", "contact_url")
        ):
            self.message = payload.get("error") or ""
            self.code = payload.get("code") or ""
            self.contact_url = payload.get("contact_url") or ""
        if not self.message:
            try:
                self.message = HTTPStatus(status_code).phrase
            except ValueError:
                pass
        diagnostic = f"eujev: HTTP {status_code}"
        if self.code:
            diagnostic += f" ({self.code})"
        if self.message:
            diagnostic += f": {self.message}"
        if self.request_id:
            diagnostic += f" [request_id={self.request_id}]"
        super().__init__(diagnostic)

    @property
    def body_text(self) -> str:
        """The raw body decoded as UTF-8, replacing invalid sequences."""
        return self.body.decode("utf-8", errors="replace")
