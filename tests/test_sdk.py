from __future__ import annotations

import io
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from email.message import Message
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import URLError

from eujev import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    MAX_RESPONSE_BYTES,
    APIError,
    ChoiceQuestion,
    Client,
    DecisionRequest,
    DecisionResponse,
    NoulQuestion,
    QuestionType,
    RequestError,
    ResponseError,
    ResponseTooLargeError,
    ScoreQuestion,
    TransportError,
)

# Same response fixture used by eujev-go/client_test.go.
CHOICE_RESPONSE = b"""{
    "model":"jeff-1.0.0",
    "answers":{"team":{"type":"choice","choice":"billing","confidence":0.9,
        "probabilities":{"billing":0.95,"support":0.05}}},
    "usage":{"input_tokens":64,"output_tokens":0},
    "meta":{"request_id":"8febf2e9-1643-4446-a7cf-7fc3bcf2b391",
        "mode":"live","latency_ms":180,"cost_eur":"0.000002368"}
}"""

REFUND_PAYLOAD = {
    "model": "jeff-latest",
    "state": "I was charged twice. Can I get a refund?",
    "questions": {
        "team": {
            "type": "choice",
            "instructions": "Which team should handle this?",
            "criteria": {
                "billing": "Payments, invoices, and refunds",
                "support": "Technical issues and bugs",
            },
        },
    },
}


def refund_request():
    return DecisionRequest(
        state=REFUND_PAYLOAD["state"],
        questions={
            "team": ChoiceQuestion(
                instructions="Which team should handle this?",
                criteria={
                    "billing": "Payments, invoices, and refunds",
                    "support": "Technical issues and bugs",
                },
            ),
        },
    )


