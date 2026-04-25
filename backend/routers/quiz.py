"""Quiz 多 Agent 接口：出题 / 评分 / 讲解。"""

from __future__ import annotations

import json
import random

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.llm import call_llm_json, llm_gen
from backend.rag import build_rag_context, chunks_to_sources, retrieve_context
from backend.schemas import QuizExplainRequest, QuizGenerateRequest, QuizGradeRequest

router = APIRouter()


# ── Quiz 专属 Prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT_QUIZ_GENERATOR = """你是一名 ROS 2 资深讲师，正在为学生出题。
请根据【参考文档】出 1 道高质量的题目，**严格输出 JSON**，不要任何额外文字、不要 Markdown 代码块。

JSON Schema：
- "type"      : "mcq" 或 "short"（必须与用户要求一致）
- "question"  : 题干（中文，简洁清晰）
- "options"   : 当 type=mcq 时为长度 4 的字符串数组（A/B/C/D 内容，不要带 "A. " 前缀）；type=short 时省略或为 null
- "answer"    : 当 type=mcq 时为 "A"/"B"/"C"/"D" 之一；type=short 时为参考答案文本（2-4 句话）
- "explanation": 1-3 句话的简短解析，说明为什么答案是这样

要求：
1. 题目必须基于【参考文档】中的真实概念，不要凭空捏造
2. 题干和选项要简洁，避免歧义
3. 选择题的干扰项必须有迷惑性，但不能模棱两可
4. 难度严格按用户指定的等级
5. 只输出 JSON，不要其他任何字符"""


SYSTEM_PROMPT_QUIZ_GRADER = """你是严谨的 ROS 2 评分老师，根据"参考答案"评判"用户答案"。

请**严格输出 JSON**，不要任何额外文字、不要 Markdown 代码块：
- "score"   : 0-100 的整数
- "verdict" : "correct" / "partially_correct" / "incorrect" 三选一
- "feedback": 2-4 句话的中文反馈，指出对在哪、错在哪、缺了什么

打分规则：
- 选择题：选对 = 100；选错 = 0
- 简答题：完全覆盖关键点 = 90-100；覆盖大部分 = 60-85；只沾边 = 30-55；完全错或空 = 0-25
- 用户答案为空或乱填 → 0 分
- 反馈语气客观、有建设性，避免空话"""


SYSTEM_PROMPT_QUIZ_EXPLAINER = """你是 ROS 2 资深讲师，给学生详细讲解题目。
请用中文 Markdown 格式输出，结构如下：

### 标准答案
（直接给出答案；选择题写出选项字母 + 内容）

### 详细解析
（分点讲清楚为什么是这个答案，涉及的 ROS 2 概念是什么，干扰项错在哪——若是选择题）

### 延伸知识
（1-2 个相关知识点，帮助学生举一反三）

