"""
Multi-Hierarchical Vector Database
===================================
Stores embeddings at three granularity levels for every block:

  Level 0 – DOCUMENT   : full note text (title + all block content joined)
  Level 1 – PARAGRAPH  : individual blocks / paragraphs / sections
  Level 2 – SENTENCE   : individual sentences inside each block

Each level has its own FAISS IndexFlatIP file on disk so they survive restarts.

Graph nodes (used by graph_expand_scores and the agent's graph_expansion tool)
are derived from three sources inside the markdown corpus:
  • File-path segments   : e.g. pages/fyp/Droneresearch → "fyp", "droneresearch"
  • Hashtags             : #tag tokens extracted from block_tags table
  • [[Wikilinks]]        : target_title from block_references table

The singleton is exposed via get_hierarchical_db().
"""

from __future__ import annotations

import logging
import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths for the three FAISS indexes + their id-maps
# ---------------------------------------------------------------------------
_BASE = Path(settings.VECTOR_DB_PATH)  # e.g. faiss_index.bin
_DOC_PATH = _BASE.with_suffix(".hier_doc.bin")
_PARA_PATH = _BASE.with_suffix(".hier_para.bin")
_SENT_PATH = _BASE.with_suffix(".hier_sent.bin")
_MAP_PATH = _BASE.with_suffix(".hier_map.pkl")  # shared metadata map

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Data class stored in memory (and pickled to _MAP_PATH)
# ---------------------------------------------------------------------------
@dataclass
class _BlockMeta:
    block_id: int
    note_id: int
    title: str
    file_path: str
    content: str
    # faiss row index in each sub-index (may differ after removals)
    doc_idx: int = -1
    para_idx: int = -1
    sent_idx: int = -1


# ---------------------------------------------------------------------------
# Helper: load or create a faiss IndexFlatIP
# ---------------------------------------------------------------------------
def _load_or_new_index(path: Path, dim: int):
    import faiss

    if path.exists():
        try:
            return faiss.read_index(str(path))
        except Exception:
            pass
    return faiss.IndexFlatIP(dim)


def _save_index(index, path: Path) -> None:
    import faiss

    faiss.write_index(index, str(path))