class MemoryResponse(io.BytesIO):
    def __init__(self, body=CHOICE_RESPONSE, *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.bytes_read = 0

    def read(self, size=-1):
        result = super().read(size)
        self.bytes_read += len(result)
        return result


class MemoryTransport:
    def __init__(self, body=CHOICE_RESPONSE, *, status=200, headers=None, failure=None):
        self.body = body
        self.status = status
        self.headers = headers
        self.failure = failure
        self.calls = []
        self.response = None

    def send(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.failure is not None:
            raise self.failure
        self.response = MemoryResponse(self.body, status=self.status, headers=self.headers)
        return self.response


@contextmanager
def server(*, body=CHOICE_RESPONSE, status=200, headers=None, delay=0):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(
                (
                    self.command,
                    self.path,
                    self.headers,
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            if delay:
                time.sleep(delay)
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            if "Content-Length" not in (headers or {}):
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.do_POST()

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class QuestionTests(unittest.TestCase):
    def test_question_wire_formats_match_go(self):
        cases = [
            (
                ChoiceQuestion(
                    instructions={"task": "Route this message"},
                    criteria={"billing": None, "support": ["technical", "bugs"]},
                ),
                {
                    "type": "choice",
                    "instructions": {"task": "Route this message"},
                    "criteria": {"billing": None, "support": ["technical", "bugs"]},
                },
            ),
            (NoulQuestion(), {"type": "noul", "instructions": None}),
            (NoulQuestion(criteria={}), {"type": "noul", "instructions": None}),
            (
                NoulQuestion(
                    "Does this require a refund?", {"true": "Refund needed", "false": None}
                ),
                {
                    "type": "noul",
                    "instructions": "Does this require a refund?",
                    "criteria": {"true": "Refund needed", "false": None},
                },
            ),
            (
                ScoreQuestion(["Rate the urgency"], ["low", {"label": "high"}, None]),
                {
                    "type": "score",
                    "instructions": ["Rate the urgency"],
                    "criteria": ["low", {"label": "high"}, None],
                },
            ),
            (ChoiceQuestion(), {"type": "choice", "instructions": None, "criteria": None}),
            (ScoreQuestion(), {"type": "score", "instructions": None, "criteria": None}),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                self.assertEqual(json.loads(json.dumps(question.to_dict())), expected)

    def test_default_model_and_serialization_do_not_mutate_request(self):
        request = refund_request()
        original = deepcopy(request)
        self.assertEqual(request.to_dict(), REFUND_PAYLOAD)
        self.assertEqual(request, original)
        request.model = "jeff-1.0.0"
        self.assertEqual(request.to_dict()["model"], "jeff-1.0.0")

    def test_unserializable_input_never_reaches_transport(self):
        circular = []
        circular.append(circular)
        for value in (object(), {1, 2}, float("nan"), float("inf"), circular, "\ud800"):
            for field in ("state", "instructions", "criteria"):
                with self.subTest(value=repr(value), field=field):
                    request = refund_request()
                    if field == "state":
                        request.state = value
                    elif field == "instructions":
                        request.questions["team"].instructions = value
                    else:
                        request.questions["team"].criteria = {"billing": value}
                    transport = MemoryTransport()
                    with self.assertRaises(RequestError) as caught:
                        Client("key", transport=transport).decide(request)
                    self.assertIsNotNone(caught.exception.__cause__)
                    self.assertEqual(transport.calls, [])


class ResponseTests(unittest.TestCase):
    def test_choice_response_and_exact_cost(self):
        transport = MemoryTransport(headers={"X-Request-ID": "header-id"})
        response = Client("key", transport=transport).decide(refund_request())
        self.assertEqual(response.to_dict(), json.loads(CHOICE_RESPONSE))
        answer = response.answers["team"]
        self.assertEqual(answer.type, QuestionType.CHOICE)
        self.assertEqual(answer.choice, "billing")
        self.assertEqual(answer.confidence, 0.9)
        self.assertIsNone(answer.score)
        self.assertIsNone(answer.noul)
        self.assertEqual(response.meta.cost_eur, "0.000002368")
        self.assertEqual(response.usage.input_tokens, 64)
        self.assertEqual(response.usage.output_tokens, 0)
        self.assertTrue(transport.response.closed)

    def test_noul_score_zero_and_header_request_id(self):
        payload = {
            "answers": {
                "urgent": {"type": "noul", "noul": 0},
                "severity": {
                    "type": "score",
                    "score": 0,
                    "confidence": 0,
                    "probabilities": {"0": 1, "1": 0, "2": 0},
                    "legend": {"0": "low", "1": "medium", "2": "high"},
                },
            },
        }
        transport = MemoryTransport(
            json.dumps(payload).encode(), headers={"x-request-id": "fallback"}
        )
        response = Client("key", transport=transport).decide(refund_request())
        self.assertEqual(response.meta.request_id, "fallback")
        self.assertEqual(response.answers["urgent"].to_dict(), {"type": "noul", "noul": 0})
        self.assertEqual(response.answers["severity"].to_dict(), payload["answers"]["severity"])
        self.assertIsNone(response.answers["urgent"].score)

    def test_missing_null_and_unknown_fields_match_go(self):
        response = DecisionResponse.from_dict(
            {
                "model": None,
                "usage": None,
                "meta": {"cost_eur": None},
                "answers": {"future": {"type": "future", "new_field": True}, "null": None},
                "new_field": {},
            }
        )
        self.assertEqual(response.model, "")
        self.assertEqual(response.usage.input_tokens, 0)
        self.assertEqual(response.meta.cost_eur, "")
        self.assertEqual(response.answers["future"].type, "future")
        self.assertIsNone(response.answers["null"].noul)
        first, second = DecisionResponse(), DecisionResponse()
        first.meta.mode = "test"
        self.assertEqual(second.meta.mode, "")

    def test_invalid_success_responses_close_body(self):
        cases = [
            b"",
            b"null",
            b"[]",
            b"42",
            b"not JSON",
            b"\xff",
            CHOICE_RESPONSE + b"{}",
            b'{"model":42}',
            b'{"usage":[]}',
            b'{"meta":{"cost_eur":0.01}}',
            b'{"answers":[]}',
            b'{"answers":{"a":{"score":"1"}}}',
            b'{"answers":{"a":{"score":true}}}',
            b'{"answers":{"a":{"noul":1e999}}}',
            b'{"answers":{"a":{"confidence":NaN}}}',
            b'{"answers":{"a":{"legend":[]}}}',
            b'{"answers":{"a":{"probabilities":{"x":"0.5"}}}}',
            b'{"usage":{"input_tokens":true}}',
            b'{"usage":{"input_tokens":1.5}}',
            b'{"usage":{"input_tokens":9223372036854775808}}',
        ]
        for body in cases:
            with self.subTest(body=body[:80]):
                transport = MemoryTransport(body)
                with self.assertRaises(ResponseError) as caught:
                    Client("key", transport=transport).decide(refund_request())
                self.assertIsNotNone(caught.exception.__cause__)
                self.assertTrue(transport.response.closed)


class ErrorTests(unittest.TestCase):
    def test_api_errors_keep_diagnostics_and_do_not_retry(self):
        body = b'{"error":"Request rejected","code":"example_code","contact_url":"https://x.test"}'
        for status in (300, 400, 401, 402, 413, 415, 422, 429, 503):
            with self.subTest(status=status):
                transport = MemoryTransport(
                    body, status=status, headers={"X-Request-ID": "error-id", "Retry-After": "30"}
                )
                with self.assertRaises(APIError) as caught:
                    Client("key", transport=transport).decide(refund_request())
                error = caught.exception
                self.assertEqual(error.status_code, status)
                self.assertEqual(error.message, "Request rejected")
                self.assertEqual(error.code, "example_code")
                self.assertEqual(error.contact_url, "https://x.test")
                self.assertEqual(error.request_id, "error-id")
                self.assertEqual(error.retry_after, "30")
                self.assertEqual(error.headers["retry-after"], "30")
                self.assertEqual(error.body, body)
                self.assertEqual(error.body_text, body.decode())
                self.assertFalse(error.body_truncated)
                self.assertIsNone(error.__cause__)
                self.assertIn("example_code", str(error))
                self.assertIn("error-id", str(error))
                self.assertEqual(len(transport.calls), 1)
                self.assertTrue(transport.response.closed)

    def test_non_json_or_invalid_api_error_schema(self):
        for body in (
            b"<html>Bad gateway</html>",
            b"",
            b'{"error":123}',
            b'{"error":"partial"',
            b"null",
            b"[]",
            b"\xff",
            b'{"error":"partial","code":42}',
            b'{"error":"partial","unknown":NaN}',
        ):
            with self.subTest(body=body):
                transport = MemoryTransport(body, status=502)
                with self.assertRaises(APIError) as caught:
                    Client("key", transport=transport).decide(refund_request())
                self.assertEqual(caught.exception.message, "Bad Gateway")
                self.assertEqual(caught.exception.code, "")
                self.assertEqual(caught.exception.body, body)

    def test_headers_are_copied_and_repeated_headers_preserved(self):
        headers = Message()
        headers["X-Trace"] = "one"
        headers["X-Trace"] = "two"
        error = APIError(599, b"", headers)
        headers["Another"] = "new"
        self.assertEqual(error.headers.get_all("x-trace"), ["one", "two"])
        self.assertNotIn("Another", error.headers)
        self.assertEqual(str(error), "eujev: HTTP 599")

    def test_response_limit_bounds_reads_and_retains_http_errors(self):
        for status in (200, 502):
            with self.subTest(status=status):
                transport = MemoryTransport(b"x" * (MAX_RESPONSE_BYTES + 100), status=status)
                expected = ResponseTooLargeError if status == 200 else APIError
                with self.assertRaises(expected) as caught:
                    Client("key", transport=transport).decide(refund_request())
                self.assertEqual(transport.response.bytes_read, MAX_RESPONSE_BYTES + 1)
                self.assertTrue(transport.response.closed)
                if status == 502:
                    self.assertIsInstance(caught.exception.__cause__, ResponseTooLargeError)
                    self.assertTrue(caught.exception.body_truncated)
                    self.assertEqual(len(caught.exception.body), MAX_RESPONSE_BYTES)

    def test_response_at_exact_size_limit_succeeds(self):
        body = CHOICE_RESPONSE + b" " * (MAX_RESPONSE_BYTES - len(CHOICE_RESPONSE))
        transport = MemoryTransport(body)
        response = Client("key", transport=transport).decide(refund_request())
        self.assertEqual(response.answers["team"].choice, "billing")
        self.assertTrue(transport.response.closed)

    def test_close_failure_does_not_hide_response_or_api_error(self):
        class CloseFailureResponse(MemoryResponse):
            def close(self):
                super().close()
                raise OSError("close failed")

        for status in (200, 503):
            with self.subTest(status=status):
                response = CloseFailureResponse(status=status)
                transport = MemoryTransport()
                with patch.object(transport, "send", return_value=response):
                    client = Client("key", transport=transport)
                    if status == 200:
                        self.assertEqual(
                            client.decide(refund_request()).answers["team"].choice, "billing"
                        )
                    else:
                        with self.assertRaises(APIError) as caught:
                            client.decide(refund_request())
                        self.assertEqual(caught.exception.status_code, 503)
                self.assertTrue(response.closed)

    def test_body_read_failures_retain_partial_data_and_close(self):
        for status in (200, 503):
            for failure in (OSError("broken stream"), IncompleteRead(b"tail", 10)):
                with self.subTest(status=status, failure=failure):

                    class BrokenResponse(MemoryResponse):
                        def read(self, size=-1, failure=failure):
                            if self.tell() == 0:
                                return super().read(size)
                            raise failure

                    response = BrokenResponse(b"prefix", status=status)

                    class BrokenTransport:
                        def send(self, request, *, timeout, response=response):
                            return response

                    expected = ResponseError if status == 200 else APIError
                    with self.assertRaises(expected) as caught:
                        Client("key", transport=BrokenTransport()).decide(refund_request())
                    self.assertIs(caught.exception.__cause__, failure)
                    self.assertTrue(response.closed)
                    if status == 503:
                        expected_body = (
                            b"prefixtail" if isinstance(failure, IncompleteRead) else b"prefix"
                        )
                        self.assertEqual(caught.exception.body, expected_body)
                        self.assertFalse(caught.exception.body_truncated)

    def test_transport_error_keeps_cause(self):
        for failure in (URLError("offline"), TimeoutError("timeout"), ConnectionResetError()):
            with self.subTest(failure=failure):
                transport = MemoryTransport(failure=failure)
                with self.assertRaises(TransportError) as caught:
                    Client("key", transport=transport).decide(refund_request())
                self.assertIs(caught.exception.__cause__, failure)
                self.assertEqual(len(transport.calls), 1)


class ConfigurationTests(unittest.TestCase):
    def test_reject_invalid_keys(self):
        for key in ("", "  ", "Bearer key", "a\r\nb", "a\x7fb", "a\x01b", "klucz-ą", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Client(key)

    def test_reject_invalid_urls(self):
        for url in (
            "",
            "not-a-url",
            "//example.com",
            "ftp://example.com",
            "https://",
            "https://a:b@example.com",
            "https://example.com?q=1",
            "https://example.com?",
            "https://example.com#fragment",
            "https://example.com#",
            "http://[::1",
            "https://example.com:abc",
            "https://example.com:65536",
            "https://exam ple.com",
            "\nhttps://example.com",
            "https://example.com/path\nnext",
            "https://a\\b",
            None,
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Client("key", base_url=url)

    def test_default_endpoint_authentication_and_timeout_overrides(self):
        transport = MemoryTransport()
        client = Client(" key\n", transport=transport)
        client.decide(refund_request())
        request, timeout = transport.calls[0]
        self.assertEqual(request.full_url, DEFAULT_BASE_URL + "/v1/systemone")
        self.assertEqual(request.get_header("Authorization"), "Bearer key")
        self.assertEqual(timeout, DEFAULT_TIMEOUT)
        self.assertEqual(json.loads(request.data)["model"], DEFAULT_MODEL)
        client.decide(refund_request(), timeout=3)
        client.decide(refund_request(), timeout=None)
        client.decide(refund_request())
        self.assertEqual([value for _, value in transport.calls], [60, 3, None, 60])
        self.assertNotIn("key", repr(client))

    def test_reject_invalid_timeouts_before_network(self):
        for timeout in (0, -1, True, float("nan"), float("inf"), "10"):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    Client("key", timeout=timeout)
                transport = MemoryTransport()
                with self.assertRaises(ValueError):
                    Client("key", transport=transport).decide(refund_request(), timeout=timeout)
                self.assertEqual(transport.calls, [])


class HTTPIntegrationTests(unittest.TestCase):
    def test_actual_http_request_matches_go(self):
        with server() as (url, calls):
            request = refund_request()
            response = Client("test-api-key", base_url=url + "/").decide(request)
        self.assertEqual(len(calls), 1)
        method, path, headers, body = calls[0]
        self.assertEqual((method, path), ("POST", "/v1/systemone"))
        self.assertEqual(headers["Authorization"], "Bearer test-api-key")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["User-Agent"], "py-eujev/0.1.0")
        self.assertEqual(json.loads(body), REFUND_PAYLOAD)
        self.assertEqual(response.answers["team"].choice, "billing")
        self.assertEqual(request.model, "")

    def test_proxy_path_custom_model_and_structured_state(self):
        for state in ({"message": "Cześć 世界", "history": []}, ["Cześć", {"history": []}]):
            with self.subTest(state=state), server() as (url, calls):
                request = DecisionRequest(
                    state=state,
                    model="jeff-1.0.0",
                    questions={
                        "urgent": NoulQuestion("Is it urgent?"),
                        "severity": ScoreQuestion("How severe?", ["low", "medium", "high"]),
                    },
                )
                Client("key", base_url=url + "/proxy///").decide(request)
                self.assertEqual(calls[0][1], "/proxy/v1/systemone")
                self.assertEqual(json.loads(calls[0][3]), request.to_dict())

    def test_redirects_never_forward_credentials_or_retry(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status), server() as (destination, destination_calls):
                with server(status=status, headers={"Location": destination + "/other"}) as (
                    url,
                    calls,
                ):
                    with self.assertRaises(APIError) as caught:
                        Client("secret-key", base_url=url).decide(refund_request())
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertEqual(len(calls), 1)
                self.assertEqual(destination_calls, [])

    def test_real_http_error(self):
        with server(
            status=429,
            body=b'{"error":"Too many requests","code":"rate_limited"}',
            headers={"Retry-After": "30", "X-Request-ID": "real-id"},
        ) as (url, calls):
            with self.assertRaises(APIError) as caught:
                Client("key", base_url=url).decide(refund_request())
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(caught.exception.retry_after, "30")
            self.assertEqual(caught.exception.request_id, "real-id")
            self.assertEqual(len(calls), 1)

    def test_socket_timeout(self):
        with server(delay=0.15) as (url, calls):
            with self.assertRaises(TransportError) as caught:
                Client("key", base_url=url, timeout=0.02).decide(refund_request())
            self.assertIsInstance(caught.exception.__cause__, (TimeoutError, URLError))
            self.assertEqual(len(calls), 1)

    def test_incomplete_content_length(self):
        for status in (200, 503):
            with (
                self.subTest(status=status),
                server(body=b"partial", status=status, headers={"Content-Length": "100"}) as (
                    url,
                    _,
                ),
            ):
                expected = ResponseError if status == 200 else APIError
                with self.assertRaises(expected) as caught:
                    Client("key", base_url=url).decide(refund_request())
                self.assertIsInstance(caught.exception.__cause__, IncompleteRead)
                if status == 503:
                    self.assertEqual(caught.exception.body, b"partial")

    def test_shared_client_concurrent_calls(self):
        with server() as (url, calls):
            client = Client("key", base_url=url)
            request = refund_request()
            with ThreadPoolExecutor(max_workers=8) as executor:
                responses = list(executor.map(lambda _: client.decide(request), range(16)))
            self.assertEqual(len(calls), 16)
            self.assertTrue(
                all(response.answers["team"].choice == "billing" for response in responses)
            )
            self.assertEqual(request.model, "")


if __name__ == "__main__":
    unittest.main()
