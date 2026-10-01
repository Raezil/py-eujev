"""Run with EU_JEV_API_KEY set; this makes one live, billable API request."""

import json
import os

from eujev import ChoiceQuestion, Client, DecisionRequest


def main() -> None:
    client = Client(os.environ["EU_JEV_API_KEY"], timeout=30)
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
    print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
