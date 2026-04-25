"""Build a Qdrant (local file-mode) hybrid index for the cleaned ROS 2 RAG chunks.

Uses BGE-M3 to produce dense (1024-d) + sparse (lexical) vectors in one pass,
stores both as named vectors so Qdrant can RRF-fuse them at query time.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import rag_common

# Import torch first on Windows; see note in rag_common.py.
import torch  # noqa: F401
from qdrant_client.models import PointStruct
from rag_common import (
    DENSE_NAME,
    SPARSE_NAME,
    ensure_collection,
    iter_chunks,
    load_bge_m3,
    open_qdrant,
    to_sparse,
)
from tqdm import tqdm


def batched(iterable, batch_size: int):
    batch = []
    for x in iterable:
        batch.append(x)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def main() -> None:
    p = argparse.ArgumentParser(description="Build BGE-M3 hybrid Qdrant index.")
    p.add_argument(
        "--chunks-path", type=Path, default=Path("database/ros2-kilted-clean/chunks.jsonl")
    )
    p.add_argument(
        "--qdrant-path", type=Path, default=Path("database/ros2-kilted-clean/qdrant_store")
    )
    p.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Override Qdrant collection name (default: from rag_common.COLLECTION).",
    )
    p.add_argument(
        "--batch-size", type=int, default=12, help="Encoding batch size (lower if RAM limited)."
    )
    p.add_argument("--max-length", type=int, default=1024, help="Max tokens per chunk for BGE-M3.")
    p.add_argument(
        "--no-fp16", action="store_true", help="Disable fp16 (slower but fp32 reproducible)."
    )
    p.add_argument(
        "--recreate", action="store_true", help="Drop and recreate the Qdrant collection."
    )
    p.add_argument(
        "--limit", type=int, default=0, help="Only index the first N chunks (for smoke tests)."
    )
    args = p.parse_args()

    if args.collection:
        rag_common.COLLECTION = args.collection

    chunks = list(iter_chunks(args.chunks_path))
    if args.limit > 0:
        chunks = chunks[: args.limit]
    total = len(chunks)
    print(f"Loaded {total} chunks from {args.chunks_path}")

    print("Loading BGE-M3 ...")
    t0 = time.time()
    model = load_bge_m3(use_fp16=not args.no_fp16)
    print(f"  ready in {time.time() - t0:.1f}s")

    print(f"Opening Qdrant at {args.qdrant_path} ...")
    client = open_qdrant(args.qdrant_path)
    ensure_collection(client, recreate=args.recreate)

    total_encoded = 0
    start = time.time()
    for batch_i, batch in enumerate(
        tqdm(list(batched(chunks, args.batch_size)), desc="encode+upsert")
    ):
        texts = [c.embed_text for c in batch]
        out = model.encode(
            texts,
            batch_size=len(texts),
            max_length=args.max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = np.asarray(out["dense_vecs"], dtype=np.float32)
        sparse_list = out["lexical_weights"]

        points = []
        for local_idx, chunk in enumerate(batch):
            global_idx = batch_i * args.batch_size + local_idx
            points.append(
                PointStruct(
                    id=global_idx,
                    vector={
                        DENSE_NAME: dense[local_idx].tolist(),
                        SPARSE_NAME: to_sparse(sparse_list[local_idx]),
                    },
                    payload={
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.doc_id,
                        "url": chunk.url,
                        "title": chunk.title,
                        "breadcrumb": chunk.breadcrumb,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                    },
                )
            )
        client.upsert(collection_name=rag_common.COLLECTION, points=points)
        total_encoded += len(batch)

    elapsed = time.time() - start
    print(
        f"\nIndexed {total_encoded} chunks in {elapsed:.1f}s "
        f"({total_encoded / max(1.0, elapsed):.1f} chunks/s)"
    )

    info = client.get_collection(rag_common.COLLECTION)
    print(f"Collection '{rag_common.COLLECTION}' points: {info.points_count}")

    meta = {
        "collection": rag_common.COLLECTION,
        "dense_dim": 1024,
        "embedding_model": "BAAI/bge-m3",
        "chunk_count": total_encoded,
        "qdrant_path": str(args.qdrant_path),
        "chunks_path": str(args.chunks_path),
        "elapsed_seconds": round(elapsed, 1),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (args.qdrant_path.parent / "index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
