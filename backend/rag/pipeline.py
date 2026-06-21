import json
import logging
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("voice_agent.rag")

_DIR = os.path.dirname(os.path.dirname(__file__))
CACHE_DIR = os.path.join(_DIR, "rag", "cache")
INDEX_PATH = os.path.join(CACHE_DIR, "faiss.index")
CHUNKS_PATH = os.path.join(CACHE_DIR, "chunks.json")


class RAGPipeline:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if not os.path.exists(INDEX_PATH) or not os.path.exists(CHUNKS_PATH):
            raise FileNotFoundError(
                "Vector DB not found. Run 'python -m rag.build_vector_db' first."
            )

        logger.info("Loading FAISS index from %s", CACHE_DIR)
        self._index = faiss.read_index(INDEX_PATH)
        with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
            self._chunks: list[str] = json.load(f)

        self._model = SentenceTransformer(model_name)
        logger.info("RAG ready — %d chunks loaded", len(self._chunks))

    def search(self, query: str, top_k: int = 3) -> list[str]:
        query_vec = self._model.encode([query], convert_to_numpy=True).astype(np.float32)
        _, indices = self._index.search(query_vec, top_k)
        return [self._chunks[i] for i in indices[0] if i < len(self._chunks)]
