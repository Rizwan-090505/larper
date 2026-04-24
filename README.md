# Embeddings & Vector DB Setup

To ensure embeddings and the vector database work correctly, make sure the following are set:

## .env

```
ACTIVE_FOLDER=/absolute/path/to/your/project
DB_PATH=notes.db
VECTOR_DB_PATH=faiss_index.bin
API_KEY=your_api_key
MODEL=your_model_name
EMBEDDING_MODEL=all-MiniLM-L6-v2
HF_DIR=/absolute/path/to/model/cache/
```

## config.py

The config.py should load these variables using Pydantic's `BaseSettings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
  API_KEY: str
  ACTIVE_FOLDER: str
  MODEL: str
  DB_PATH: str
  VECTOR_DB_PATH: str
  EMBEDDING_MODEL: str
  HF_DIR: str

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
```

## Python Requirements

- sentence-transformers
- faiss
- numpy
- pydantic-settings

## Usage

The parser worker will automatically generate embeddings for each block and store them in the vector DB. Logs will indicate successful embedding generation and storage.
# LARPER

# LARPer

LARPer is a modular system designed for automated ingestion, processing, and management of structured and unstructured data sources. It provides a pipeline-based architecture for watching directories, detecting changes, ingesting content, and exposing it through APIs and tooling interfaces.

---

## 🚀 Features

- 📁 **File Watcher System**
  - Monitors directories for file creation, updates, and deletions
  - Event-driven ingestion triggers

- ⚙️ **Ingestion Pipeline**
  - Processes markdown, text, and structured files
  - Extensible processing hooks for custom parsers

- 🗄️ **Database Layer**
  - Stores processed documents and metadata
  - Supports efficient querying and filtering
