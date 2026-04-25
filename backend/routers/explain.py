"""节点 / 边解释接口。"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.llm import llm_gen
from backend.prompts import SYSTEM_PROMPT_BASE, SYSTEM_PROMPT_RAG
from backend.rag import build_rag_context, chunks_to_sources, retrieve_context
from backend.schemas import EdgeExplainRequest, NodeExplainRequest

router = APIRouter()


def _explain_stream(system: str, user: str, chunks: list[dict], max_tokens: int = 400):
    """统一的 explain 流：先发 meta（含 sources），再流 LLM。"""
    meta = {"meta": {"used_rag": bool(chunks), "sources": chunks_to_sources(chunks)}}
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def gen():
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        async for line in llm_gen(msgs, max_tokens=max_tokens):
            yield line

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/explain/node")
async def explain_node(req: NodeExplainRequest):
    parts = [f"ROS 2 节点 `{req.node_label}`，类型是 {req.node_type}"]
    if req.package:
        parts.append(f"所属包：{req.package}")
    if req.description:
        parts.append(f"已知信息：{req.description}")
    if req.qos:
        parts.append("QoS：" + "、".join(f"{k}={v}" for k, v in req.qos.items()))

    query = "、".join(parts)

    chunks = await retrieve_context(f"{req.node_label} {req.node_type} {req.package or ''} ROS 2")

    if chunks:
        user_prompt = f"请解释 {query}。\n\n【参考文档】\n{build_rag_context(chunks)}"
        system = SYSTEM_PROMPT_RAG
    else:
        user_prompt = f"请解释 {query}。"
        system = SYSTEM_PROMPT_BASE

    return _explain_stream(system, user_prompt, chunks)


@router.post("/explain/edge")
async def explain_edge(req: EdgeExplainRequest):
    parts = [f"ROS 2 通信通道 `{req.topic_name}`，类型是 {req.edge_type}"]
    if req.msg_type:
        parts.append(f"消息类型：{req.msg_type}")
    if req.hz:
        parts.append(f"发布频率：{req.hz} Hz")

    chunks = await retrieve_context(
        f"{req.topic_name} {req.edge_type} {req.msg_type or ''} ROS 2 topic"
    )

    if chunks:
        user_prompt = f"请解释 {'，'.join(parts)}。\n\n【参考文档】\n{build_rag_context(chunks)}"
        system = SYSTEM_PROMPT_RAG
    else:
        user_prompt = "，".join(parts) + "。"
        system = SYSTEM_PROMPT_BASE

    return _explain_stream(system, user_prompt, chunks)
