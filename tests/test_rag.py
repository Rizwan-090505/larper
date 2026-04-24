import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.vector_db import VectorDB, search_similar_blocks


def test_vector_db_add_search_and_remove(tmp_path: Path):
    index_path = tmp_path / "test_faiss_index.idx"
    vector_db = VectorDB(index_path=str(index_path), embedding_model="all-MiniLM-L6-v2")

    assert vector_db.index.ntotal == 0

    contents = [
        "The quick brown fox jumps over the lazy dog.",
        "A fast orange fox leaps across the sleepy hound.",
        "Completely unrelated content about space travel.",
    ]
    block_ids = [101, 102, 103]

    embeddings = np.vstack([vector_db.get_embedding(text) for text in contents])
    vector_db.add_embeddings(embeddings, block_ids)

    assert vector_db.index.ntotal == 3
    assert set(vector_db.id_map.values()) == set(block_ids)

    results = vector_db.search(vector_db.get_embedding("fast fox"), k=2)
    assert len(results) >= 1
    assert results[0][0] in {101, 102}
    assert results[0][1] > 0

    vector_db.remove_by_block_ids([101])
    assert vector_db.index.ntotal == 2
    assert 101 not in vector_db.reverse_map
    assert 102 in vector_db.reverse_map
    assert 103 in vector_db.reverse_map


def test_search_similar_blocks_async(tmp_path: Path):
    index_path = tmp_path / "async_index.idx"
    vector_db = VectorDB(index_path=str(index_path), embedding_model="all-MiniLM-L6-v2")

    texts = ["Learn Python programming.", "Study machine learning."]
    vector_db.add_embeddings(np.vstack([vector_db.get_embedding(t) for t in texts]), [201, 202])

    async def run_query():
        return await search_similar_blocks("machine learning", k=1, db=vector_db)

    results = asyncio.run(run_query())
    assert len(results) == 1
    assert results[0][0] == 202
    assert results[0][1] > 0.1
