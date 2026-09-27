"""Google Gemini API transport (generativelanguage.googleapis.com) for structured output.

Document text is sent to Google only after the user explicitly selects Gemini.
Errors never echo prompts, document text, provider responses, or the API key.
"""

from __future__ import annotations

import copy
import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Same-provider model chain. Free-tier keys have small per-model daily quotas
# (20 requests/day/model when this was written), so a busy or exhausted model
# hands off to the next one. Override with GEMINI_MODELS="a,b,c".
DEFAULT_MODELS = (
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
)
BUSY = {500, 502, 503, 504}


class GeminiError(RuntimeError):
    """Sanitized provider failure."""


def gemini_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def models() -> list[str]:
    configured = [m.strip() for m in os.environ.get("GEMINI_MODELS", "").split(",") if m.strip()]
    return configured or list(DEFAULT_MODELS)


def inline_schema(schema: dict) -> dict:
    """Resolve local ``$ref``s and drop keywords Gemini's schema subset rejects."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {
                key: walk(value)
                for key, value in node.items()
                if key not in {"title", "additionalProperties", "default"}
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def _post(model: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        API_URL.format(model=model),
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def generate(body: dict, *, timeout: int = 90, attempts: int = 2) -> tuple[dict, str]:
    """POST ``body`` across the model chain; returns (response, model used).

    429 (quota) moves to the next model at once; 5xx/network errors retry once.
    """
    if not gemini_available():
        raise GeminiError("Gemini needs GEMINI_API_KEY in the server environment.")
    quota_hit = False
    for model in models():
        for attempt in range(attempts):
            try:
                return _post(model, body, timeout), model
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    quota_hit = True
                    break
                if error.code == 404:
                    break  # model not offered to this key
                if error.code not in BUSY:
                    raise GeminiError(f"Gemini request was rejected ({error.code}).") from None
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(1.0 * (attempt + 1))
    if quota_hit:
        raise GeminiError(
            "Gemini usage limit reached for this API key. Try again later or enable billing."
        )
    raise GeminiError("Gemini is busy or unreachable. Retry in a moment.")


def response_text(response: dict) -> str:
    try:
        parts = response["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        raise GeminiError("Gemini returned no content.") from None
    return "".join(part.get("text", "") for part in parts if not part.get("thought"))


def generate_json(instructions: str, user_text: str, schema: dict, *, max_tokens: int = 8192) -> tuple[str, str]:
    """Structured JSON output constrained by ``schema``; returns (json_text, model)."""
    body = {
        "systemInstruction": {"parts": [{"text": instructions}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": inline_schema(schema),
            "maxOutputTokens": max_tokens,
            "temperature": 0,
        },
    }
    response, model = generate(body)
    return response_text(response), model
