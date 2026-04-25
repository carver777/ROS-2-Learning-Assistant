"""Shared helpers for the ROS2 RAG pipeline: model loading, Qdrant adapters,
query encoding, RRF fusion, and LLM backends (DeepSeek / Ollama)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# IMPORTANT: import torch BEFORE qdrant_client on Windows.
# qdrant-client drags in grpcio/protobuf C-extensions whose DLL load order
# conflicts with torch's CUDA DLLs, causing a silent access violation
# (exit code -1073741819) when the model is later loaded on CUDA.
import torch  # noqa: F401  (side-effect: initialize DLL search path first)


# --- 兼容层：FlagEmbedding 1.4.x 使用 transformers 5.x 的 `dtype=` 参数，
# 而我们锁定在 transformers 4.49（保留 `prepare_for_model` 以支持 reranker）。
# 4.49 使用旧的 `torch_dtype=` 参数名，这里把它映射回去。
def _patch_transformers_dtype_compat() -> None:
    try:
        from transformers import modeling_utils
    except Exception:
        return
    base = modeling_utils.PreTrainedModel
    orig = base.from_pretrained
    if getattr(orig, "_dtype_compat_patched", False):
        return

    @classmethod
    def _patched(cls, *args, **kwargs):
        if "dtype" in kwargs and "torch_dtype" not in kwargs:
            kwargs["torch_dtype"] = kwargs.pop("dtype")
        elif "dtype" in kwargs:
            kwargs.pop("dtype", None)
        return orig.__func__(cls, *args, **kwargs)

    _patched._dtype_compat_patched = True  # type: ignore[attr-defined]
    base.from_pretrained = _patched


_patch_transformers_dtype_compat()

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    FusionQuery,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

COLLECTION = "ros2_kilted_chunks"
DENSE_NAME = "dense"
SPARSE_NAME = "sparse"
DENSE_DIM = 1024  # BGE-M3
BGE_M3_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


# ---------- models ----------


def _auto_device(device: str | None) -> str:
    if device:
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:0"
    except ImportError:
        pass
    return "cpu"


def load_bge_m3(use_fp16: bool = True, device: str | None = None):
    from FlagEmbedding import BGEM3FlagModel

    dev = _auto_device(device)
    return BGEM3FlagModel(
        BGE_M3_MODEL,
        use_fp16=use_fp16 and dev.startswith("cuda"),
        devices=[dev],
    )


def load_reranker(use_fp16: bool = True, device: str | None = None):
    from FlagEmbedding import FlagReranker

    dev = _auto_device(device)
    return FlagReranker(
        RERANKER_MODEL,
        use_fp16=use_fp16 and dev.startswith("cuda"),
        devices=[dev],
    )


# ---------- qdrant ----------


def open_qdrant(path: Path) -> QdrantClient:
    path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path))


def ensure_collection(client: QdrantClient, recreate: bool = False) -> None:
    exists = client.collection_exists(COLLECTION)
    if exists and recreate:
        client.delete_collection(COLLECTION)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config={
                DENSE_NAME: VectorParams(size=DENSE_DIM, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE_NAME: SparseVectorParams(),
            },
        )


def to_sparse(lexical_weights: dict) -> SparseVector:
    if not lexical_weights:
        return SparseVector(indices=[0], values=[0.0])
    indices = [int(k) for k in lexical_weights]
    values = [float(v) for v in lexical_weights.values()]
    return SparseVector(indices=indices, values=values)


# ---------- hybrid query ----------


def hybrid_search(
    client: QdrantClient,
    dense_vec,
    sparse_vec: SparseVector,
    limit: int = 20,
    prefetch_limit: int = 50,
    collection_name: str | None = None,
):
    """Run dense + sparse prefetch and RRF-fuse at the Qdrant side.

    `collection_name` 可显式指定；不传则使用模块级 `COLLECTION`（向后兼容）。
    """
    return client.query_points(
        collection_name=collection_name or COLLECTION,
        prefetch=[
            Prefetch(query=list(map(float, dense_vec)), using=DENSE_NAME, limit=prefetch_limit),
            Prefetch(query=sparse_vec, using=SPARSE_NAME, limit=prefetch_limit),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    ).points


# ---------- chunk IO ----------


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    url: str
    title: str
    breadcrumb: str
    chunk_index: int
    text: str
    embed_text: str

    @classmethod
    def from_dict(cls, d: dict) -> Chunk:
        return cls(
            chunk_id=d["chunk_id"],
            doc_id=d["doc_id"],
            url=d["url"],
            title=d.get("title", ""),
            breadcrumb=d.get("breadcrumb", ""),
            chunk_index=int(d.get("chunk_index", 0)),
            text=d["text"],
            embed_text=d.get("embed_text", d["text"]),
        )


def iter_chunks(path: Path) -> Iterable[Chunk]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield Chunk.from_dict(json.loads(line))


# ---------- LLM backends ----------


def load_env_if_any() -> None:
    """Load backend/.env (reused so DEEPSEEK_API_KEY is picked up)."""
    try:
        from dotenv import load_dotenv

        for candidate in (
            Path("backend/.env"),
            Path(".env"),
            Path(__file__).resolve().parent.parent / "backend" / ".env",
        ):
            if candidate.exists():
                load_dotenv(candidate, override=False)
    except ImportError:
        pass


def stream_deepseek(
    system: str,
    user: str,
    *,
    model: str = "deepseek-chat",
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> Iterable[str]:
    import httpx

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set (see backend/.env).")
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    with httpx.Client(timeout=60) as client:
        with client.stream(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"DeepSeek error {resp.status_code}: {resp.read().decode()}")
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk == "[DONE]":
                    return
                try:
                    data = json.loads(chunk)
                    content = data["choices"][0]["delta"].get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue


def stream_ollama(
    system: str,
    user: str,
    *,
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    temperature: float = 0.3,
) -> Iterable[str]:
    import httpx

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "options": {"temperature": temperature},
    }
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama error {resp.status_code}: {resp.read().decode()}")
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("done"):
                        return
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                except Exception:
                    continue


def stream_llm(provider: str, system: str, user: str, **kwargs) -> Iterable[str]:
    if provider == "deepseek":
        return stream_deepseek(system, user, **kwargs)
    if provider == "ollama":
        return stream_ollama(system, user, **kwargs)
    raise ValueError(f"Unknown LLM provider: {provider}")