要求：
- 解析要扎实、严谨，可适度引用【参考文档】中的内容
- 若提到来源，使用 [1]/[2] 标号方式（与 RAG 文档顺序一致）
- 不要重复题干
- 当解析涉及多个概念的对比/区别时，**必须**用 Markdown 表格列出对比维度（至少 3 行，含表头）
- 适度使用 `行内代码` 和 ```代码块``` 提升可读性"""


# 出题主题种子（无主题时随机抽一个，保证话题多样性）
_SEED_TOPICS = [
    "node lifecycle",
    "QoS profile",
    "topic publisher subscriber",
    "service client server",
    "action goal feedback",
    "parameter declare",
    "launch file substitution",
    "tf2 transform",
    "rclcpp executor",
    "rclpy callback group",
    "DDS discovery",
    "message filter",
    "component composition",
    "ros2 bag record",
    "URDF xacro",
    "navigation2 behavior tree",
    "MoveIt planning",
]


def _format_quiz_question(req) -> str:
    """把题目格式化成 grader/explainer 输入用的纯文本。"""
    lines = [f"题型：{'选择题' if req.qtype == 'mcq' else '简答题'}", f"题干：{req.question}"]
    if req.qtype == "mcq" and req.options:
        labels = ["A", "B", "C", "D"]
        for lab, opt in zip(labels, req.options, strict=False):
            lines.append(f"  {lab}. {opt}")
    return "\n".join(lines)


@router.post("/quiz/generate")
async def quiz_generate(req: QuizGenerateRequest):
    """出题 Agent：基于 RAG 检索到的内容生成一道题目（含答案）。"""
    if req.qtype not in ("mcq", "short"):
        raise HTTPException(status_code=400, detail="qtype 必须是 mcq 或 short")
    if req.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="difficulty 必须是 easy/medium/hard")

    if req.topic and req.topic.strip():
        query = f"ROS 2 {req.topic.strip()}"
    else:
        query = "ROS 2 " + random.choice(_SEED_TOPICS)

    chunks = await retrieve_context(query)
    if not chunks:
        raise HTTPException(
            status_code=503,
            detail="知识库未返回内容，无法出题。请检查 RAG 是否启用。",
        )

    qtype_zh = "选择题（4 选 1）" if req.qtype == "mcq" else "简答题"
    diff_zh = {
        "easy": "简单（基础概念）",
        "medium": "中等（理解+应用）",
        "hard": "困难（综合分析或易混淆点）",
    }[req.difficulty]

    user_prompt = (
        f"请出 1 道 ROS 2 {qtype_zh}，难度：{diff_zh}。\n"
        f"主题方向：{req.topic.strip() if req.topic else '从下面参考文档中自由选取一个核心概念'}。\n\n"
        f"【参考文档】\n{build_rag_context(chunks)}\n\n"
        f'严格按 JSON 格式输出（type 必须为 "{req.qtype}"）。'
    )

    quiz = await call_llm_json(SYSTEM_PROMPT_QUIZ_GENERATOR, user_prompt, max_tokens=900)

    if quiz.get("type") not in ("mcq", "short"):
        quiz["type"] = req.qtype
    if req.qtype == "mcq":
        opts = quiz.get("options") or []
        if not isinstance(opts, list) or len(opts) != 4:
            raise HTTPException(status_code=502, detail=f"出题 Agent 返回的选项数量非法：{opts}")
        ans = (quiz.get("answer") or "").strip().upper()
        if ans not in ("A", "B", "C", "D"):
            raise HTTPException(status_code=502, detail=f"出题 Agent 返回的答案非法：{ans}")
        quiz["answer"] = ans

    return {
        "type": quiz.get("type", req.qtype),
        "question": quiz.get("question", "").strip(),
        "options": quiz.get("options") if req.qtype == "mcq" else None,
        "answer": quiz.get("answer", ""),
        "explanation": quiz.get("explanation", "").strip(),
        "sources": chunks_to_sources(chunks),
        "topic_used": query,
    }


@router.post("/quiz/grade")
async def quiz_grade(req: QuizGradeRequest):
    """评分 Agent：对比用户答案与参考答案，给出 0-100 分和反馈。"""
    if not req.user_answer.strip():
        return {"score": 0, "verdict": "incorrect", "feedback": "未作答。"}

    # 选择题先做规则判分（更稳），再让 LLM 给反馈
    if req.qtype == "mcq":
        ref = req.reference_answer.strip().upper()
        usr = req.user_answer.strip().upper()
        if usr == ref:
            return {
                "score": 100,
                "verdict": "correct",
                "feedback": f"回答正确，{ref} 选项就是答案。",
            }
        question_text = _format_quiz_question(req)
        user_prompt = (
            f"{question_text}\n\n"
            f"参考答案：{ref}\n用户答案：{usr}\n\n"
            f"用户选错了，请给一句简短的中文反馈（不要超过 2 句话），"
            f"指出他选错的原因，不要透露详细解析（之后会有讲解环节）。"
            f'严格 JSON，score=0，verdict="incorrect"。'
        )
        result = await call_llm_json(
            SYSTEM_PROMPT_QUIZ_GRADER,
            user_prompt,
            max_tokens=200,
        )
        result["score"] = 0
        result["verdict"] = "incorrect"
        return result

    # 简答题完全交给 LLM 评分
    question_text = _format_quiz_question(req)
    user_prompt = (
        f"{question_text}\n\n"
        f"参考答案：\n{req.reference_answer}\n\n"
        f"用户答案：\n{req.user_answer}\n\n"
        f"请评分并反馈，严格 JSON 格式。"
    )
    return await call_llm_json(
        SYSTEM_PROMPT_QUIZ_GRADER,
        user_prompt,
        max_tokens=300,
    )


@router.post("/quiz/explain")
async def quiz_explain(req: QuizExplainRequest):
    """讲解 Agent：详细讲解题目和正确答案，流式输出。"""
    question_text = _format_quiz_question(req)

    # 优先复用出题时的来源；若前端没传，再现场检索一次
    if req.sources:
        sources = req.sources
        ctx_block = ""  # 没有原始 chunk 内容，但来源足以提示
    else:
        chunks = await retrieve_context(req.question)
        sources = chunks_to_sources(chunks)
        ctx_block = build_rag_context(chunks) if chunks else ""

    parts = [
        question_text,
        f"\n参考答案：{req.reference_answer}",
    ]
    if req.explanation_hint:
        parts.append(f"\n出题人提示的解析要点：{req.explanation_hint}")
    if ctx_block:
        parts.append(f"\n【参考文档】\n{ctx_block}")
    user_prompt = "\n".join(parts) + "\n\n请按系统提示的结构详细讲解。"

    meta = {"meta": {"used_rag": bool(sources), "sources": sources}}
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT_QUIZ_EXPLAINER},
        {"role": "user", "content": user_prompt},
    ]

    async def gen():
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        async for line in llm_gen(msgs, max_tokens=900):
            yield line

    return StreamingResponse(gen(), media_type="text/event-stream")
