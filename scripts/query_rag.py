"""Query the ROS2 RAG store: hybrid retrieval + reranker + optional LLM.

Pipeline:
  query -> BGE-M3 (dense + sparse) -> Qdrant RRF hybrid search (pool)
        -> bge-reranker-v2-m3 rerank (optional) -> top-k
        -> DeepSeek / Ollama generation (optional)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import rag_common

# Import torch first on Windows; see note in rag_common.py.
import torch  # noqa: F401
from rag_common import (
    hybrid_search,
    load_bge_m3,
    load_env_if_any,
    load_reranker,
    open_qdrant,
    stream_llm,
    to_sparse,
)

SYSTEM_PROMPT_CN = (
    "你是一位 ROS 2 技术专家，回答用户关于 ROS 2 Kilted 的问题。\n"
    "严格遵守：\n"
    "1. 只基于给定的上下文回答，不要编造。\n"
    "2. 若上下文不足，明确说“资料中未覆盖”。\n"
    "3. 答案末尾用 [n] 的形式引用上下文编号。\n"
    "4. 默认中文回答，代码/命令/参数保留原文。\n"
)


def build_prompt(query: str, hits: list[dict]) -> str:
    context_blocks = []
    for i, h in enumerate(hits, 1):
        context_blocks.append(
            f"[{i}] {h['title']} | {h['breadcrumb']}\nURL: {h['url']}\n{h['text']}"
        )
    ctx = "\n\n---\n\n".join(context_blocks)
    return f"# 用户问题\n{query}\n\n" f"# 上下文\n{ctx}\n\n" "请基于上下文回答。"


def main() -> None:
    p = argparse.ArgumentParser(description="Query the ROS2 RAG knowledge base.")
    p.add_argument("query", nargs="?", help="Question text. If omitted, reads stdin.")
    p.add_argument(
        "--qdrant-path", type=Path, default=Path("database/ros2-kilted-clean/qdrant_store")
    )
    p.add_argument("--collection", type=str, default=None, help="Override Qdrant collection name.")
    p.add_argument("--top-k", type=int, default=5, help="Final results returned.")
    p.add_argument(
        "--rerank-pool", type=int, default=20, help="Hybrid candidate pool before rerank."
    )
    p.add_argument(
        "--prefetch",
        type=int,
        default=40,
        help="Per-branch prefetch size inside Qdrant (dense & sparse).",
    )
    p.add_argument("--no-rerank", action="store_true", help="Skip cross-encoder reranking.")
    p.add_argument("--no-fp16", action="store_true")
    p.add_argument("--llm", choices=["none", "deepseek", "ollama"], default="none")
    p.add_argument("--ollama-model", default="qwen2.5:7b")
    p.add_argument("--ollama-base", default="http://localhost:11434")
    p.add_argument("--show-chars", type=int, default=280, help="Text preview length per hit.")
    args = p.parse_args()

    if args.query is None:
        args.query = sys.stdin.read().strip()
    if not args.query:
        print("ERR: empty query.", file=sys.stderr)
        sys.exit(2)

    if args.collection:
        rag_common.COLLECTION = args.collection

    load_env_if_any()
    print(f"[rag] query: {args.query}")

    print("[rag] loading BGE-M3 ...")
    t0 = time.time()
    model = load_bge_m3(use_fp16=not args.no_fp16)
    print(f"      ready in {time.time() - t0:.1f}s")

    print(f"[rag] opening qdrant at {args.qdrant_path} ...")
    client = open_qdrant(args.qdrant_path)

    print("[rag] encoding query ...")
    enc = model.encode(
        [args.query],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vec = enc["dense_vecs"][0]
    sparse_vec = to_sparse(enc["lexical_weights"][0])

    print(f"[rag] hybrid search (prefetch={args.prefetch} pool={args.rerank_pool}) ...")
    hits = hybrid_search(
        client, dense_vec, sparse_vec, limit=args.rerank_pool, prefetch_limit=args.prefetch
    )

    if not hits:
        print("[rag] no results.")
        return

    candidates = []
    for pt in hits:
        p_ = pt.payload or {}
        candidates.append(
            {
                "score": float(pt.score) if pt.score is not None else 0.0,
                "chunk_id": p_.get("chunk_id", ""),
                "doc_id": p_.get("doc_id", ""),
                "url": p_.get("url", ""),
                "title": p_.get("title", ""),
                "breadcrumb": p_.get("breadcrumb", ""),
                "text": p_.get("text", ""),
            }
        )

    if not args.no_rerank and len(candidates) > 1:
        print(f"[rag] reranking {len(candidates)} candidates with bge-reranker-v2-m3 ...")
        reranker = load_reranker(use_fp16=not args.no_fp16)
        pairs = [[args.query, c["text"]] for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [float(scores)]
        for c, s in zip(candidates, scores, strict=False):
            c["rerank"] = float(s)
        candidates.sort(key=lambda x: x.get("rerank", 0.0), reverse=True)
    else:
        candidates.sort(key=lambda x: x["score"], reverse=True)

    top = candidates[: args.top_k]

    print("\n" + "=" * 80)
    print(f"Top-{len(top)} results")
    print("=" * 80)
    for i, c in enumerate(top, 1):
        score_str = (
            f"rerank={c.get('rerank', 0.0):.4f}" if "rerank" in c else f"rrf={c['score']:.4f}"
        )
        preview = c["text"].replace("\n", " ")
        if len(preview) > args.show_chars:
            preview = preview[: args.show_chars] + "..."
        print(f"\n[{i}] {score_str}  {c['title']}")
        print(f"    {c['breadcrumb']}")
        print(f"    {c['url']}")
        print(f"    {preview}")

    if args.llm == "none":
        return

    print("\n" + "=" * 80)
    print(f"Generating answer via {args.llm} ...")
    print("=" * 80)
    prompt = build_prompt(args.query, top)

    llm_kwargs = {}
    if args.llm == "ollama":
        llm_kwargs = {"model": args.ollama_model, "base_url": args.ollama_base}

    try:
        for piece in stream_llm(args.llm, SYSTEM_PROMPT_CN, prompt, **llm_kwargs):
            print(piece, end="", flush=True)
        print()
    except Exception as e:
        print(f"\n[rag] LLM error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
