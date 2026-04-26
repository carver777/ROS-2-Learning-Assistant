from __future__ import annotations

"""Executable requirements spec for ROS-2-Learning-Assistant.

这些测试不是在测“实现细节”，而是在定义系统“必须做到什么”。
运行通过 = 需求满足。
"""

import json


def _parse_sse_events(raw_text: str) -> list[dict | str]:
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


def test_req_health_endpoint_must_report_runtime_status(client):
    """需求：系统必须提供健康检查，暴露运行时关键状态。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data
    assert "rag_enabled" in data
    assert "key_configured" in data


def test_req_chat_must_support_streaming_and_meta(client, mock_llm_stream, mock_rag):
    """需求：聊天接口必须是流式输出，并首帧返回检索元信息。"""
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "解释 ROS2 topic"}],
            "use_rag": "on",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert "meta" in events[0]
    assert "sources" in events[0]["meta"]
    assert any(isinstance(e, dict) and "content" in e for e in events)
    assert "[DONE]" in events


def test_req_quiz_generate_mcq_must_return_structured_question(client, mock_llm_json, mock_rag):
    """需求：系统必须能生成结构化选择题（4选项+标准答案）。"""
    resp = client.post(
        "/quiz/generate",
        json={"topic": "topic", "qtype": "mcq", "difficulty": "medium"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "mcq"
    assert isinstance(data["question"], str) and data["question"]
    assert isinstance(data["options"], list) and len(data["options"]) == 4
    assert data["answer"] in ["A", "B", "C", "D"]


def test_req_quiz_grade_must_return_numeric_score_and_feedback(client):
    """需求：系统必须返回可量化评分和文本反馈。"""
    resp = client.post(
        "/quiz/grade",
        json={
            "question": "x",
            "qtype": "mcq",
            "options": ["a", "b", "c", "d"],
            "reference_answer": "A",
            "user_answer": "A",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["score"], int)
    assert 0 <= data["score"] <= 100
    assert data["verdict"] in ["correct", "partially_correct", "incorrect"]
    assert isinstance(data["feedback"], str) and data["feedback"]


def test_req_roadmap_generate_must_return_learnable_sections(client, mock_llm_json, mock_rag):
    """需求：系统必须能生成可学习路线（至少一节，含目标与概念）。"""
    resp = client.post(
        "/roadmap/generate",
        json={
            "goal": "学习 ROS2 通信",
            "level": "beginner",
            "focus": "topic service",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("sections"), list) and len(data["sections"]) >= 1
    first = data["sections"][0]
    assert isinstance(first.get("title"), str) and first["title"]
    assert isinstance(first.get("objectives"), list)
    assert isinstance(first.get("key_concepts"), list)


def test_req_explain_node_must_stream_explanation(client, mock_llm_stream, mock_rag):
    """需求：节点讲解接口必须返回可流式渲染内容。"""
    resp = client.post(
        "/explain/node",
        json={
            "node_label": "talker",
            "node_type": "publisher",
            "package": "demo_nodes_cpp",
            "description": "publish string",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert "meta" in events[0]
    assert any(isinstance(e, dict) and "content" in e for e in events)
    assert "[DONE]" in events
