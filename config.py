from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    API_KEY: str = ""
    ACTIVE_FOLDER: str = "."
    MODEL: str = "openai/gpt-4.1-mini"
    DB_PATH: str = "notes.db"
    VECTOR_DB_PATH: str = "faiss_index.bin"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    HF_DIR: str = ".cache/huggingface"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = ""
    OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
