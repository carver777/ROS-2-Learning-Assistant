"""LLM 调用：DeepSeek / Ollama 的流式 SSE 与同步 JSON 模式。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


async def _gen_deepseek(messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
    """异步生成器：从 DeepSeek 流式拉取 SSE 内容片段（仅 yield SSE 行）。"""
    if not DEEPSEEK_API_KEY:
        yield f"data: {json.dumps({'error': '未配置 DEEPSEEK_API_KEY'})}\n\n"
        return

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.5,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield f"data: {json.dumps({'error': f'DeepSeek 错误 {resp.status_code}: {body.decode()}'})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        data = json.loads(chunk)
                        content = data["choices"][0]["delta"].get("content", "")
                        if content:
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    except Exception:
                        continue
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def _gen_ollama(messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.5, "num_predict": max_tokens},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield f"data: {json.dumps({'error': f'Ollama 错误 {resp.status_code}: {body.decode()}'})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("done"):
                            yield "data: [DONE]\n\n"
                            return
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    except Exception:
                        continue
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


def llm_gen(messages: list[dict], max_tokens: int = 600) -> AsyncIterator[str]:
    """根据 ``LLM_PROVIDER`` 选择异步生成器。"""
    if LLM_PROVIDER == "ollama":
        return _gen_ollama(messages, max_tokens=max_tokens)
    return _gen_deepseek(messages, max_tokens=max_tokens)


async def stream_llm(system: str, user: str, max_tokens: int = 400) -> StreamingResponse:
    """单轮 system+user 的流式响应（保留旧函数签名，便于兼容）。"""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return StreamingResponse(llm_gen(msgs, max_tokens=max_tokens), media_type="text/event-stream")


async def call_llm_json(system: str, user: str, max_tokens: int = 800) -> dict:
    """非流式调用 + JSON 输出。适合需要结构化结果的 Agent（出题）。

    DeepSeek 支持 ``response_format={"type": "json_object"}``；
    Ollama 走 ``format="json"``。
    """
    if LLM_PROVIDER == "ollama":
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.7, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
    else:
        if not DEEPSEEK_API_KEY:
            raise HTTPException(status_code=500, detail="未配置 DEEPSEEK_API_KEY")
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM 返回的 JSON 无法解析：{e}；原文：{content[:300]}",
        )
