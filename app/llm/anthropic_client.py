"""Anthropic API client with retry logic (fallback provider)."""

import json

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: AsyncAnthropic | None = None


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
        "content": json.loads(raw),
        "model": model,
        "provider": "anthropic",
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
    }
