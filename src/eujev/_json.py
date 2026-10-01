"""JSON decoding without Python's nonstandard NaN and Infinity extensions."""

import json
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def loads(body: bytes) -> Any:
    return json.loads(body, parse_constant=_reject_constant)
