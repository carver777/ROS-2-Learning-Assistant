# MUST be the very first import on Windows to initialize CUDA DLL search paths
# before any other C extension (grpcio, protobuf, qdrant) loads conflicting DLLs.
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import torch  # noqa: F401
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent  # 项目根目录
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# ── 配置 ──────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")  # deepseek | ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() == "true"
QDRANT_PATH = ROOT / os.getenv("QDRANT_PATH", "database/ros2-kilted-clean/qdrant_store")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "ros2_kilted_chunks")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
RAG_RERANK_POOL = int(os.getenv("RAG_RERANK_POOL", "15"))
RAG_DEVICE = os.getenv("RAG_DEVICE", "cpu")


def _parse_datasets() -> list[tuple[str, str, str]]:
    """解析 QDRANT_DATASETS 配置。

    格式：`path1:collection1,path2:collection2`，路径相对项目根。
    返回 `[(label, abs_path, collection_name), ...]`。
    未配置则退回单数据集（QDRANT_PATH + QDRANT_COLLECTION）。
    """
    raw = os.getenv("QDRANT_DATASETS", "").strip()
    if not raw:
        return [("default", str(QDRANT_PATH), QDRANT_COLLECTION)]
    out = []
    for i, part in enumerate(raw.split(",")):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"QDRANT_DATASETS 第 {i+1} 项缺少冒号 (path:collection)：{part}")
        # Windows 路径里有 ':'（如 C:\xxx），所以从右侧切一刀
        path_part, _, coll = part.rpartition(":")
        abs_path = str(ROOT / path_part.strip())
        # 用 collection 名作 label，避免多库路径都以 qdrant_store 结尾时混淆
        label = coll.strip() or f"ds{i}"
        out.append((label, abs_path, coll.strip()))
    return out


RAG_DATASETS = _parse_datasets()  # [(label, path, collection)]

# ── RAG 全局单例（模块级初始化，在 uvicorn event loop 启动前完成） ────────────
_bge_model = None
_reranker = None
# 由 run_backend.py 注入：[(label, QdrantClient, collection_name), ...]
_qdrant_clients: list[tuple[str, object, str]] = []


# 模型由 run_backend.py 外部注入（避免 uvicorn 子进程 DLL 冲突）。
# 直接运行 uvicorn backend.main:app 时，在 /health 调用时会看到 rag_loaded=false。


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


async def retrieve_context(query: str) -> list[dict]:
    """混合检索 + reranker 精排，返回 top-k chunk 列表。"""
    if not RAG_ENABLED or _bge_model is None or not _qdrant_clients:
        return []
    try:
        return _sync_retrieve(query)
    except Exception as e:
        print(f"[RAG] 检索失败，降级为纯 LLM: {e}", flush=True)
        return []


