# Usage examples

Run these commands from the repository root after `python -m pip install .`.
For an uninstalled checkout, prefix commands with `PYTHONPATH=src`.

| Script | Demonstrates | API key needed? |
| --- | --- | --- |
| [offline.py](offline.py) | A complete decision using a fake transport; no network or cost | No |
| [refund.py](refund.py) | Route a refund message with a choice question; print the full response | Yes |
| [all_question_types.py](all_question_types.py) | Structured state, choice/noul/score, probabilities, token usage, exact costs | Yes |
| [handle_errors.py](handle_errors.py) | Timeouts, a custom base URL, API diagnostics, connection errors | Yes |

Try the offline example first:

```sh
python examples/offline.py
```

It prints the outgoing JSON, a simulated refund probability of `0.98`, and the
request ID `offline-example`. The transport returns fixed data and never calls
the API.

For live calls, set your API key and choose an example:

```sh
export EU_JEV_API_KEY='your-api-key'
python examples/refund.py
python examples/all_question_types.py
python examples/handle_errors.py
```

Each live script makes one request when run; the service may charge for it.
`handle_errors.py` optionally reads `EU_JEV_BASE_URL` (the service root, without
`/v1/systemone`). Leave it unset to use the normal endpoint.

