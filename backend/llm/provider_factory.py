from config import Settings
from .base_provider import BaseLLMProvider
from .anthropic_provider import AnthropicProvider
from .sarvam_provider import SarvamProvider


def get_provider(provider_name: str, settings: Settings) -> BaseLLMProvider:
    if provider_name == "anthropic":
        return AnthropicProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL,
        )
    if provider_name == "sarvam":
        return SarvamProvider(
            api_key=settings.SARVAM_API_KEY,
            model=settings.SARVAM_LLM_MODEL,
        )
    if provider_name == "sarvam-105b":
        return SarvamProvider(
            api_key=settings.SARVAM_API_KEY,
            model=settings.SARVAM_LLM_MODEL_105B,
        )
    raise ValueError(f"Unknown LLM provider: {provider_name}")
