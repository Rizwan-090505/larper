from __future__ import annotations

import re
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from dataclasses import dataclass
from pathlib import Path

from .vector_db import VectorDB, _get_vector_db, add_blocks_to_vector_db
from config import settings

@dataclass
class HierarchicalEmbedding:
    """Represents embeddings at different levels of granularity."""
    block_id: int
    note_id: int
    document_embedding: np.ndarray  # Whole document context
    paragraph_embedding: np.ndarray  # Paragraph/section level  
    sentence_embedding: np.ndarray   # Individual sentence level
    content: str
    title: str
    file_path: str


class MultiHierarchicalVectorDB:
    """
    Enhanced vector database that stores embeddings at multiple hierarchical levels:
    1. Document level (entire note context)
    2. Paragraph level (sections/paragraphs) 
    3. Sentence level (individual sentences)
    
    This allows for more nuanced retrieval based on query granularity.
    """
    
    def __init__(self, base_db: Optional[VectorDB] = None):
        self.base_db = base_db or _get_vector_db()
        self._hierarchical_data: Dict[int, HierarchicalEmbedding] = {}
        self._load_hierarchical_data()
    
    def _load_hierarchical_data(self):
        """Load hierarchical embeddings from disk if they exist."""
        # TODO: Implement persistence for hierarchical embeddings
        pass
    
    def _save_hierarchical_data(self):
        """Save hierarchical embeddings to disk."""
        # TODO: Implement persistence for hierarchical embeddings
        pass
    
    def _split_into_hierarchies(self, content: str) -> Tuple[str, List[str], List[str]]:
        """
        Split content into hierarchical levels:
        - Document: Entire content
        - Paragraphs: Split by blank lines or markdown headings
        - Sentences: Split by sentence boundaries
        """
        # Document level - entire content
        document_text = content.strip()
        
        # Paragraph level - split by blank lines or markdown headings
        paragraphs = []
        current_para = []
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
            elif line.startswith('#') or line.startswith('##') or line.startswith('###'):
                # Markdown heading - start new paragraph
                if current_para:
                    paragraphs.append(' '.join(current_para))
                current_para = [line]
            else:
                current_para.append(line)
        
        if current_para:
            paragraphs.append(' '.join(current_para))
        
        # Sentence level - split by sentence boundaries
        sentences = []
        for para in paragraphs:
            # Simple sentence splitting (can be improved with NLP)
            para_sentences = re.split(r'[.!?]+', para)
            sentences.extend([s.strip() for s in para_sentences if s.strip()])
        
        return document_text, paragraphs, sentences
    
    def _create_hierarchical_embeddings(self, content: str, block_id: int, note_id: int, 
                                        title: str, file_path: str) -> HierarchicalEmbedding:
        """Create embeddings for all hierarchical levels."""
        document_text, paragraphs, sentences = self._split_into_hierarchies(content)
        
        # Get embeddings for each level
        model = self.base_db.embedding_model
        
        # Document embedding
        doc_embedding = model.encode(document_text, convert_to_numpy=True)
        
        # Paragraph embedding (average of paragraph embeddings)
        if paragraphs:
            para_embeddings = model.encode(paragraphs, convert_to_numpy=True)
            para_embedding = np.mean(para_embeddings, axis=0)
        else:
            para_embedding = doc_embedding.copy()
        
        # Sentence embedding (average of sentence embeddings)
        if sentences:
            sent_embeddings = model.encode(sentences, convert_to_numpy=True)
            sent_embedding = np.mean(sent_embeddings, axis=0)
        else:
            sent_embedding = doc_embedding.copy()
        
        return HierarchicalEmbedding(
            block_id=block_id,
            note_id=note_id,
            document_embedding=doc_embedding,
            paragraph_embedding=para_embedding,
            sentence_embedding=sent_embedding,
            content=content,
            title=title,
            file_path=file_path
        )
    
    async def add_hierarchical_embeddings(self, block_ids: List[int], contents: List[str],
                                          note_ids: List[int], titles: List[str], 
                                          file_paths: List[str]):
        """Add blocks with hierarchical embeddings."""
        if len(block_ids) != len(contents) != len(note_ids) != len(titles) != len(file_paths):
            raise ValueError("All input lists must have the same length")
        
        import asyncio
        
        # Create hierarchical embeddings
        hierarchical_items = []
        for i in range(len(block_ids)):
            he = self._create_hierarchical_embeddings(
                contents[i], block_ids[i], note_ids[i], titles[i], file_paths[i]
            )
            hierarchical_items.append(he)
            self._hierarchical_data[block_ids[i]] = he
        
        # Still add to base vector DB (using document-level embeddings for backward compatibility)
        doc_embeddings = np.array([he.document_embedding for he in hierarchical_items])
        await add_blocks_to_vector_db(block_ids, contents, self.base_db)
        
        self._save_hierarchical_data()
    
    def _get_best_hierarchical_match(self, query: str, granularity: str = "auto") -> np.ndarray:
        """
        Determine which hierarchical level is best for the query.
        
        granularity options:
        - "document": Use document-level embeddings
        - "paragraph": Use paragraph-level embeddings  
        - "sentence": Use sentence-level embeddings
        - "auto": Automatically determine based on query length/complexity
        """
        model = self.base_db.embedding_model
        query_embedding = model.encode(query, convert_to_numpy=True)
        
        if granularity == "auto":
            # Simple heuristic: short queries -> sentence level, long queries -> document level
            query_words = len(query.split())
            if query_words <= 3:
                return query_embedding, "sentence"
            elif query_words <= 10:
                return query_embedding, "paragraph"
            else:
                return query_embedding, "document"
        else:
            return query_embedding, granularity
    
    async def hierarchical_search(self, query: str, k: int = 5, 
                                 granularity: str = "auto") -> List[Tuple[int, float, str]]:
        """
        Search using hierarchical embeddings.
        
        Returns: List of (block_id, score, matched_level)
        """
        query_embedding, matched_level = self._get_best_hierarchical_match(query, granularity)
        
        # For now, use the base search (document level)
        # TODO: Implement proper hierarchical search
        results = self.base_db.search(query_embedding, k)
        
        # Enhance results with hierarchical information
        enhanced_results = []
        for block_id, score in results:
            if block_id in self._hierarchical_data:
                he = self._hierarchical_data[block_id]
                enhanced_results.append((block_id, score, matched_level, he.title, he.file_path))
            else:
                enhanced_results.append((block_id, score, matched_level, "", ""))
        
        return enhanced_results
    
    def get_hierarchical_context(self, block_id: int) -> Optional[Dict[str, Any]]:
        """Get hierarchical context for a block."""
        if block_id not in self._hierarchical_data:
            return None
        
        he = self._hierarchical_data[block_id]
        return {
            "block_id": he.block_id,
            "note_id": he.note_id,
            "title": he.title,
            "file_path": he.file_path,
            "content": he.content,
            "has_hierarchical": True,
            "levels": ["document", "paragraph", "sentence"]
        }


# Singleton instance
_hierarchical_db: Optional[MultiHierarchicalVectorDB] = None

def get_hierarchical_db() -> MultiHierarchicalVectorDB:
    """Get or create the hierarchical vector database."""
    global _hierarchical_db
    if _hierarchical_db is None:
        _hierarchical_db = MultiHierarchicalVectorDB()
    return _hierarchical_db