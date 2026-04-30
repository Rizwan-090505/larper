from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Optional
import pickle
# DEFERRED IMPORTS: numpy and faiss imported inside methods to avoid startup cost

from config import settings
# model_loader stays - it's just a function definition, doesn't load model yet


# ---------------------------------------------------------------------------
# Vector DB
# ---------------------------------------------------------------------------

class VectorDB:
    def __init__(
        self,
        index_path: str = settings.VECTOR_DB_PATH,
        embedding_model: str = settings.EMBEDDING_MODEL,
    ):
        # Lazy imports - only when VectorDB is actually instantiated
        import numpy as np
        
        self.index_path = Path(index_path)
        self.mapping_path = self.index_path.with_suffix(".mapping")
        self.embeddings_path = self.index_path.with_suffix(".embeddings.npy")

        # Store model name but don't load model yet
        self._embedding_model_name = embedding_model
        self._embedding_model = None  # Lazy loaded on first use
        
        # Default dimension for all-MiniLM-L6-v2
        self.dimension = 384

        self.index: Optional[object] = None  # faiss.IndexFlatIP
        self.id_map: Dict[int, int] = {}
        self.reverse_map: Dict[int, int] = {}
        self.embeddings = np.zeros((0, self.dimension), dtype=np.float32)

        self._load_or_create_index()
    
    @property
    def embedding_model(self):
        """Lazy load the embedding model only when first accessed."""
        if self._embedding_model is None:
            from src.rag.model_loader import _get_model
            self._embedding_model = _get_model(self._embedding_model_name)
            # Update dimension after model loads
            if hasattr(self._embedding_model, "get_embedding_dimension"):
                self.dimension = self._embedding_model.get_embedding_dimension()
            else:
                self.dimension = self._embedding_model.get_sentence_embedding_dimension()
        return self._embedding_model

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_index(self):
        import faiss
        import numpy as np
        
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
        import numpy as np
        
        if self.embeddings_path.exists():
            self.embeddings = np.load(self.embeddings_path)
        else:
            self.embeddings = np.zeros((0, self.dimension), dtype=np.float32)

    # ------------------------------------------------------------------
    # Embedding utils
    # ------------------------------------------------------------------

    def _normalize_embeddings(self, embeddings) -> object:
        import numpy as np
        
        embeddings = np.asarray(embeddings, dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    # ------------------------------------------------------------------
    # Index rebuild / persistence
    # ------------------------------------------------------------------

    def _rebuild_index(self):
        import faiss
        
        self.index = faiss.IndexFlatIP(self.dimension)
        if self.embeddings.shape[0] > 0:
            self.index.add(self.embeddings.astype('float32'))

    def _save_state(self):
        import faiss
        import numpy as np
        
        faiss.write_index(self.index, str(self.index_path))
        with open(self.mapping_path, "wb") as f:
            pickle.dump((self.id_map, self.reverse_map), f)
        np.save(self.embeddings_path, self.embeddings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_embeddings(self, embeddings, block_ids: List[int]):
        import numpy as np
        
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

    def search(self, query_embedding, k: int = 5) -> List[Tuple[int, float]]:
        import numpy as np
        
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

    def get_embedding(self, text: str):
        import numpy as np
        
        if not isinstance(text, str):
            raise TypeError("Text must be string")
        return self.embedding_model.encode(text, convert_to_numpy=True)

    def remove_by_block_ids(self, block_ids: List[int]):
        import numpy as np
        
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

    import asyncio
    loop = asyncio.get_event_loop()

    normalized = [_normalize_text(c) for c in contents]
    embeddings = await loop.run_in_executor(
        None, lambda: target_db.embedding_model.encode(normalized, convert_to_numpy=True)
    )
    
    import numpy as np
    target_db.add_embeddings(embeddings.astype(np.float32), block_ids)


async def search_similar_blocks(
    query: str,
    k: int = 5,
    db: VectorDB | None = None,
) -> List[Tuple[int, float]]:
    if not isinstance(query, str) or not query.strip():
        return []

    import asyncio
    loop = asyncio.get_event_loop()
    target_db = db or _get_vector_db()
    query_emb = await loop.run_in_executor(None, target_db.get_embedding, _normalize_text(query))
    return target_db.search(query_emb, k)