from config import Settings
from .base_provider import BaseLLMProvider
from .anthropic_provider import AnthropicProvider


def get_provider(provider_name: str, settings: Settings) -> BaseLLMProvider:
    if provider_name == "anthropic":
        return AnthropicProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL,
        )
    raise ValueError(f"Unknown LLM provider: {provider_name}")
