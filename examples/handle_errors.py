"""Configure a client and inspect API and transport errors from one live call."""

import os
import sys

from eujev import (
    DEFAULT_BASE_URL,
    APIError,
    Client,
    DecisionRequest,
    EujevError,
    NoulQuestion,
    TransportError,
)


def main() -> None:
    try:
        client = Client(
            os.environ["EU_JEV_API_KEY"],
            base_url=os.environ.get("EU_JEV_BASE_URL", DEFAULT_BASE_URL),
            timeout=20,
        )
        response = client.decide(
            DecisionRequest(
                state="The same payment appears twice on my invoice.",
                questions={"refund": NoulQuestion("Does this require a refund?")},
            ),
            timeout=10,
        )
    except (KeyError, ValueError) as error:
        print(f"Check EU_JEV_API_KEY and client configuration: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except APIError as error:
        print(f"HTTP {error.status_code}: {error.message}", file=sys.stderr)
        print(f"Code: {error.code}; request ID: {error.request_id}", file=sys.stderr)
        if error.retry_after:
            print(
                f"Retry-After: {error.retry_after}; this example does not retry.", file=sys.stderr
            )
        if error.contact_url:
            print(f"Contact: {error.contact_url}", file=sys.stderr)
        raise SystemExit(1) from error
    except TransportError as error:
        print(f"Connection or socket timeout failure: {error.__cause__}", file=sys.stderr)
        raise SystemExit(1) from error
    except EujevError as error:
        print(f"SDK error: {error}; cause: {error.__cause__}", file=sys.stderr)
        raise SystemExit(1) from error

    print("Refund probability:", response.answers["refund"].noul)
    print("Request ID:", response.meta.request_id)


if __name__ == "__main__":
    main()
