# py-eujev

A typed Python SDK for the [eu/jev System One API](https://jev.bevel.software/docs),
ported from [eujev-go](https://github.com/Raezil/eujev-go). Supports choice, noul
(yes/no probability), and score questions using only the Python standard library.

Requires Python 3.10 or later. The distribution is named `py-eujev`; import it
as `eujev`. This checkout is ready for local installation; it has not been
published to PyPI.

## Install

From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

For another project, run `python -m pip install /absolute/path/to/py-eujev` in
that project's environment. There are no runtime dependencies.

## Quick start

```python
import os

from eujev import ChoiceQuestion, Client, DecisionRequest

client = Client(os.environ["EU_JEV_API_KEY"])
response = client.decide(
    DecisionRequest(
        state="I was charged twice. Can I get a refund?",
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
)

print(response.answers["team"].choice)
print(response.meta.request_id, response.meta.cost_eur)
```

The client sends `POST /v1/systemone` with bearer authentication. An omitted or
empty model uses `jeff-latest`; set `DecisionRequest(model="jeff-1.0.0", ...)`
to select another model. The client does not modify the request.

The SDK takes the key explicitly. The example reads `EU_JEV_API_KEY` from the
environment and prints the full response:

```sh
export EU_JEV_API_KEY='your-api-key'
python examples/refund.py
```

Running the example makes one live request subject to the service's billing.

## Question types and responses

```python
from eujev import DecisionRequest, NoulQuestion, ScoreQuestion

response = client.decide(
    DecisionRequest(
        state={
            "message": "I was charged twice. Can I get a refund?",
            "customer_tier": "premium",
        },
        questions={
            "refund": NoulQuestion(
                instructions="Does this require a refund?",
                criteria={
                    "true": "A duplicate or incorrect charge",
                    "false": "A valid charge",
                },
            ),
            "urgency": ScoreQuestion(
                instructions="How urgently should the team respond?",
                criteria=["Routine", "Soon", "Immediately"],
            ),
        },
    )
)

print(response.answers["refund"].noul)
print(response.answers["urgency"].score)
```

Question classes add their JSON `type` automatically. Instructions and criterion
descriptions can be strings, objects, arrays, or `None`. Noul criteria are optional;
`None` and an empty dictionary omit them. State accepts JSON strings, objects, and
arrays. Values must be serializable by `json.dumps`; nonfinite numbers are rejected.
The service validates question counts and other API constraints, as in the Go SDK.

Answers are keyed by question name. Compare `answer.type` with `QuestionType.CHOICE`,
`QuestionType.NOUL`, or `QuestionType.SCORE` (or their string values):

| Type | Fields |
| --- | --- |
| `choice` | `choice`, `confidence`, `probabilities` |
| `noul` | `noul` (probability from 0 to 1) |
| `score` | `score` (expected position from 0 to N−1), `confidence`, `probabilities`, `legend` |

`noul`, `score`, and `confidence` use `None` for absent values, preserving valid zeros.
`meta.cost_eur` is a decimal string; use `decimal.Decimal` if arithmetic is needed.
`usage` exposes `input_tokens` and `output_tokens`. Metadata includes `request_id`,
`mode`, and `latency_ms`. `X-Request-ID` supplies a fallback if `meta.request_id` is
missing or empty.

Request, question, and response objects provide `to_dict()` for JSON serialization.
`DecisionResponse.from_dict()` parses stored responses. Unknown fields are ignored,
unknown answer type strings are retained, and incorrect types in known fields raise
an error. Absent fields use the Go SDK's zero values.

## HTTP configuration

```python
client = Client(
    api_key,
    base_url="https://jev.bevel.software",  # Service root, without /v1/systemone
    timeout=20,
)
response = client.decide(request, timeout=10)  # Override for just this call
```

The default timeout is 60 seconds. It applies to blocking socket operations,
including connecting and reading; it is not an overall deadline as Go's context
can provide. `None` disables the timeout. This client is synchronous and does not
provide Go-style context cancellation.

Base URLs may include a proxy prefix, such as `https://example.com/proxy`. They must
use HTTP or HTTPS and contain no credentials, query, or fragment. Redirects are
disabled, all non-2xx responses raise `APIError`, and there are no automatic retries.
Each response is closed after reading and limited to 4 MiB. The default transport
respects urllib's proxy environment variables and verifies HTTPS certificates.

A client can be shared across threads. Do not mutate request dictionaries, lists,
or client configuration during a call. The client holds no persistent connections
and needs no `close()` call.

For a custom CA configuration, use
`Client(api_key, transport=HTTPTransport(ssl_context=ssl.create_default_context(cafile=...)))`
with `ssl` and `HTTPTransport` imported. For testing or another HTTP implementation,
pass an object implementing `eujev.Transport.send(request, *, timeout)`.
It receives a `urllib.request.Request` and returns an `eujev.HTTPResponse` with
`status`, `headers` (an `email.message.Message`), `read(size)`, and `close()`.
Custom transports must honor timeouts, return error responses normally, and avoid
redirects and retries. They must support concurrent calls if the client is shared.
The SDK closes responses; transport lifetime remains the caller's responsibility.

## Errors

```python
from eujev import APIError, EujevError, ResponseTooLargeError

try:
    response = client.decide(request)
except APIError as error:
    print(error.status_code, error.code, error.message)
    print(error.request_id, error.retry_after, error.contact_url)
    if isinstance(error.__cause__, ResponseTooLargeError):
        print("Error body exceeded the size limit")
except EujevError as error:
    print(error, error.__cause__)
```

`APIError` preserves case-insensitive `headers`, raw `body` bytes, UTF-8 `body_text`,
and `body_truncated`. HTML and malformed error bodies retain the HTTP status and
raw data, with a standard HTTP message as fallback. `retry_after` retains the
header verbatim for caller-controlled retry scheduling.

| Exception | Meaning |
| --- | --- |
| `RequestError` | The request could not be JSON encoded; nothing was sent |
| `TransportError` | Sending failed, including connection and socket timeout errors |
| `ResponseError` | Reading or decoding a successful response failed |
| `ResponseTooLargeError` | A successful response exceeded 4 MiB |
| `APIError` | A non-2xx response; a read/size failure is retained as `__cause__` |

All of these derive from `EujevError`. Underlying encoding, transport, read, and
decode exceptions remain available through Python exception chaining. Invalid
client configuration or timeout values raise `ValueError` before a network call.

## Development

```sh
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
mypy
python -m build
```

Without installation, run tests with
`PYTHONPATH=src python3 -m unittest discover -s tests -v`.
Tests use local HTTP servers and in-memory transports, with request and response
fixtures from the Go SDK. They need no API key and make no live service requests.
CI runs tests on Python 3.10–3.14 and checks formatting, types, and package builds.

