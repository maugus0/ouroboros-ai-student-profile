"""Anthropic API client with retry logic (fallback provider)."""

import json
import re

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncAnthropic | None = None


def _build_response_preview(raw: str, *, limit: int = 800) -> str:
    """Build a bounded preview of raw model output for debugging."""
    text = raw.strip()
    if len(text) <= limit:
        return text

    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n... [TRUNCATED RAW RESPONSE] ...\n{text[-tail:]}"


def _parse_anthropic_json(raw: str) -> dict:
    """Parse JSON from Anthropic text responses.

    Claude may return valid JSON wrapped in markdown fences or with a short
    lead-in sentence. Extract the JSON payload before decoding.
    """
    text = raw.strip()
    if not text:
        raise ValueError("Anthropic returned empty text content")

    candidates = [text]

    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        candidates.insert(0, fenced_match.group(1).strip())

    object_start = text.find("{")
    if object_start != -1:
        candidates.append(text[object_start:])

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed, _end_index = decoder.raw_decode(candidate)
            if not isinstance(parsed, dict):
                continue
            return parsed
        except json.JSONDecodeError as exc:
            last_error = exc

    preview = _build_response_preview(text)
    logger.warning(
        "anthropic_non_json_response",
        content_length=len(text),
        response_preview=preview,
        parse_error=str(last_error) if last_error is not None else None,
    )
    if last_error is not None:
        raise ValueError(
            f"Anthropic returned non-JSON content: {last_error}. Response preview: {preview}"
        ) from last_error
    raise ValueError("Anthropic returned non-JSON content")


def get_anthropic_client() -> AsyncAnthropic:
    """Return a lazily-initialised AsyncAnthropic client."""
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def call_anthropic(
    system_prompt: str,
    user_content: str,
    model: str | None = None,
    max_tokens: int | None = None,
) -> dict:
    """Send a message to Anthropic and return the parsed JSON response."""
    client = get_anthropic_client()
    model = model or settings.ANTHROPIC_MODEL
    max_tokens = max_tokens or settings.ANTHROPIC_MAX_TOKENS

    logger.info("anthropic_call_started", model=model)

    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    first_block = response.content[0]
    raw = getattr(first_block, "text", None)
    if raw is None:
        raise ValueError(f"Expected text block from Anthropic, got {type(first_block).__name__}")
    usage = response.usage

    logger.info(
        "anthropic_call_completed",
        model=model,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
    )

    return {
        "content": _parse_anthropic_json(raw),
        "model": model,
        "provider": "anthropic",
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
    }
