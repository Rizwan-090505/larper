from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

from src.ingestion.db.blocks import get_enriched_blocks_data
from src.ingestion.db.connection import get_connection
from src.rag.vector_db import search_similar_blocks, VectorDB
from src.rag.multi_hierarchical import get_hierarchical_db

from .retrieval import (
    TOKEN_RE, TAG_RE, ISO_DATE_RE,
    _keyword_and_tag_scores, _temporal_scores, _graph_expand_scores,
    _weighted_score
)


async def enhanced_search_and_enrich_blocks(
    query: str, 
    k: int = 6, 
    use_hierarchical: bool = True,
    db: VectorDB | None = None
) -> List[Dict[str, Any]]:
    """
    Enhanced hybrid RAG search with optional hierarchical embeddings.
    
    New features:
    1. Hierarchical embedding matching (document/paragraph/sentence levels)
    2. Query type detection for better granularity matching
    3. Enhanced scoring with hierarchical signals
    
    Parameters:
    - query: Search query
    - k: Number of results
    - use_hierarchical: Whether to use hierarchical embeddings
    - db: Optional vector database instance
    """
    if not query.strip() or k <= 0:
        return []

    scores: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    
    # Determine query type for hierarchical matching
    query_type = _detect_query_type(query)
    
    # Get base vector results
    vector_results = await search_similar_blocks(query, k=max(k * 3, 15), db=db)
    for block_id, score in vector_results:
        scores[block_id]["embedding"] = max(scores[block_id]["embedding"], float(score))
    
    # Add hierarchical embeddings if enabled
    if use_hierarchical:
        hierarchical_scores = await _hierarchical_scores(query, query_type, k=max(k * 3, 15))
        for block_id, score in hierarchical_scores.items():
            scores[block_id]["hierarchical"] = max(scores[block_id].get("hierarchical", 0), float(score))
    
    # Traditional signals
    lexical = await _keyword_and_tag_scores(query, limit=max(k * 5, 30))
    for block_id, signal_scores in lexical.items():
        for signal, score in signal_scores.items():
            scores[block_id][signal] += score
    
    temporal = await _temporal_scores(query)
    for block_id, score in temporal.items():
        scores[block_id]["temporal"] += score
    
    graph_scores = await _graph_expand_scores(set(scores.keys()))
    for block_id, score in graph_scores.items():
        scores[block_id]["graph"] += score
    
    if not scores:
        return []
    
    # Enhanced scoring with hierarchical weight
    ranked = sorted(
        scores.items(),
        key=lambda item: _enhanced_weighted_score(item[1], query_type),
        reverse=True,
    )
    
    block_ids = [block_id for block_id, _ in ranked[: max(k * 2, k)]]
    enriched_data = await get_enriched_blocks_data(block_ids)
    
    # Add hierarchical context if available
    if use_hierarchical:
        hierarchical_db = get_hierarchical_db()
        for block_id in enriched_data:
            hier_context = hierarchical_db.get_hierarchical_context(block_id)
            if hier_context:
                enriched_data[block_id]["hierarchical_context"] = hier_context
    
    enriched_results = []
    for block_id, signal_scores in ranked:
        if len(enriched_results) >= k:
            break
        data = enriched_data.get(block_id)
        if not data:
            continue
        
        total = _enhanced_weighted_score(signal_scores, query_type)
        data["similarity_score"] = total
        data["hybrid_score"] = total
        data["score_breakdown"] = dict(signal_scores)
        data["query_type"] = query_type
        
        enriched_results.append(data)
    
    return enriched_results


