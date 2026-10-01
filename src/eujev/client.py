"""Synchronous client for the eu/jev System One API."""

from __future__ import annotations

import json
import math
import re
from contextlib import suppress
from http.client import HTTPException, IncompleteRead
from urllib.parse import urlsplit
from urllib.request import Request

from ._constants import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, MAX_RESPONSE_BYTES
from ._json import loads
from .errors import APIError, RequestError, ResponseError, ResponseTooLargeError, TransportError
from .transport import HTTPResponse, HTTPTransport, Transport
from .types import DecisionRequest, DecisionResponse


class _Unset:
    pass


_UNSET = _Unset()


def _validate_timeout(timeout: float | None) -> None:
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("eujev: timeout must be a positive number of seconds or None")


def _endpoint(base_url: str) -> str:
    message = "eujev: base URL must be an HTTP(S) URL without credentials, a query, or a fragment"
    if not isinstance(base_url, str) or re.search(r"[\x00-\x20\x7f\\?#]", base_url):
        raise ValueError(message)
    try:
        url = urlsplit(base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
        ):
            raise ValueError(message)
        # Accessing port validates malformed and out-of-range ports.
        _ = url.port
    except ValueError as error:
        raise ValueError(message) from error
    return base_url.rstrip("/") + "/v1/systemone"


class Client:
    """Authenticated System One client with no automatic retries.

    api_key is the token without the Bearer prefix. Leading/trailing whitespace
    is trimmed. timeout controls blocking socket operations, not a total request
    deadline. Pass None to disable it. No persistent connections need closing.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float | None = DEFAULT_TIMEOUT,
        transport: Transport | None = None,
    ) -> None:
        if not isinstance(api_key, str):
            raise ValueError("eujev: API key must be a string")
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("eujev: API key must not be empty")
        if any(ord(character) <= 32 or ord(character) >= 127 for character in api_key):
            raise ValueError("eujev: API key must be an ASCII token without whitespace or controls")
        _validate_timeout(timeout)
        self._api_key = api_key
        self._endpoint = _endpoint(base_url)
        self._timeout = timeout
        self._transport = transport if transport is not None else HTTPTransport()

    def decide(
        self,
        request: DecisionRequest,
        *,
        timeout: float | None | _Unset = _UNSET,
    ) -> DecisionResponse:
        """Submit a decision without modifying the request.

        The optional timeout overrides this call's socket timeout, in seconds.
        Configuration errors raise ValueError. Other failures raise EujevError
        subclasses, with original transport/encoding/decoding errors as causes.
        """
        effective_timeout = self._timeout if isinstance(timeout, _Unset) else timeout
        _validate_timeout(effective_timeout)
        try:
            payload = json.dumps(
                request.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, AttributeError, RecursionError) as error:
            raise RequestError("eujev: encode request") from error
        http_request = Request(
            self._endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "py-eujev/0.1.0",
            },
        )
        try:
            response = self._transport.send(http_request, timeout=effective_timeout)
        except (OSError, HTTPException) as error:
            raise TransportError("eujev: send request") from error
        try:
            body, truncated, read_error = _read_body(response)
            if not 200 <= response.status < 300:
                raise APIError(
                    response.status, body, response.headers, body_truncated=truncated
                ) from read_error
            if read_error is not None:
                if isinstance(read_error, ResponseTooLargeError):
                    raise read_error
                raise ResponseError("eujev: read response") from read_error
            try:
                data = loads(body)
                result = DecisionResponse.from_dict(data)
            except (ValueError, TypeError, OverflowError, RecursionError) as error:
                raise ResponseError("eujev: decode response") from error
            if not result.meta.request_id:
                result.meta.request_id = response.headers.get("X-Request-ID", "")
            return result
        finally:
            # A close failure must not hide an HTTP error or a completed response.
            with suppress(OSError, HTTPException):
                response.close()


def _read_body(response: HTTPResponse) -> tuple[bytes, bool, Exception | None]:
    """Read at most limit+1 bytes, retaining partial bodies and read errors."""
    body = bytearray()
    error: Exception | None = None
    while len(body) <= MAX_RESPONSE_BYTES:
        remaining = MAX_RESPONSE_BYTES + 1 - len(body)
        try:
            chunk = response.read(min(64 * 1024, remaining))
        except IncompleteRead as failure:
            body.extend(failure.partial[:remaining])
            error = failure
            break
        except (OSError, HTTPException) as failure:
            error = failure
            break
        if not chunk:
            break
        body.extend(chunk[:remaining])
    truncated = len(body) > MAX_RESPONSE_BYTES
    if truncated:
        too_large = ResponseTooLargeError()
        too_large.__cause__ = error
        error = too_large
    elif error is None and not response.headers.get("Transfer-Encoding"):
        # HTTPResponse.read(size) can return EOF silently before Content-Length.
        length = response.headers.get("Content-Length", "")
        if length.isascii() and length.isdigit() and int(length) > len(body):
            error = IncompleteRead(bytes(body), int(length) - len(body))
    return bytes(body[:MAX_RESPONSE_BYTES]), truncated, error
