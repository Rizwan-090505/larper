from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    API_KEY: str
    ACTIVE_FOLDER: str
    MODEL: str
    DB_PATH: str
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
