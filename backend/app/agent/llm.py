"""Model factory. One place decides which Claude model runs and with what settings."""
from langchain_anthropic import ChatAnthropic

from app.config import settings


def make_llm(max_tokens: int = 700) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.llm_model,            # claude-haiku-4-5-20251001 (low cost)
        api_key=settings.anthropic_api_key,
        max_tokens=max_tokens,               # hard cap on output size (and cost)
        temperature=0,                       # deterministic: we want consistent, grounded answers
        timeout=60,
        max_retries=2,                       # transient API errors are retried; persistent ones surface
    )