def _detect_query_type(query: str) -> str:
    """
    Detect the type of query to determine which hierarchical level to prioritize.
    
    Returns:
    - "factual": Short, specific facts (prioritize sentence level)
    - "conceptual": Medium-length conceptual queries (prioritize paragraph level)
    - "exploratory": Long, broad queries (prioritize document level)
    - "relational": Queries about connections (prioritize graph expansion)
    """
    query = query.lower().strip()
    words = len(query.split())
    
    # Check for relational indicators
    relational_indicators = ["related to", "connected to", "linked to", "similar to", 
                            "like", "unlike", "compare", "contrast", "versus", "vs"]
    if any(indicator in query for indicator in relational_indicators):
        return "relational"
    
    # Check for factual indicators
    factual_indicators = ["what is", "who is", "when did", "where is", "how many",
                         "which", "name", "list", "define"]
    if words <= 5 or any(indicator in query for indicator in factual_indicators):
        return "factual"
    
    # Check for conceptual indicators
    conceptual_indicators = ["explain", "describe", "discuss", "analyze", "understand",
                           "meaning", "significance", "implications"]
    if words <= 15 or any(indicator in query for indicator in conceptual_indicators):
        return "conceptual"
    
    # Default to exploratory for long queries
    return "exploratory"


def _enhanced_weighted_score(signal_scores: dict[str, float], query_type: str) -> float:
    """
    Enhanced scoring that adapts weights based on query type.
    """
    base_score = _weighted_score(signal_scores)
    
    # Add hierarchical score if present
    hierarchical_score = signal_scores.get("hierarchical", 0.0)
    
    # Adjust weights based on query type
    if query_type == "factual":
        # Emphasize sentence-level matching and keywords
        weights = {
            "embedding": 0.40,
            "hierarchical": 0.25,  # Emphasize sentence-level
            "keyword": 0.25,
            "tag": 0.10,
            "temporal": 0.10,
            "graph": 0.05,
        }
    elif query_type == "conceptual":
        # Emphasize paragraph-level matching and embedding
        weights = {
            "embedding": 0.45,
            "hierarchical": 0.20,  # Emphasize paragraph-level
            "keyword": 0.15,
            "tag": 0.10,
            "temporal": 0.15,
            "graph": 0.10,
        }
    elif query_type == "relational":
        # Emphasize graph connections and tags
        weights = {
            "embedding": 0.30,
            "hierarchical": 0.15,
            "keyword": 0.10,
            "tag": 0.20,  # Emphasize shared tags
            "temporal": 0.05,
            "graph": 0.30,  # Emphasize graph expansion
        }
    else:  # exploratory
        # Emphasize document-level matching and breadth
        weights = {
            "embedding": 0.50,
            "hierarchical": 0.15,  # Emphasize document-level
            "keyword": 0.15,
            "tag": 0.10,
            "temporal": 0.15,
            "graph": 0.10,
        }
    
    # Calculate weighted score
    weighted = 0.0
    for signal, weight in weights.items():
        score = signal_scores.get(signal, 0.0)
        weighted += score * weight
    
    return weighted


async def _hierarchical_scores(query: str, query_type: str, k: int) -> Dict[int, float]:
    """
    Get scores from hierarchical embeddings.
    
    Returns mapping of block_id -> hierarchical similarity score.
    """
    try:
        hierarchical_db = get_hierarchical_db()
        
        # Determine granularity based on query type
        if query_type == "factual":
            granularity = "sentence"
        elif query_type == "conceptual":
            granularity = "paragraph"
        else:
            granularity = "document"
        
        # Get hierarchical search results
        results = await hierarchical_db.hierarchical_search(query, k=k, granularity=granularity)
        
        # Convert to score mapping
        scores = {}
        for block_id, score, matched_level, title, file_path in results:
            scores[block_id] = float(score)
        
        return scores
    except Exception as e:
        # Fall back to no hierarchical scores if not available
        return {}


async def get_hierarchical_context(block_id: int) -> Optional[Dict[str, Any]]:
    """Get hierarchical context for a specific block."""
    try:
        hierarchical_db = get_hierarchical_db()
        return hierarchical_db.get_hierarchical_context(block_id)
    except:
        return None


# Export the enhanced search as the default
search_and_enrich_blocks = enhanced_search_and_enrich_blocks