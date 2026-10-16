from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/ai_panel_studio.db"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.deepseek.com"
    openai_model: str = "deepseek-chat"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
