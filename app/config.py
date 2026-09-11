import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Legal Voice Review (iPhone PWA)"
    APP_VERSION: str = "1.0.0"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    
    # Google Workspace credentials / OAuth token
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_OAUTH_TOKEN: str = os.getenv("GOOGLE_OAUTH_TOKEN", "")
    
    # Gemini Multimodal Live API settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_LIVE_MODEL: str = os.getenv("GEMINI_LIVE_MODEL", "models/gemini-2.0-flash-exp")
    GEMINI_VOICE_NAME: str = os.getenv("GEMINI_VOICE_NAME", "Aoede")  # Clear, professional voice
    
    # Audio Settings (16kHz PCM for low-latency voice streaming)
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    
    class Config:
        env_file = ".env"

settings = Settings()
