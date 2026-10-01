"""Ask choice, noul, and score questions in a single live API request."""

import os
from decimal import Decimal

from eujev import ChoiceQuestion, Client, DecisionRequest, NoulQuestion, ScoreQuestion


def main() -> None:
    client = Client(os.environ["EU_JEV_API_KEY"], timeout=30)
    response = client.decide(
        DecisionRequest(
            state={
                "message": "I was charged twice and need the money back today.",
                "customer_tier": "premium",
                "history": ["Payment completed yesterday"],
            },
            questions={
                "team": ChoiceQuestion(
                    instructions="Which team should handle this?",
                    criteria={
                        "billing": "Payments, invoices, and refunds",
                        "support": "Technical issues and bugs",
                    },
                ),
                "refund": NoulQuestion(
                    instructions="Does this require a refund?",
                    criteria={"true": "A duplicate charge", "false": "A valid charge"},
                ),
                "urgency": ScoreQuestion(
                    instructions="How urgently should the team respond?",
                    criteria=["Routine", "Soon", "Immediately"],
                ),
            },
        )
    )

    print("Assigned team:", response.answers["team"].choice)
    refund_probability = response.answers["refund"].noul
    # Check against None: a probability of zero is a valid answer.
    if refund_probability is not None:
        print(f"Refund probability: {refund_probability:.1%}")
    urgency = response.answers["urgency"]
    if urgency.score is not None:
        print(f"Urgency: {urgency.score:.2f} on the 0–2 scale")
    print("Scale:", urgency.legend)
    print("Tokens:", response.usage.input_tokens, response.usage.output_tokens)
    if response.meta.cost_eur:
        print("Cost (EUR):", Decimal(response.meta.cost_eur))


if __name__ == "__main__":
    main()
