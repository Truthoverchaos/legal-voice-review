import os

class Settings:
    APP_NAME: str = "Legal Voice Review (iPhone PWA)"
    APP_VERSION: str = "1.0.0"
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_OAUTH_TOKEN: str = os.getenv("GOOGLE_OAUTH_TOKEN", "")
    
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_LIVE_MODEL: str = os.getenv("GEMINI_LIVE_MODEL", "models/gemini-2.0-flash-exp")
    GEMINI_VOICE_NAME: str = os.getenv("GEMINI_VOICE_NAME", "Aoede")
    
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1

settings = Settings()
