"""Bedrock Anthropic wire format — the provider-level half shared by the Units that call it.

Three Units speak the Anthropic Messages protocol over Bedrock (U7 summarization, U11 evidence,
U12 novelty) and had each grown their own copy of the same four pieces: the protocol version
string, the ``invoke_model`` envelope (encode body → the payload may be bytes or a stream → decode),
the tool schema shape, and the content blocks. None of that carries domain meaning — it is the
wire format, and a copy of a wire format is a copy that drifts silently, because a stale one keeps
working until the day the protocol moves.

What deliberately does NOT live here, because these are the parts that SHOULD differ per Unit:

- **The circuit breaker and the retry policy.** Each Unit raises its own unavailable-exception
  and counts failures its own way (U11/U12: one machine retry then hand the error to the agent;
  U7: exponential backoff then abstain). Wrapping the call is the caller's job — these helpers
  are the thing being wrapped.
- **The decision mapping.** ``tool_use`` → a Unit's own decision type is domain vocabulary.
- **Streaming.** U7 streams (``invoke_model_with_response_stream``) to catch a mid-JSON
  truncation at the output cap; the others do not need it. Only the non-streaming envelope is
  shared.

boto3 is never imported here — callers pass an already-built client, so a process that never
touches Bedrock does not load it.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "ANTHROPIC_VERSION",
    "first_tool_call",
    "image_block",
    "invoke_model",
    "text_blocks",
    "tool_schema",
]

ANTHROPIC_VERSION = "bedrock-2023-05-31"


def invoke_model(client: Any, model_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """One non-streaming ``invoke_model`` round trip → the decoded response body.

    No retry, no breaker, no error translation: the caller owns those. ``response["body"]`` is a
    ``StreamingBody`` against the real client but plain bytes against most fakes, so both are
    accepted — a caller that handles only one shape passes its tests and fails in production.
    """
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )
    raw = response["body"]
    payload = raw.read() if hasattr(raw, "read") else raw
    return json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Anthropic tool declaration. Note ``input_schema`` — OpenAI's equivalent key is
    ``parameters`` nested under ``function``, which is why this shape belongs to the provider
    and not to the port."""
    return {"name": name, "description": description, "input_schema": parameters}


def image_block(media_type: str, data_b64: str) -> dict[str, Any]:
    """Base64 image content block. Callers MUST place text before images so a trust-boundary
    declaration precedes the data (BR-EV-17 / BR-RA); ordering stays with the caller because
    only it knows which text is the banner."""
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }


def first_tool_call(response: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """First ``tool_use`` block as ``(name, arguments)``, or None if the model returned prose.

    Arguments that are not an object become ``{}`` rather than propagating a non-dict: callers
    validate arguments against the tool's own schema, and handing them a string to unpack turns
    a bad model response into a TypeError far from here.
    """
    for block in (response or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            args = block.get("input")
            return str(block.get("name") or ""), args if isinstance(args, dict) else {}
    return None


def text_blocks(response: dict[str, Any]) -> list[str]:
    """Every ``text`` block, in order. Callers decide whether they want the first one (an
    extraction payload) or all of them joined (a prose fallback before terminating)."""
    return [
        str(block.get("text") or "")
        for block in (response or {}).get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
