import json
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_PATH = os.path.join(_DIR, "knowledge_base.txt")
CACHE_DIR = os.path.join(_DIR, "rag", "cache")
INDEX_PATH = os.path.join(CACHE_DIR, "faiss.index")
CHUNKS_PATH = os.path.join(CACHE_DIR, "chunks.json")
MODEL_NAME = "all-MiniLM-L6-v2"


def build():
    print(f"Loading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    with open(KB_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    print(f"Found {len(chunks)} chunks in knowledge_base.txt")

    embeddings = model.encode(chunks, convert_to_numpy=True).astype(np.float32)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    os.makedirs(CACHE_DIR, exist_ok=True)
    faiss.write_index(index, INDEX_PATH)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f)

    print(f"Vector DB saved to {CACHE_DIR}")
    print(f"  - {INDEX_PATH}")
    print(f"  - {CHUNKS_PATH}")


if __name__ == "__main__":
    build()
