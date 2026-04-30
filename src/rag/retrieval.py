import asyncio
from typing import List, Dict, Any

from src.ingestion.db.blocks import get_enriched_blocks_data
from src.rag.vector_db import search_similar_blocks, VectorDB

async def search_and_enrich_blocks(
    query: str, k: int = 5, db: VectorDB | None = None
) -> List[Dict[str, Any]]:
    """
    Search for similar blocks and enrich them with file names, actual text content,
    and related block context (parent block, associated tags, block references).
    """
    # 1. Fetch raw vector matches -> List[Tuple[int, float]] (block_id, score)
    basic_results = await search_similar_blocks(query, k=k, db=db)
    if not basic_results:
        return []

    # Extract IDs to fetch from DB
    block_ids = [result[0] for result in basic_results]
    score_map = {result[0]: result[1] for result in basic_results}
    
    enriched_data = await get_enriched_blocks_data(block_ids)
    
    enriched_results = []
    # Keep them in the order of original vector db similarity scores
    for block_id in block_ids:
        if block_id in enriched_data:
            data = enriched_data[block_id]
            data['similarity_score'] = score_map[block_id]
            enriched_results.append(data)
            
    return enriched_results
