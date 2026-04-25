import sys
from pathlib import Path

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.rag.vector_db import (
    add_blocks_to_vector_db,
    search_similar_blocks,
    vector_db
)


@pytest.mark.asyncio
async def test_add_and_search_blocks():
    # 🔹 Reset DB to avoid flaky tests
    if hasattr(vector_db, "clear"):
        await vector_db.clear()

    block_ids = [101, 102, 103]
    contents = [
        "The quick brown fox jumps over the lazy dog.",
        "Artificial intelligence is transforming the world.",
        "Vector databases store embeddings for fast retrieval."
    ]

    # 🔹 Add data
    await add_blocks_to_vector_db(block_ids, contents)

    # 🔹 Query
    query = "What stores embeddings for fast retrieval?"
    results = await search_similar_blocks(query, k=2)

    print("\nResults:")
    id_to_content = dict(zip(block_ids, contents))
    for block_id, score in results:
        text = id_to_content.get(block_id, "<not found>")
        print(f"Block ID: {block_id}, Score: {score}, Text: {text}")

    # 🔹 Assertion
    assert any(block_id == 103 for block_id, _ in results), \
        "Expected block 103 to be among top results"


@pytest.mark.asyncio
async def test_custom_query():
    query = "There should be what"
    results = await search_similar_blocks(query, k=3)

    print("\nCustom Query Results:")
    # If you want to see the text, you need to know the mapping from block_id to content.
    # For this test, you can add your own mapping or print only IDs and scores.
    for block_id, score in results:
        print(f"Block ID: {block_id}, Score: {score}")
