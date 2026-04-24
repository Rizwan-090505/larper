from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Optional
import pickle
import numpy as np
import faiss

from config import settings
from src.rag.model_loader import _get_model  # assumes your shared embedding loader


# ---------------------------------------------------------------------------
# Vector DB
# ---------------------------------------------------------------------------

class VectorDB:
    def __init__(
        self,
        index_path: str = settings.VECTOR_DB_PATH,  # <-- Updated here
        embedding_model: str = settings.EMBEDDING_MODEL,
    ):
        self.index_path = Path(index_path)
        self.mapping_path = self.index_path.with_suffix(".mapping")
        self.embeddings_path = self.index_path.with_suffix(".embeddings.npy")

        # Shared / cached embedding model
        self.embedding_model = _get_model(embedding_model)

        # Dimension detection
        if hasattr(self.embedding_model, "get_embedding_dimension"):
            self.dimension = self.embedding_model.get_embedding_dimension()
        else:
            self.dimension = self.embedding_model.get_sentence_embedding_dimension()

        self.index: Optional[faiss.IndexFlatIP] = None
        self.id_map: Dict[int, int] = {}
        self.reverse_map: Dict[int, int] = {}
        self.embeddings = np.zeros((0, self.dimension), dtype=np.float32)

        self._load_or_create_index()

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_index(self):
        if self.index_path.exists():
            try:
                self.index = faiss.read_index(str(self.index_path))
            except Exception:
                self.index = faiss.IndexFlatIP(self.dimension)
        else:
            self.index = faiss.IndexFlatIP(self.dimension)

        self._load_mappings()
        self._load_embeddings()

        if (
            self.embeddings.shape[0] > 0
            and self.index.ntotal != self.embeddings.shape[0]
        ):
            self._rebuild_index()

    def _load_mappings(self):
        if self.mapping_path.exists():
            with open(self.mapping_path, "rb") as f:
                self.id_map, self.reverse_map = pickle.load(f)
        else:
            self.id_map = {}
            self.reverse_map = {}

    def _load_embeddings(self):
        if self.embeddings_path.exists():
            self.embeddings = np.load(self.embeddings_path)
        else:
            self.embeddings = np.zeros((0, self.dimension), dtype=np.float32)

    # ------------------------------------------------------------------
    # Embedding utils
    # ------------------------------------------------------------------

    def _normalize_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings.astype(np.float32) / norms

    # ------------------------------------------------------------------
    # Index rebuild / persistence
    # ------------------------------------------------------------------

    def _rebuild_index(self):
        self.index = faiss.IndexFlatIP(self.dimension)
        if self.embeddings.shape[0] > 0:
            self.index.add(self.embeddings.astype(np.float32))

    def _save_state(self):
        faiss.write_index(self.index, str(self.index_path))
        with open(self.mapping_path, "wb") as f:
            pickle.dump((self.id_map, self.reverse_map), f)
        np.save(self.embeddings_path, self.embeddings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_embeddings(self, embeddings: np.ndarray, block_ids: List[int]):
        embeddings = np.asarray(embeddings, dtype=np.float32)

        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        if embeddings.shape[0] != len(block_ids):
            raise ValueError("Embeddings and block_ids must match length")

        if embeddings.shape[1] != self.dimension:
            raise ValueError("Embedding dimension mismatch")

        normalized = self._normalize_embeddings(embeddings)

        start_id = self.index.ntotal
        self.index.add(normalized)

        if self.embeddings.size == 0:
            self.embeddings = normalized.copy()
        else:
            self.embeddings = np.vstack([self.embeddings, normalized])

        for i, block_id in enumerate(block_ids):
            faiss_id = start_id + i
            self.id_map[faiss_id] = block_id
            self.reverse_map[block_id] = faiss_id

        self._save_state()

    def search(self, query_embedding: np.ndarray, k: int = 5) -> List[Tuple[int, float]]:
        if self.index.ntotal == 0 or k <= 0:
            return []

        query_embedding = np.asarray(query_embedding, dtype=np.float32)

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        if query_embedding.shape[1] != self.dimension:
            raise ValueError("Query embedding dimension mismatch")

        query_embedding = self._normalize_embeddings(query_embedding)

        k = min(k, self.index.ntotal)
        scores, indices = self.index.search(query_embedding, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and idx in self.id_map:
                results.append((self.id_map[idx], float(score)))

        return results

    def get_embedding(self, text: str) -> np.ndarray:
        if not isinstance(text, str):
            raise TypeError("Text must be string")
        return self.embedding_model.encode(text, convert_to_numpy=True)

    def remove_by_block_ids(self, block_ids: List[int]):
        block_ids_set = set(block_ids)
        if not block_ids_set:
            return

        valid_faiss_ids = [
            fid for fid, bid in self.id_map.items()
            if bid not in block_ids_set
        ]

        if len(valid_faiss_ids) == len(self.id_map):
            return

        new_embeddings = []
        new_id_map = {}
        new_reverse_map = {}

        for new_idx, fid in enumerate(valid_faiss_ids):
            new_embeddings.append(self.embeddings[fid])
            block_id = self.id_map[fid]
            new_id_map[new_idx] = block_id
            new_reverse_map[block_id] = new_idx

        self.embeddings = (
            np.vstack(new_embeddings).astype(np.float32)
            if new_embeddings
            else np.zeros((0, self.dimension), dtype=np.float32)
        )

        self.id_map = new_id_map
        self.reverse_map = new_reverse_map

        self._rebuild_index()
        self._save_state()


# ---------------------------------------------------------------------------
# Singleton (lazy-loaded)
# ---------------------------------------------------------------------------

_vector_db: Optional[VectorDB] = None

def _get_vector_db() -> VectorDB:
    global _vector_db
    if _vector_db is None:
        _vector_db = VectorDB()
    return _vector_db

class _LazyVectorDB:
    def __getattr__(self, name):
        return getattr(_get_vector_db(), name)

vector_db = _LazyVectorDB()

# ---------------------------------------------------------------------------
# Async preload
# ---------------------------------------------------------------------------

async def _preload_vector_db():
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _get_vector_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    return text.strip()


async def add_blocks_to_vector_db(
    block_ids: List[int],
    contents: List[str],
    db: VectorDB | None = None,
):
    if not block_ids or not contents:
        return

    target_db = db or _get_vector_db()

    embeddings = [
        target_db.get_embedding(_normalize_text(c))
        for c in contents
    ]

    target_db.add_embeddings(np.vstack(embeddings), block_ids)


async def search_similar_blocks(
    query: str,
    k: int = 5,
    db: VectorDB | None = None,
) -> List[Tuple[int, float]]:
    if not isinstance(query, str) or not query.strip():
        return []

    target_db = db or _get_vector_db()
    query_emb = target_db.get_embedding(_normalize_text(query))
    return target_db.search(query_emb, k)
