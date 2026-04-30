# DEFERRED EXPORTS - Don't import VectorDB class directly to avoid loading faiss
# Only export the lazy-loaded singleton and helper functions

from .vector_db import vector_db, add_blocks_to_vector_db, search_similar_blocks, _preload_vector_db
from .retrieval import search_and_enrich_blocks

__all__ = [
    "vector_db",
    "add_blocks_to_vector_db",
    "search_similar_blocks",
    "search_and_enrich_blocks",
    "_preload_vector_db",
]