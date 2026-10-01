"""Run without an API key or network access using a custom transport."""

import io
import json
from email.message import Message
from urllib.request import Request

from eujev import Client, DecisionRequest, HTTPResponse, NoulQuestion


class DemoResponse(io.BytesIO):
    def __init__(self) -> None:
        super().__init__(
            json.dumps(
                {
                    "model": "offline-demo",
                    "answers": {"refund": {"type": "noul", "noul": 0.98}},
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                    "meta": {"mode": "demo", "latency_ms": 0, "cost_eur": "0"},
                }
            ).encode()
        )
        self.status = 200
        self.headers = Message()
        self.headers["X-Request-ID"] = "offline-example"


class DemoTransport:
    def send(self, request: Request, *, timeout: float | None) -> HTTPResponse:
        # A real custom transport would send this request exactly once, honor
        # timeout, and return the response without following redirects.
        if not isinstance(request.data, bytes):
            raise TypeError("Expected a byte-encoded JSON request")
        print("Outgoing JSON:", request.data.decode())
        return DemoResponse()


def main() -> None:
    client = Client("unused-demo-key", transport=DemoTransport())
    response = client.decide(
        DecisionRequest(
            state="I was charged twice. Can I get a refund?",
            questions={"refund": NoulQuestion("Does this require a refund?")},
        )
    )
    print("Refund probability:", response.answers["refund"].noul)
    print("Request ID:", response.meta.request_id)
    print(json.dumps(response.to_dict(), indent=2))


if __name__ == "__main__":
    main()
