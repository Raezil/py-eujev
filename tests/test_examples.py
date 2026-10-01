from __future__ import annotations

import io
import json
import runpy
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ExampleResponse(io.BytesIO):
    def __init__(self, payload, *, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = Message()
        self.headers["X-Request-ID"] = "example-test"
        self.headers["Retry-After"] = "30"


class ExampleTests(unittest.TestCase):
    def test_offline_demo_needs_no_key_or_network(self):
        output = io.StringIO()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("eujev.HTTPTransport.send", side_effect=AssertionError("unexpected HTTP call")),
            redirect_stdout(output),
        ):
            runpy.run_path(str(EXAMPLES / "offline.py"), run_name="__main__")
        self.assertIn("Refund probability: 0.98", output.getvalue())
        self.assertIn("offline-example", output.getvalue())

    def test_live_examples_with_intercepted_http(self):
        payload = {
            "model": "jeff-1.0.0",
            "answers": {
                "team": {"type": "choice", "choice": "billing"},
                "refund": {"type": "noul", "noul": 0},
                "urgency": {"type": "score", "score": 0, "legend": {"0": "Routine"}},
            },
            "meta": {"cost_eur": "0.000002368"},
        }
        for name, expected in (
            ("refund.py", "billing"),
            ("all_question_types.py", "Refund probability: 0.0%"),
            ("handle_errors.py", "Refund probability: 0.0"),
        ):
            with self.subTest(example=name):
                response = ExampleResponse(payload)
                output = io.StringIO()
                with (
                    patch.dict("os.environ", {"EU_JEV_API_KEY": "example-key"}, clear=True),
                    patch("eujev.HTTPTransport.send", return_value=response) as send,
                    redirect_stdout(output),
                ):
                    runpy.run_path(str(EXAMPLES / name), run_name="__main__")
                self.assertIn(expected, output.getvalue())
                send.assert_called_once()
                self.assertTrue(response.closed)

    def test_error_example_reports_api_failure_and_retry_header(self):
        output = io.StringIO()
        response = ExampleResponse({"error": "Rate limited", "code": "rate_limited"}, status=429)
        with (
            patch.dict("os.environ", {"EU_JEV_API_KEY": "example-key"}, clear=True),
            patch("eujev.HTTPTransport.send", return_value=response),
            redirect_stderr(output),
            self.assertRaises(SystemExit) as caught,
        ):
            runpy.run_path(str(EXAMPLES / "handle_errors.py"), run_name="__main__")
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("HTTP 429: Rate limited", output.getvalue())
        self.assertIn("Retry-After: 30", output.getvalue())
        self.assertIn("example-test", output.getvalue())


if __name__ == "__main__":
    unittest.main()
