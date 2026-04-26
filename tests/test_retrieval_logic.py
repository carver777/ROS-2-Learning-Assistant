from __future__ import annotations

from backend.rag import build_rag_context, chunks_to_sources, is_ros2_query


def test_is_ros2_query_detects_english_keywords():
    assert is_ros2_query("How does ROS 2 topic QoS work?") is True


def test_is_ros2_query_detects_chinese_keywords():
    assert is_ros2_query("请解释一下 ROS2 节点和话题") is True


def test_is_ros2_query_rejects_unrelated_text():
    assert is_ros2_query("今天天气怎么样") is False


def test_build_rag_context_formats_numbered_blocks():
    chunks = [
        {
            "title": "ROS 2 Topic",
            "breadcrumb": "Concepts > Topic",
            "url": "https://docs.ros.org/en/test/topic",
            "text": "Topic is pub/sub.",
        },
        {
            "title": "ROS 2 Service",
            "breadcrumb": "Concepts > Service",
            "url": "https://docs.ros.org/en/test/service",
            "text": "Service is request/response.",
        },
    ]
    ctx = build_rag_context(chunks)
    assert "[1] ROS 2 Topic" in ctx
    assert "[2] ROS 2 Service" in ctx
    assert "来源：https://docs.ros.org/en/test/topic" in ctx


def test_chunks_to_sources_drops_text_body_only_keep_metadata():
    chunks = [
        {
            "title": "A",
            "url": "https://example.com/a",
            "breadcrumb": "B > C",
            "text": "very long text",
        }
    ]
    sources = chunks_to_sources(chunks)
    assert sources == [{"title": "A", "url": "https://example.com/a", "breadcrumb": "B > C"}]
