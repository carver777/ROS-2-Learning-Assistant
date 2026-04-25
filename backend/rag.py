"""RAG 检索：BGE-M3 混合检索 + reranker 精排 + 上下文拼装 + ROS 2 意图识别。"""

from __future__ import annotations

import re
import sys
import time

from backend import state
from backend.config import RAG_ENABLED, RAG_RERANK_POOL, RAG_TOP_K, SCRIPTS_DIR

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ── ROS 2 意图识别（关键词命中即走 RAG） ───────────────────────────────────────
_ROS2_EN = re.compile(
    r"(?i)\b(ros\s*2?|topic|service|action|node|publisher|subscriber|qos|"
    r"rcl(?:py|cpp)|colcon|ament|urdf|sdf|xacro|gazebo|rviz2?|tf2?|"
    r"lifecycle|launchfile|launch\.py|executor|callback\s*group|"
    r"nav2|moveit2?|fast.?dds|cyclone.?dds|micro.?ros|"
    r"sensor_msgs|std_msgs|geometry_msgs|nav_msgs|"
    r"\.msg|\.srv|\.action|ament_cmake|ament_python)\b"
)
_ROS2_ZH = re.compile(
    r"(节点|话题|订阅者|发布者|订阅|发布|消息类型|参数服务器|"
    r"行为服务|生命周期节点|启动文件|工作空间|功能包|机器人操作系统)"
)


def is_ros2_query(text: str) -> bool:
    """判断文本是否疑似 ROS 2 相关问题（用于 chat 自动决定走 RAG）。"""
    if not text:
        return False
    return bool(_ROS2_EN.search(text) or _ROS2_ZH.search(text))


async def retrieve_context(query: str) -> list[dict]:
    """混合检索 + reranker 精排，返回 top-k chunk 列表。

    异常时降级返回空列表（让上层回退到纯 LLM）。
    """
    if not RAG_ENABLED or not state.is_ready():
        return []
    try:
        return _sync_retrieve(query)
    except Exception as e:
        print(f"[RAG] 检索失败，降级为纯 LLM: {e}", flush=True)
        return []


def _sync_retrieve(query: str) -> list[dict]:
    """同步检索逻辑（耗时分段打印用于诊断）。"""
    import rag_common  # 来自 SCRIPTS_DIR

    bge = state.bge_model
    reranker = state.reranker
    clients = state.qdrant_clients

    t0 = time.perf_counter()
    enc = bge.encode(
        [query],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vec = enc["dense_vecs"][0]
    sparse_vec = rag_common.to_sparse(enc["lexical_weights"][0])
    t1 = time.perf_counter()

    # 多数据集并查：每个库各取 RAG_RERANK_POOL 条候选，url 去重后合并
    seen_urls: set[str] = set()
    candidates: list[dict] = []
    per_dataset_counts: list[str] = []
    for label, client, coll in clients:
        hits = rag_common.hybrid_search(
            client,
            dense_vec,
            sparse_vec,
            limit=RAG_RERANK_POOL,
            prefetch_limit=RAG_RERANK_POOL * 2,
            collection_name=coll,
        )
        kept = 0
        for pt in hits:
            p = pt.payload or {}
            url = p.get("url", "")
            # 同一条文档不同集合可能重复，去重保留首个出现（先到先得）
            dedup_key = url or f"_id:{label}:{pt.id}"
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)
            candidates.append(
                {
                    "score": float(pt.score or 0),
                    "url": url,
                    "title": p.get("title", ""),
                    "breadcrumb": p.get("breadcrumb", ""),
                    "text": p.get("text", ""),
                    "dataset": label,
                }
            )
            kept += 1
        per_dataset_counts.append(f"{label}={kept}")
    t2 = time.perf_counter()

    if len(candidates) > 1:
        pairs = [[query, c["text"]] for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [float(scores)]
        for c, s in zip(candidates, scores, strict=False):
            c["rerank"] = float(s)
        candidates.sort(key=lambda x: x.get("rerank", 0), reverse=True)
    t3 = time.perf_counter()

    print(
        f"[RAG] encode={(t1 - t0) * 1000:.0f}ms  search={(t2 - t1) * 1000:.0f}ms  "
        f"rerank={(t3 - t2) * 1000:.0f}ms  pool={len(candidates)} "
        f"({', '.join(per_dataset_counts)}) -> top{RAG_TOP_K}",
        flush=True,
    )
    return candidates[:RAG_TOP_K]


def build_rag_context(chunks: list[dict]) -> str:
    """将检索到的 chunks 拼成 prompt 中的上下文块。"""
    if not chunks:
        return ""
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(f"[{i}] {c['title']} | {c['breadcrumb']}\n来源：{c['url']}\n{c['text']}")
    return "\n\n---\n\n".join(blocks)


def chunks_to_sources(chunks: list[dict]) -> list[dict]:
    """从 chunks 提取面向前端的 source 元信息（去掉 text 正文）。"""
    return [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "breadcrumb": c.get("breadcrumb", ""),
        }
        for c in chunks
    ]
