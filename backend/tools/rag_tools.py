from rag.pipeline import RAGPipeline


def make_search_knowledge_base(rag: RAGPipeline):
    async def search_knowledge_base(query: str) -> dict:
        results = rag.search(query, top_k=3)
        return {"results": results}

    return search_knowledge_base
