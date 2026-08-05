import os
from typing import Optional
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Settings:
    # ── Anthropic (primary LLM — claude-sonnet-4-6) ───────────────────────────
    ANTHROPIC_API_KEY: str = ""

    # ── Paths ─────────────────────────────────────────────────────────────────
    ACTIVE_FOLDER: str = "."
    DB_PATH: str = "notes.db"
    VECTOR_DB_PATH: str = "faiss_index.bin"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    HF_DIR: str = ".cache/huggingface"

    # ── Legacy / fallback (kept so existing .env files don't break) ──────────
    API_KEY: str = ""
    MODEL: str = "openai/gpt-4.1-mini"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = ""
    OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_API_BASE: str = ""

    # ── RAG toggles ───────────────────────────────────────────────────────────
    ENABLE_BM25: bool = True
    ENABLE_FZF: bool = True
    ENABLE_GRAPH_EXPANSION: bool = True
    RAG_DEFAULT_K: int = 6

    def __init__(self):
        # Load from .env file if it exists
        self._load_env()

    def _load_env(self):
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            with env_file.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip("\"'")
                        if hasattr(self, key):
                            # Convert boolean values
                            if value.lower() == 'true':
                                value = True
                            elif value.lower() == 'false':
                                value = False
                            # Convert integer values
                            elif value.isdigit():
                                value = int(value)
                            setattr(self, key, value)

settings = Settings()
