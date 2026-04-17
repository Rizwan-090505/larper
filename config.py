from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_KEY: str
    ACTIVE_FOLDER: str
    MODEL: str
    DB_PATH: str
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
