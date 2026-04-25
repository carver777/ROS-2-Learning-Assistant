"""启动脚本：在 uvicorn event loop 之前加载 RAG 模型，然后注入 FastAPI app。

用法：
    python run_backend.py [--host 0.0.0.0] [--port 8000] [--no-rag]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

# ── 必须在所有 C 扩展之前导入 torch（Windows DLL 顺序问题）──────────────────
import os

import torch  # noqa: F401
from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env", override=True)

RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() == "true"
QDRANT_PATH = ROOT / os.getenv("QDRANT_PATH", "database/ros2-kilted-clean/qdrant_store")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "ros2_kilted_chunks")
RAG_DEVICE = os.getenv("RAG_DEVICE", "cpu")


def _resolve_datasets():
    """解析 QDRANT_DATASETS；未配置时退回单数据集。返回 [(label, abs_path, collection)]."""
    raw = os.getenv("QDRANT_DATASETS", "").strip()
    if not raw:
        return [("default", QDRANT_PATH, QDRANT_COLLECTION)]
    items = []
    for i, part in enumerate(raw.split(",")):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"QDRANT_DATASETS 第 {i+1} 项格式错误（应为 path:collection）：{part}")
        path_part, _, coll = part.rpartition(":")
        abs_path = ROOT / path_part.strip()
        label = coll.strip() or f"ds{i}"
        items.append((label, abs_path, coll.strip()))
    return items


def load_rag():
    import rag_common

    use_fp16 = RAG_DEVICE.startswith("cuda")
    print(f"[RAG] 加载 BGE-M3（device={RAG_DEVICE}）...", flush=True)
    bge = rag_common.load_bge_m3(use_fp16=use_fp16, device=RAG_DEVICE)
    print("[RAG] 加载 reranker...", flush=True)
    rank = rag_common.load_reranker(use_fp16=use_fp16, device=RAG_DEVICE)

    clients: list[tuple[str, object, str]] = []
    for label, path, coll in _resolve_datasets():
        print(f"[RAG] 打开 Qdrant：{label} | {coll} | {path}", flush=True)
        clients.append((label, rag_common.open_qdrant(path), coll))
    return bge, rank, clients


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-rag", action="store_true", help="禁用 RAG，仅使用纯 LLM")
    p.add_argument("--reload", action="store_true", help="开发热重载（会禁用 RAG 注入）")
    args = p.parse_args()

    use_rag = RAG_ENABLED and not args.no_rag and not args.reload

    if use_rag:
        bge, rank, clients = load_rag()
        labels = ", ".join(f"{lab}({coll})" for lab, _c, coll in clients)
        print(f"[RAG] 加载完成 | 数据集={labels}", flush=True)

        # GPU 预热：首次 forward 会触发 CUDA kernel JIT 编译（约 5-6s）。
        # 启动期跑一次假查询，把这部分开销前置，避免拖累首个真实请求。
        if RAG_DEVICE.startswith("cuda"):
            print("[RAG] GPU 预热中...", flush=True)
            import time

            t0 = time.perf_counter()
            _ = bge.encode(
                ["warmup query"],
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            _ = rank.compute_score([["warmup", "warmup passage"]], normalize=True)
            print(f"[RAG] 预热完成（{(time.perf_counter()-t0)*1000:.0f}ms）", flush=True)
    else:
        bge = rank = None
        clients = []
        print("[RAG] 已跳过", flush=True)

    # 导入 app 并注入模型（必须在模型加载之后才 import backend.main）
    import backend.main as app_module

    app_module._bge_model = bge
    app_module._reranker = rank
    app_module._qdrant_clients = clients

    import uvicorn

    print(f"[server] 启动 http://{args.host}:{args.port}", flush=True)
    uvicorn.run(
        app_module.app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
