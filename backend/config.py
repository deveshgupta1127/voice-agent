import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    SARVAM_API_KEY: str = field(default_factory=lambda: os.getenv("SARVAM_API_KEY", ""))
    ANTHROPIC_API_KEY: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    SARVAM_STT_WS_URL: str = "wss://api.sarvam.ai/speech-to-text-translate/ws"
    SARVAM_TTS_WS_URL: str = "wss://api.sarvam.ai/text-to-speech/ws"

    STT_MODEL: str = "saaras:v3"
    STT_LANGUAGE: str = "unknown"
    STT_MODE: str = "transcribe"
    STT_SAMPLE_RATE: int = 16000
    STT_ENCODING: str = "pcm_s16le"
    STT_HIGH_VAD_SENSITIVITY: bool = True
    STT_VAD_SIGNALS: bool = True

    TTS_MODEL: str = "bulbul:v3"
    TTS_TARGET_LANGUAGE: str = "en-IN"
    TTS_SPEAKER: str = "shubh"
    TTS_SAMPLE_RATE: int = 24000
    TTS_ENABLE_COMPLETION: bool = True

    DEFAULT_LLM_PROVIDER: str = "anthropic"
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.3

    DATABASE_PATH: str = "banking.db"

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WS_HEARTBEAT_INTERVAL: int = 30


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
