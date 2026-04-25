"""通用聊天接口（自动判断是否走 RAG）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.llm import llm_gen
from backend.prompts import SYSTEM_PROMPT_CHAT, SYSTEM_PROMPT_CHAT_RAG
from backend.rag import build_rag_context, chunks_to_sources, is_ros2_query, retrieve_context
from backend.schemas import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest):
    """通用聊天接口：自动判断是否走 RAG。

    前端可传 ``use_rag``：
      - ``"auto"``（默认）：根据最新一条 user 消息的关键词判断
      - ``"on"``  ：强制走 RAG
      - ``"off"`` ：纯 LLM
    流式 SSE 第一帧为 meta：``{"meta": {"used_rag": bool, "sources": [...]}}``
    后续为 ``{"content": "..."}`` 直到 ``[DONE]``。
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    if not last_user.strip():
        raise HTTPException(status_code=400, detail="最后一条用户消息为空")

    if req.use_rag == "on":
        do_rag = True
    elif req.use_rag == "off":
        do_rag = False
    else:
        do_rag = is_ros2_query(last_user)

    chunks: list[dict] = []
    if do_rag:
        chunks = await retrieve_context(last_user)

    if chunks:
        ctx = build_rag_context(chunks)
        msgs = [{"role": "system", "content": SYSTEM_PROMPT_CHAT_RAG}]
        # 历史保留除最后一条 user 外的全部，最后一条 user 注入参考文档
        history = list(req.messages[:-1])
        for m in history:
            msgs.append({"role": m.role, "content": m.content})
        msgs.append(
            {
                "role": "user",
                "content": f"{last_user}\n\n【参考文档】\n{ctx}",
            }
        )
    else:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}]
        for m in req.messages:
            msgs.append({"role": m.role, "content": m.content})

    meta_event = {
        "meta": {
            "used_rag": bool(chunks),
            "rag_attempted": do_rag,
            "sources": chunks_to_sources(chunks),
        }
    }

    async def generate():
        yield f"data: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
        async for chunk_line in llm_gen(msgs, max_tokens=600):
            yield chunk_line

    return StreamingResponse(generate(), media_type="text/event-stream")