def _sync_retrieve(query: str) -> list[dict]:
    """同步检索逻辑（耗时分段打印用于诊断）。"""
    import time

    import rag_common

    t0 = time.perf_counter()
    enc = _bge_model.encode(
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
    for label, client, coll in _qdrant_clients:
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
        scores = _reranker.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [float(scores)]
        for c, s in zip(candidates, scores, strict=False):
            c["rerank"] = float(s)
        candidates.sort(key=lambda x: x.get("rerank", 0), reverse=True)
    t3 = time.perf_counter()

    print(
        f"[RAG] encode={(t1-t0)*1000:.0f}ms  search={(t2-t1)*1000:.0f}ms  "
        f"rerank={(t3-t2)*1000:.0f}ms  pool={len(candidates)} "
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
        blocks.append(
            f"[{i}] {c['title']} | {c['breadcrumb']}\n" f"来源：{c['url']}\n" f"{c['text']}"
        )
    return "\n\n---\n\n".join(blocks)


# ── System Prompt ─────────────────────────────────────────────────────────────
# 所有 LLM 回答共享的格式约定：允许使用 Markdown，并在涉及对比时强制使用表格
MARKDOWN_FORMAT_RULES = """
【输出格式约定】
- 用 Markdown 输出，前端会渲染为富文本
- 适度使用 ## / ### 标题、`行内代码`、```代码块``` 和有序/无序列表组织内容
- 强调关键术语用 **粗体**
- 当用户的问题包含「对比 / 区别 / 差异 / 异同 / 选哪个 / vs / 什么时候用 A 什么时候用 B」等比较语义时，**必须**用 Markdown 表格列出对比维度，例如：

| 维度 | A | B |
|---|---|---|
| 通信模式 | 异步发布订阅 | 同步请求响应 |
| 适用场景 | 持续数据流 | 一次性查询 |

- 表格至少 3 行（含表头），列名要具体，避免空泛
- 不要在表格前后赘述"以下是表格"之类的废话
"""


SYSTEM_PROMPT_BASE = (
    """你是一位 ROS 2 专家教师，专门帮助初学者理解 ROS 2 概念。

回答要求：
- 用简洁明了的中文，控制在 500 字以内
- 解释这个组件的核心职责和在系统中的作用
- 适当用类比帮助理解（如"话题就像广播电台"）
- 末尾提一个初学者常见的坑或注意事项
"""
    + MARKDOWN_FORMAT_RULES
)


SYSTEM_PROMPT_RAG = (
    """你是一位 ROS 2 专家教师，基于官方文档回答用户问题。

回答要求：
- 用简洁明了的中文，控制在 500 字以内
- 严格基于下方【参考文档】的内容回答，不要编造
- 解释核心职责和作用，适当用类比
- 末尾提一个常见坑或注意事项
- 引用来源用 [n] 标注（对应参考文档编号）
"""
    + MARKDOWN_FORMAT_RULES
)


# 通用对话场景的系统提示（不带 RAG）
SYSTEM_PROMPT_CHAT = (
    """你是一位友好的 AI 助手。
- 用简洁的中文回答
- 如果用户的问题涉及 ROS 2 / 机器人开发，可以基于自身知识回答
- 其它领域的问题也正常回答，不必拒绝
"""
    + MARKDOWN_FORMAT_RULES
)


# RAG 场景的对话系统提示
SYSTEM_PROMPT_CHAT_RAG = (
    """你是一位 ROS 2 专家助手，基于官方文档回答用户问题。

回答要求：
- 用简洁明了的中文
- 优先使用下方【参考文档】中的事实，不要编造
- 引用来源用 [n] 标注（对应参考文档编号）
- 如果【参考文档】不足以回答，可结合自身知识补充并明确提示
"""
    + MARKDOWN_FORMAT_RULES
)


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


def _is_ros2_query(text: str) -> bool:
    if not text:
        return False
    return bool(_ROS2_EN.search(text) or _ROS2_ZH.search(text))


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="ROS2 Viz AI Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── LLM 流式生成 ──────────────────────────────────────────────────────────────
async def _gen_deepseek(messages: list[dict], max_tokens: int = 600):
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


async def _gen_ollama(messages: list[dict], max_tokens: int = 600):
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


def _llm_gen(messages: list[dict], max_tokens: int = 600):
    """根据 LLM_PROVIDER 选择异步生成器。"""
    if LLM_PROVIDER == "ollama":
        return _gen_ollama(messages, max_tokens=max_tokens)
    return _gen_deepseek(messages, max_tokens=max_tokens)


async def stream_llm(system: str, user: str, max_tokens: int = 400) -> StreamingResponse:
    """兼容旧接口：单轮 system+user 的流式响应。"""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return StreamingResponse(_llm_gen(msgs, max_tokens=max_tokens), media_type="text/event-stream")


async def call_llm_json(system: str, user: str, max_tokens: int = 800) -> dict:
    """非流式调用 + JSON 输出。适合需要结构化结果的 Agent（出题）。

    DeepSeek 支持 `response_format={"type": "json_object"}`；
    Ollama 走 `format="json"`。
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


# ── 请求模型 ──────────────────────────────────────────────────────────────────
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


# ── Quiz 相关 ─────────────────────────────────────────────────────────────────
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


# ── 接口 ──────────────────────────────────────────────────────────────────────
def _explain_stream(system: str, user: str, chunks: list[dict], max_tokens: int = 400):
    """统一的 explain 流：先发 meta（含 sources），再流 LLM。"""
    sources = [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "breadcrumb": c.get("breadcrumb", ""),
        }
        for c in chunks
    ]
    meta = {"meta": {"used_rag": bool(chunks), "sources": sources}}
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def gen():
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        async for line in _llm_gen(msgs, max_tokens=max_tokens):
            yield line

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/explain/node")
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


@app.post("/explain/edge")
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


@app.post("/chat")
async def chat(req: ChatRequest):
    """通用聊天接口：自动判断是否走 RAG。

    前端可传 `use_rag`：
      - "auto"（默认）：根据最新一条 user 消息的关键词判断
      - "on"  ：强制走 RAG
      - "off" ：纯 LLM
    流式 SSE 第一帧为 meta：{"meta": {"used_rag": bool, "sources": [...]}}
    后续为 {"content": "..."} 直到 [DONE]。
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    if not last_user.strip():
        raise HTTPException(status_code=400, detail="最后一条用户消息为空")

    # 决定是否走 RAG
    if req.use_rag == "on":
        do_rag = True
    elif req.use_rag == "off":
        do_rag = False
    else:
        do_rag = _is_ros2_query(last_user)

    chunks: list[dict] = []
    if do_rag:
        chunks = await retrieve_context(last_user)

    # 组装 messages
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

    sources = [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "breadcrumb": c.get("breadcrumb", ""),
        }
        for c in chunks
    ]
    meta_event = {
        "meta": {
            "used_rag": bool(chunks),
            "rag_attempted": do_rag,
            "sources": sources,
        }
    }

    async def generate():
        # 第一帧：meta（前端用来显示"已检索 N 篇文档"等）
        yield f"data: {json.dumps(meta_event, ensure_ascii=False)}\n\n"
        # 后续：LLM 流式内容
        async for chunk_line in _llm_gen(msgs, max_tokens=600):
            yield chunk_line

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Quiz Multi-Agent ─────────────────────────────────────────────────────────
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


def _format_quiz_question(req) -> str:
    """把题目格式化成 grader/explainer 输入用的纯文本。"""
    lines = [f"题型：{'选择题' if req.qtype == 'mcq' else '简答题'}", f"题干：{req.question}"]
    if req.qtype == "mcq" and req.options:
        labels = ["A", "B", "C", "D"]
        for lab, opt in zip(labels, req.options, strict=False):
            lines.append(f"  {lab}. {opt}")
    return "\n".join(lines)


@app.post("/quiz/generate")
async def quiz_generate(req: QuizGenerateRequest):
    """出题 Agent：基于 RAG 检索到的内容生成一道题目（含答案）。"""
    if req.qtype not in ("mcq", "short"):
        raise HTTPException(status_code=400, detail="qtype 必须是 mcq 或 short")
    if req.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="difficulty 必须是 easy/medium/hard")

    # 检索：有主题就按主题查；无主题就用一组通用 ROS 2 概念词触发随机主题
    if req.topic and req.topic.strip():
        query = f"ROS 2 {req.topic.strip()}"
    else:
        # 让 RAG 在常见概念中随机抓一些片段，制造话题多样性
        import random

        seed_topics = [
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
        query = "ROS 2 " + random.choice(seed_topics)

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
        f"严格按 JSON 格式输出（type 必须为 \"{req.qtype}\"）。"
    )

    quiz = await call_llm_json(SYSTEM_PROMPT_QUIZ_GENERATOR, user_prompt, max_tokens=900)

    # 校验和清理
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

    sources = [
        {
            "title": c.get("title", ""),
            "url": c.get("url", ""),
            "breadcrumb": c.get("breadcrumb", ""),
        }
        for c in chunks
    ]

    return {
        "type": quiz.get("type", req.qtype),
        "question": quiz.get("question", "").strip(),
        "options": quiz.get("options") if req.qtype == "mcq" else None,
        "answer": quiz.get("answer", ""),
        "explanation": quiz.get("explanation", "").strip(),
        "sources": sources,
        "topic_used": query,
    }


@app.post("/quiz/grade")
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
        # 错了让 LLM 简短点评
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


@app.post("/quiz/explain")
async def quiz_explain(req: QuizExplainRequest):
    """讲解 Agent：详细讲解题目和正确答案，流式输出。"""
    question_text = _format_quiz_question(req)

    # 优先复用出题时的来源；若前端没传，再现场检索一次
    if req.sources:
        sources = req.sources
        ctx_block = ""  # 没有原始 chunk 内容，但来源足以提示
    else:
        chunks = await retrieve_context(req.question)
        sources = [
            {
                "title": c.get("title", ""),
                "url": c.get("url", ""),
                "breadcrumb": c.get("breadcrumb", ""),
            }
            for c in chunks
        ]
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
        async for line in _llm_gen(msgs, max_tokens=900):
            yield line

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": LLM_PROVIDER,
        "rag_enabled": RAG_ENABLED,
        "rag_loaded": _bge_model is not None,
        "datasets": [
            {"label": label, "collection": coll} for label, _client, coll in _qdrant_clients
        ],
        "key_configured": bool(DEEPSEEK_API_KEY),
    }
