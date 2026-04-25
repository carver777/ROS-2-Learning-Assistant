"""Pydantic 请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel


class NodeExplainRequest(BaseModel):
    node_label: str
    node_type: str
    package: str | None = None
    description: str | None = None
    qos: dict | None = None


class EdgeExplainRequest(BaseModel):
    topic_name: str
    edge_type: str
    msg_type: str | None = None
    hz: float | None = None


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_rag: str = "auto"  # "auto" | "on" | "off"


class QuizGenerateRequest(BaseModel):
    topic: str | None = None  # 用户指定主题；留空则随机
    qtype: str = "mcq"  # "mcq"（选择题）| "short"（简答题）
    difficulty: str = "medium"  # "easy" | "medium" | "hard"


class QuizGradeRequest(BaseModel):
    question: str
    qtype: str
    options: list[str] | None = None
    reference_answer: str  # 出题时返回的标准答案
    user_answer: str


class QuizExplainRequest(BaseModel):
    question: str
    qtype: str
    options: list[str] | None = None
    reference_answer: str
    explanation_hint: str | None = None  # 出题时附带的简短解析
    sources: list[dict] | None = None  # 出题时检索到的文档来源


# ── Roadmap ──────────────────────────────────────────────────────────────────
class RoadmapGenerateRequest(BaseModel):
    """学习路线生成请求。

    - 传 ``preset_id`` 走预制路线（快、固定）
    - 传 ``goal`` 走 LLM+RAG 自定义生成
    """

    preset_id: str | None = None
    goal: str | None = None
    level: str = "beginner"  # beginner | intermediate | advanced
    focus: str | None = None  # 重点方向（如 "导航 / 控制 / 仿真"）


class RoadmapSectionExplainRequest(BaseModel):
    """对路线中某一节请求 LLM 流式讲解。"""

    roadmap_title: str
    section_title: str
    objectives: list[str]
    key_concepts: list[str]
