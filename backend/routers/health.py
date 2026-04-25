"""健康检查接口。"""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.config import DEEPSEEK_API_KEY, LLM_PROVIDER, RAG_ENABLED

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": LLM_PROVIDER,
        "rag_enabled": RAG_ENABLED,
        "rag_loaded": state.bge_model is not None,
        "datasets": [
            {"label": label, "collection": coll} for label, _client, coll in state.qdrant_clients
        ],
        "key_configured": bool(DEEPSEEK_API_KEY),
    }
