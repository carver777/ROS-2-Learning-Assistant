from __future__ import annotations

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


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data
    assert "rag_enabled" in data


def test_chat_rejects_empty_messages(client):
    resp = client.post("/chat", json={"messages": [], "use_rag": "auto"})
    assert resp.status_code == 400
    assert "messages" in resp.json()["detail"]


def test_chat_rejects_when_last_user_empty(client):
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "assistant", "content": "hello"}],
            "use_rag": "auto",
        },
    )
    assert resp.status_code == 400
    assert "最后一条用户消息为空" in resp.json()["detail"]


def test_chat_stream_with_rag_on_contains_meta_and_content(client, mock_llm_stream, mock_rag):
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "ROS2 topic 是什么？"}],
            "use_rag": "on",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert events[0]["meta"]["rag_attempted"] is True
    assert events[0]["meta"]["used_rag"] is True
    assert len(events[0]["meta"]["sources"]) >= 1
    assert any(isinstance(e, dict) and e.get("content") == "测试回答" for e in events)
    assert "[DONE]" in events


def test_chat_stream_with_rag_off_meta_flags(client, mock_llm_stream, mock_rag):
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "ROS2 topic 是什么？"}],
            "use_rag": "off",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert events[0]["meta"]["rag_attempted"] is False
    assert events[0]["meta"]["used_rag"] is False


def test_quiz_generate_mcq_success(client, mock_llm_json, mock_rag):
    resp = client.post(
        "/quiz/generate",
        json={"topic": "topic", "qtype": "mcq", "difficulty": "easy"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "mcq"
    assert len(data["options"]) == 4
    assert data["answer"] in ["A", "B", "C", "D"]


def test_quiz_generate_rejects_invalid_qtype(client):
    resp = client.post(
        "/quiz/generate",
        json={"topic": "topic", "qtype": "essay", "difficulty": "easy"},
    )
    assert resp.status_code == 400
    assert "qtype" in resp.json()["detail"]


def test_quiz_grade_mcq_correct_returns_full_score(client):
    resp = client.post(
        "/quiz/grade",
        json={
            "question": "x",
            "qtype": "mcq",
            "options": ["a", "b", "c", "d"],
            "reference_answer": "B",
            "user_answer": "b",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 100
    assert data["verdict"] == "correct"


def test_quiz_grade_empty_answer_returns_zero(client):
    resp = client.post(
        "/quiz/grade",
        json={
            "question": "x",
            "qtype": "short",
            "options": None,
            "reference_answer": "ref",
            "user_answer": "   ",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 0
    assert data["verdict"] == "incorrect"


def test_roadmap_presets_available(client):
    resp = client.get("/roadmap/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert "presets" in data
    assert len(data["presets"]) >= 1


def test_roadmap_generate_preset_success(client, mock_rag):
    resp = client.post("/roadmap/generate", json={"preset_id": "beginner"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "beginner"
    assert data["is_preset"] is True
    assert isinstance(data["sections"], list) and len(data["sections"]) >= 1


def test_roadmap_generate_custom_requires_goal(client):
    resp = client.post(
        "/roadmap/generate",
        json={"goal": "", "level": "beginner", "focus": "nav"},
    )
    assert resp.status_code == 400
    assert "goal" in resp.json()["detail"]


def test_explain_node_stream_has_meta_and_content(client, mock_llm_stream, mock_rag):
    resp = client.post(
        "/explain/node",
        json={
            "node_label": "camera_node",
            "node_type": "publisher",
            "package": "demo_pkg",
            "description": "publish image",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert events[0]["meta"]["used_rag"] is True
    assert any(isinstance(e, dict) and e.get("content") == "测试回答" for e in events)


def test_explain_edge_stream_has_meta_and_content(client, mock_llm_stream, mock_rag):
    resp = client.post(
        "/explain/edge",
        json={
            "topic_name": "/camera/image_raw",
            "edge_type": "topic",
            "msg_type": "sensor_msgs/Image",
            "hz": 30,
        },
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert isinstance(events[0], dict)
    assert events[0]["meta"]["used_rag"] is True
    assert any(isinstance(e, dict) and e.get("content") == "测试回答" for e in events)
