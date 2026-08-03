# Embeddings & Vector DB Setup

To ensure embeddings and the vector database work correctly, make sure the following are set:

## .env

```
ACTIVE_FOLDER=/absolute/path/to/your/project
DB_PATH=notes.db
VECTOR_DB_PATH=faiss_index.bin
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
EMBEDDING_MODEL=all-MiniLM-L6-v2
HF_DIR=/absolute/path/to/model/cache/
```

## config.py

The config.py should load these variables using Pydantic's `BaseSettings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
  ACTIVE_FOLDER: str = "."
  DB_PATH: str = "notes.db"
  VECTOR_DB_PATH: str = "faiss_index.bin"
  EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
  HF_DIR: str = ".cache/huggingface"
  OPENROUTER_API_KEY: str = ""
  OPENROUTER_MODEL: str = "openai/gpt-4.1-mini"

  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
```

## Python Requirements

- sentence-transformers
- faiss
- numpy
- pydantic-settings
- langchain-openrouter
- dateparser

## Usage

The parser worker will automatically generate embeddings for each block and store them in the vector DB. Logs will indicate successful embedding generation and storage.

## Personal Manager

The TUI is local-first. Notes, tasks, events, tags, references, and embeddings stay in the local workspace; Todoist/Google Calendar sync is not started.

Type naturally in the agent input:

- `remind me to renew passport tomorrow #admin`
- `meeting with Sam Friday at 14:30 #work`
- `what do I know about the migration plan?`

Retrieval is hybrid: embedding similarity, keyword overlap, tag graph matches, temporal matches, and linked/parent/child block graph expansion are combined before the agent answers.
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