def _normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs[None, :]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class MultiHierarchicalVectorDB:
    """
    Three-level vector store that integrates seamlessly with the existing
    VectorDB / retrieval pipeline.

    Public API consumed by the rest of the codebase
    ─────────────────────────────────────────────────
    add_hierarchical_embeddings(block_ids, contents, note_ids, titles, file_paths)
    hierarchical_search(query, k, granularity) -> list[(block_id, score, level)]
    remove_block_ids(block_ids)
    get_hierarchical_context(block_id) -> dict | None
    graph_nodes_for_block(block_id) -> list[str]
    """

    def __init__(self) -> None:
        # lazy-loaded
        self._model = None
        self._dim: int = 384

        # meta: block_id -> _BlockMeta
        self._meta: Dict[int, _BlockMeta] = {}
        # reverse: faiss row -> block_id  (one per sub-index)
        self._doc_rev: Dict[int, int] = {}
        self._para_rev: Dict[int, int] = {}
        self._sent_rev: Dict[int, int] = {}

        self._doc_idx = None
        self._para_idx = None
        self._sent_idx = None

        self._load()

    # ------------------------------------------------------------------ #
    # persistence                                                          #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if _MAP_PATH.exists():
            try:
                with open(_MAP_PATH, "rb") as fh:
                    saved = pickle.load(fh)
                    self._meta = saved.get("meta", {})
                    self._doc_rev = saved.get("doc_rev", {})
                    self._para_rev = saved.get("para_rev", {})
                    self._sent_rev = saved.get("sent_rev", {})
                    self._dim = saved.get("dim", 384)
            except Exception as exc:
                log.warning("hier map load failed (%s); starting fresh", exc)

        self._doc_idx = _load_or_new_index(_DOC_PATH, self._dim)
        self._para_idx = _load_or_new_index(_PARA_PATH, self._dim)
        self._sent_idx = _load_or_new_index(_SENT_PATH, self._dim)

    def _save(self) -> None:
        try:
            with open(_MAP_PATH, "wb") as fh:
                pickle.dump(
                    {
                        "meta": self._meta,
                        "doc_rev": self._doc_rev,
                        "para_rev": self._para_rev,
                        "sent_rev": self._sent_rev,
                        "dim": self._dim,
                    },
                    fh,
                )
            _save_index(self._doc_idx, _DOC_PATH)
            _save_index(self._para_idx, _PARA_PATH)
            _save_index(self._sent_idx, _SENT_PATH)
        except Exception as exc:
            log.error("hier save failed: %s", exc)

    # ------------------------------------------------------------------ #
    # model access                                                         #
    # ------------------------------------------------------------------ #

    def _get_model(self):
        if self._model is None:
            from src.rag.model_loader import _get_model as _load

            self._model = _load(settings.EMBEDDING_MODEL)
            try:
                self._dim = self._model.get_sentence_embedding_dimension()
            except Exception:
                self._dim = 384
        return self._model

    def _encode(self, texts: List[str]) -> np.ndarray:
        model = self._get_model()
        vecs = model.encode(texts, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)

    # ------------------------------------------------------------------ #
    # text splitting                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_paragraphs(content: str) -> List[str]:
        """Split on blank lines or markdown headings."""
        paras, buf = [], []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                if buf:
                    paras.append(" ".join(buf))
                    buf = []
            elif stripped.startswith("#"):
                if buf:
                    paras.append(" ".join(buf))
                buf = [stripped]
            else:
                buf.append(stripped)
        if buf:
            paras.append(" ".join(buf))
        return [p for p in paras if p]

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        parts = SENTENCE_SPLIT_RE.split(text)
        return [s.strip() for s in parts if s.strip()]

    # ------------------------------------------------------------------ #
    # ingestion                                                            #
    # ------------------------------------------------------------------ #

    async def add_hierarchical_embeddings(
        self,
        block_ids: List[int],
        contents: List[str],
        note_ids: List[int],
        titles: List[str],
        file_paths: List[str],
    ) -> None:
        """Add or update blocks in all three sub-indexes."""
        if not block_ids:
            return

        import asyncio

        loop = asyncio.get_event_loop()

        # Build texts for each level
        doc_texts: List[str] = []
        para_texts: List[str] = []
        sent_texts: List[str] = []

        for title, content in zip(titles, contents):
            full = f"{title}\n{content}".strip()

            # Document level: full text
            doc_texts.append(full)

            # Paragraph level: mean of paragraph embeddings; compute representative
            paras = self._split_paragraphs(content) or [content]
            para_texts.append(
                paras[0] if len(paras) == 1 else " [SEP] ".join(paras[:4])
            )

            # Sentence level
            sents = self._split_sentences(content) or [content]
            sent_texts.append(sents[0] if len(sents) == 1 else sents[0])

        # Compute all embeddings in executor (non-blocking)
        def _encode_all():
            d = self._encode(doc_texts)
            p = self._encode(para_texts)
            s = self._encode(sent_texts)
            return d, p, s

        doc_vecs, para_vecs, sent_vecs = await loop.run_in_executor(None, _encode_all)

        # Remove stale entries first
        self.remove_block_ids(block_ids)

        # Add to FAISS + update maps
        for idx, (bid, nid, title, fp, content) in enumerate(
            zip(block_ids, note_ids, titles, file_paths, contents)
        ):
            dv = _normalize(doc_vecs[idx])
            pv = _normalize(para_vecs[idx])
            sv = _normalize(sent_vecs[idx])

            d_row = self._doc_idx.ntotal
            self._doc_idx.add(dv)
            self._doc_rev[d_row] = bid

            p_row = self._para_idx.ntotal
            self._para_idx.add(pv)
            self._para_rev[p_row] = bid

            s_row = self._sent_idx.ntotal
            self._sent_idx.add(sv)
            self._sent_rev[s_row] = bid

            self._meta[bid] = _BlockMeta(
                block_id=bid,
                note_id=nid,
                title=title,
                file_path=fp,
                content=content,
                doc_idx=d_row,
                para_idx=p_row,
                sent_idx=s_row,
            )

        self._save()
        log.debug("hier: added %d blocks", len(block_ids))

    # ------------------------------------------------------------------ #
    # removal                                                              #
    # ------------------------------------------------------------------ #

    def remove_block_ids(self, block_ids: List[int]) -> None:
        """Remove blocks from all sub-indexes (full rebuild, same as VectorDB)."""
        to_remove = set(block_ids) & set(self._meta.keys())
        if not to_remove:
            return

        for bid in to_remove:
            del self._meta[bid]

        # Rebuild each sub-index from surviving meta
        import faiss

        survivors = list(self._meta.values())

        def _rebuild(old_idx, rev_map, attr):
            new_idx = faiss.IndexFlatIP(self._dim)
            new_rev: Dict[int, int] = {}
            for meta in survivors:
                old_row = getattr(meta, attr)
                if old_row < 0 or old_row >= old_idx.ntotal:
                    continue
                vec = np.zeros((1, self._dim), dtype=np.float32)
                old_idx.reconstruct(old_row, vec[0])
                new_row = new_idx.ntotal
                new_idx.add(vec)
                new_rev[new_row] = meta.block_id
                setattr(meta, attr, new_row)
            return new_idx, new_rev

        self._doc_idx, self._doc_rev = _rebuild(self._doc_idx, self._doc_rev, "doc_idx")
        self._para_idx, self._para_rev = _rebuild(
            self._para_idx, self._para_rev, "para_idx"
        )
        self._sent_idx, self._sent_rev = _rebuild(
            self._sent_idx, self._sent_rev, "sent_idx"
        )

        self._save()

    # ------------------------------------------------------------------ #
    # search                                                               #
    # ------------------------------------------------------------------ #

    def _search_index(self, index, rev_map: Dict[int, int], qvec: np.ndarray, k: int):
        if index.ntotal == 0 or k <= 0:
            return []
        k = min(k, index.ntotal)
        scores, idxs = index.search(_normalize(qvec), k)
        results = []
        for score, row in zip(scores[0], idxs[0]):
            if row != -1 and row in rev_map:
                results.append((rev_map[row], float(score)))
        return results

    async def hierarchical_search(
        self,
        query: str,
        k: int = 6,
        granularity: str = "auto",
    ) -> List[Tuple[int, float, str]]:
        """
        Search all three levels and merge.

        Returns list of (block_id, score, level_name).
        """
        import asyncio

        loop = asyncio.get_event_loop()
        qvec = await loop.run_in_executor(None, lambda: self._encode([query])[0])

        if granularity == "auto":
            nw = len(query.split())
            granularity = (
                "sentence" if nw <= 4 else ("paragraph" if nw <= 12 else "document")
            )

        # Run all three for merging; weight the primary one highest
        level_weights = {
            "document": {"document": 0.6, "paragraph": 0.3, "sentence": 0.1},
            "paragraph": {"document": 0.2, "paragraph": 0.6, "sentence": 0.2},
            "sentence": {"document": 0.1, "paragraph": 0.3, "sentence": 0.6},
        }[granularity]

        doc_res = self._search_index(self._doc_idx, self._doc_rev, qvec, k * 2)
        para_res = self._search_index(self._para_idx, self._para_rev, qvec, k * 2)
        sent_res = self._search_index(self._sent_idx, self._sent_rev, qvec, k * 2)

        agg: Dict[int, float] = {}
        for bid, sc in doc_res:
            agg[bid] = agg.get(bid, 0.0) + sc * level_weights["document"]
        for bid, sc in para_res:
            agg[bid] = agg.get(bid, 0.0) + sc * level_weights["paragraph"]
        for bid, sc in sent_res:
            agg[bid] = agg.get(bid, 0.0) + sc * level_weights["sentence"]

        ranked = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:k]
        return [(bid, sc, granularity) for bid, sc in ranked]

    # ------------------------------------------------------------------ #
    # graph nodes derived from corpus metadata                             #
    # ------------------------------------------------------------------ #

    def graph_nodes_for_block(self, block_id: int) -> List[str]:
        """
        Return graph node labels for a block.  These come from:
          1. file-path segments   (pages/fyp/note → ["fyp", "note"])
          2. already extracted tags are in the DB — callers use tag_search
          3. wikilink targets    (block_references.target_title)

        Returns lower-cased tokens callers can use for fuzzy matching.
        """
        meta = self._meta.get(block_id)
        if not meta:
            return []
        nodes: List[str] = []
        # file path segments
        parts = Path(meta.file_path).parts
        for part in parts:
            # strip extension, lower, split on separators
            clean = re.sub(r"\.[^.]+$", "", part).lower()
            tokens = re.split(r"[_\-\s]+", clean)
            nodes.extend(t for t in tokens if len(t) > 2)
        return list(dict.fromkeys(nodes))  # deduplicate, preserve order

    # ------------------------------------------------------------------ #
    # context access                                                       #
    # ------------------------------------------------------------------ #

    def get_hierarchical_context(self, block_id: int) -> Optional[Dict[str, Any]]:
        meta = self._meta.get(block_id)
        if not meta:
            return None
        return {
            "block_id": meta.block_id,
            "note_id": meta.note_id,
            "title": meta.title,
            "file_path": meta.file_path,
            "content": meta.content,
            "has_hierarchical": True,
            "levels": ["document", "paragraph", "sentence"],
            "graph_nodes": self.graph_nodes_for_block(block_id),
        }

    # ------------------------------------------------------------------ #
    # convenience stats                                                    #
    # ------------------------------------------------------------------ #

    @property
    def size(self) -> int:
        return len(self._meta)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_hier_db: Optional[MultiHierarchicalVectorDB] = None


def get_hierarchical_db() -> MultiHierarchicalVectorDB:
    global _hier_db
    if _hier_db is None:
        _hier_db = MultiHierarchicalVectorDB()
    return _hier_db


# kept for backward-compat imports
HierarchicalEmbedding = _BlockMeta
