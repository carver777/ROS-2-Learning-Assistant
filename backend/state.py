"""RAG 全局状态：由 ``run_backend.py`` 在 uvicorn 启动前注入。

直接 ``import backend.state as state`` 然后赋值/读取模块级变量即可。
单独成模块的目的是给前置脚本一个明确的注入点，避免散落在 ``main.py``。
"""

from __future__ import annotations

bge_model: object | None = None
reranker: object | None = None
# [(label, QdrantClient, collection_name), ...]
qdrant_clients: list[tuple[str, object, str]] = []


def is_ready() -> bool:
    """RAG 资源是否已就绪（模型与至少 1 个 Qdrant client）。"""
    return bge_model is not None and bool(qdrant_clients)
