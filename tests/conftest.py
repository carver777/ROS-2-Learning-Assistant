from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_llm_stream(monkeypatch: pytest.MonkeyPatch):
    async def _fake_llm_gen(messages: list[dict], max_tokens: int = 600):
        _ = messages, max_tokens
        yield f"data: {json.dumps({'content': '测试回答'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("backend.llm.llm_gen", _fake_llm_gen)
    monkeypatch.setattr("backend.routers.chat.llm_gen", _fake_llm_gen)
    monkeypatch.setattr("backend.routers.quiz.llm_gen", _fake_llm_gen)
    monkeypatch.setattr("backend.routers.roadmap.llm_gen", _fake_llm_gen)
    monkeypatch.setattr("backend.routers.explain.llm_gen", _fake_llm_gen)


@pytest.fixture
def mock_llm_json(monkeypatch: pytest.MonkeyPatch):
    async def _fake_call_llm_json(system: str, user: str, max_tokens: int = 800):
        _ = system, user, max_tokens
        return {
            "type": "mcq",
            "question": "ROS 2 中 Topic 的典型通信模式是？",
            "options": ["一对一同步", "发布订阅", "事务提交", "文件共享"],
            "answer": "B",
            "explanation": "Topic 采用发布订阅模型。",
            "title": "测试路线",
            "summary": "这是测试返回",
            "level": "beginner",
            "sections": [
                {
                    "title": "测试章节",
                    "objectives": ["理解 Topic"],
                    "key_concepts": ["topic", "publisher", "subscriber"],
                    "estimated_minutes": 30,
                }
            ],
            "score": 100,
            "verdict": "correct",
            "feedback": "回答正确。",
        }

    monkeypatch.setattr("backend.llm.call_llm_json", _fake_call_llm_json)
    monkeypatch.setattr("backend.routers.quiz.call_llm_json", _fake_call_llm_json)
    monkeypatch.setattr("backend.routers.roadmap.call_llm_json", _fake_call_llm_json)


@pytest.fixture
def mock_rag(monkeypatch: pytest.MonkeyPatch):
    async def _fake_retrieve_context(query: str):
        _ = query
        return [
            {
                "title": "ROS 2 Topic",
                "url": "https://docs.ros.org/en/test/topic",
                "breadcrumb": "Concepts > Topic",
                "text": "Topic is pub/sub communication in ROS 2.",
            }
        ]

    monkeypatch.setattr("backend.rag.retrieve_context", _fake_retrieve_context)
    monkeypatch.setattr("backend.routers.chat.retrieve_context", _fake_retrieve_context)
    monkeypatch.setattr("backend.routers.quiz.retrieve_context", _fake_retrieve_context)
    monkeypatch.setattr("backend.routers.roadmap.retrieve_context", _fake_retrieve_context)
    monkeypatch.setattr("backend.routers.explain.retrieve_context", _fake_retrieve_context)

    monkeypatch.setattr("backend.rag.is_ros2_query", lambda text: True)
    monkeypatch.setattr("backend.routers.chat.is_ros2_query", lambda text: True)


def parse_sse_events(raw_text: str) -> list[dict | str]:
    events: list[dict | str] = []
    for line in raw_text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            events.append("[DONE]")
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            events.append(payload)
    return events
