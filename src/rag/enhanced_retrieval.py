"""
Enhanced Hybrid Retrieval
==========================
Combines:
  • FAISS flat-IP vector search  (baseline embeddings)
  • Multi-hierarchical vector search  (doc / paragraph / sentence sub-indexes)
  • Keyword + tag lexical scoring
  • Temporal scoring (dates in content / task dates)
  • Graph expansion (parent/child blocks, [[wikilinks]], shared #tags,
                     file-path segment proximity)

The public entry point is `search_and_enrich_blocks`, which is re-exported
here so the rest of the codebase has a single stable import.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.ingestion.db.blocks import get_enriched_blocks_data
from src.rag.vector_db import search_similar_blocks, VectorDB
from src.rag.multi_hierarchical import get_hierarchical_db
import re
from .retrieval import (
    TAG_RE,
    TOKEN_RE,
    ISO_DATE_RE,
    _keyword_and_tag_scores,
    _temporal_scores,
    _graph_expand_scores,
    _weighted_score,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query type detection
# ---------------------------------------------------------------------------

_RELATIONAL = re.compile(
    r"\b(related|connected|linked|similar|like|compare|contrast|versus|vs)\b",
    re.I,
)
_FACTUAL = re.compile(
    r"^(what|who|when|where|how many|which|name|list|define)\b|"
    r"\b(is|are|was|were)\s+\w+\?",
    re.I,
)
_CONCEPTUAL = re.compile(
    r"\b(explain|describe|discuss|analyze|understand|meaning|significance|"
    r"implications|overview|summary)\b",
    re.I,
)

import re  # noqa: E402  (needed for _RELATIONAL etc above)


def _detect_query_type(query: str) -> str:
    """Return one of: factual | conceptual | relational | exploratory."""
    q = query.strip()
    if _RELATIONAL.search(q):
        return "relational"
    words = len(q.split())
    if words <= 5 or _FACTUAL.search(q):
        return "factual"
    if _CONCEPTUAL.search(q):
        return "conceptual"
    return "exploratory"


# ---------------------------------------------------------------------------
# Per-query-type score weights
# ---------------------------------------------------------------------------

_WEIGHTS: Dict[str, Dict[str, float]] = {
    "factual": {
        "embedding": 0.35,
        "hierarchical": 0.25,
        "keyword": 0.20,
        "tag": 0.10,
        "temporal": 0.05,
        "graph": 0.05,
    },
    "conceptual": {
        "embedding": 0.40,
        "hierarchical": 0.20,
        "keyword": 0.15,
        "tag": 0.10,
        "temporal": 0.10,
        "graph": 0.05,
    },
    "relational": {
        "embedding": 0.25,
        "hierarchical": 0.10,
        "keyword": 0.10,
        "tag": 0.20,
        "temporal": 0.05,
        "graph": 0.30,
    },
    "exploratory": {
        "embedding": 0.45,
        "hierarchical": 0.15,
        "keyword": 0.15,
        "tag": 0.10,
        "temporal": 0.10,
        "graph": 0.05,
    },
}


def _enhanced_weighted_score(signal_scores: Dict[str, float], query_type: str) -> float:
    weights = _WEIGHTS.get(query_type, _WEIGHTS["exploratory"])
    return sum(signal_scores.get(sig, 0.0) * w for sig, w in weights.items())


# ---------------------------------------------------------------------------
# Hierarchical signal
# ---------------------------------------------------------------------------


async def _hierarchical_scores(query: str, query_type: str, k: int) -> Dict[int, float]:
    """Return block_id → hierarchical similarity score."""
    try:
        hier_db = get_hierarchical_db()
        if hier_db.size == 0:
            return {}

        granularity_map = {
            "factual": "sentence",
            "conceptual": "paragraph",
            "relational": "paragraph",
            "exploratory": "document",
        }
        gran = granularity_map.get(query_type, "auto")

        results = await hier_db.hierarchical_search(query, k=k, granularity=gran)
        return {bid: score for bid, score, _ in results}
    except Exception as exc:
        log.debug("hierarchical_scores failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def search_and_enrich_blocks(
    query: str,
    k: int = 6,
    use_hierarchical: bool = True,
    db: VectorDB | None = None,
) -> List[Dict[str, Any]]:
    """
    Hybrid RAG search combining vector, hierarchical, lexical, temporal, and
    graph signals.  This is the single function the agent and TUI use.
    """
    if not query.strip() or k <= 0:
        return []

    scores: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    query_type = _detect_query_type(query)
    fetch_k = max(k * 3, 15)

    # 1. Baseline vector search
    for bid, sc in await search_similar_blocks(query, k=fetch_k, db=db):
        scores[bid]["embedding"] = max(scores[bid]["embedding"], float(sc))

    # 2. Multi-hierarchical search
    if use_hierarchical:
        for bid, sc in (await _hierarchical_scores(query, query_type, fetch_k)).items():
            scores[bid]["hierarchical"] = max(
                scores[bid].get("hierarchical", 0.0), float(sc)
            )

    # 3. Lexical (keyword + tag)
    for bid, sigs in (
        await _keyword_and_tag_scores(query, limit=max(k * 5, 30))
    ).items():
        for sig, sc in sigs.items():
            scores[bid][sig] += sc

    # 4. Temporal
    for bid, sc in (await _temporal_scores(query)).items():
        scores[bid]["temporal"] += sc

    # 5. Graph expansion (uses DB-level parent/child/ref/tag + path-segment nodes)
    graph_sc = await _graph_expand_scores(set(scores.keys()))
    for bid, sc in graph_sc.items():
        scores[bid]["graph"] += sc

    if not scores:
        return []

    ranked = sorted(
        scores.items(),
        key=lambda item: _enhanced_weighted_score(item[1], query_type),
        reverse=True,
    )

    block_ids = [bid for bid, _ in ranked[: max(k * 2, k)]]
    enriched = await get_enriched_blocks_data(block_ids)

    # Attach hierarchical context where available
    if use_hierarchical:
        hier_db = get_hierarchical_db()
        for bid in list(enriched.keys()):
            ctx = hier_db.get_hierarchical_context(bid)
            if ctx:
                enriched[bid]["hierarchical_context"] = ctx

    results: List[Dict[str, Any]] = []
    for bid, sigs in ranked:
        if len(results) >= k:
            break
        data = enriched.get(bid)
        if not data:
            continue
        total = _enhanced_weighted_score(sigs, query_type)
        data["similarity_score"] = total
        data["hybrid_score"] = total
        data["score_breakdown"] = dict(sigs)
        data["query_type"] = query_type
        results.append(data)

    return results


# ---------------------------------------------------------------------------
# Compat shim (old import name used in a few places)
# ---------------------------------------------------------------------------
enhanced_search_and_enrich_blocks = search_and_enrich_blocks
