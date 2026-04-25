# ROS 2 Learning Assistant

面向 ROS 2 学习者的全功能 AI 助手：把官方文档变成可查、可问、可练、可走的「学习闭环」。

后端基于 **FastAPI + DeepSeek/Ollama + 本地 RAG（BGE-M3 混合检索 + reranker + Qdrant）**，前端基于 **React 18 + TypeScript + Vite + ReactFlow**。

## 功能总览

| 模块 | 入口 | 说明 |
|---|---|---|
| 经典场景模拟 | 侧栏 `🗺️` | 三个真实 ROS 2 场景（TurtleBot 导航 / 相机流水线 / 机械臂控制）的拓扑图，点击节点/连线让 AI 现场讲解 |
| 学习路线 | 侧栏 `🧭` | 4 条预制路线（入门 / 进阶 / Nav2 / MoveIt），或基于知识库 LLM 现场为你定制；每节可展开 AI 流式讲解，可一键跳转出题 |
| AI 助手 | 侧栏 `💬` | 带 RAG 的多轮对话，自动识别 ROS 2 提问触发文档检索；支持「智能 / 强制 / 关闭」三种检索模式 |
| 知识测验 | 侧栏 `📝` | 三个 Agent 串联：出题人（基于知识库出题）→ 判题人（评分 + 反馈）→ 讲题人（流式详细解析） |

所有 LLM 输出均**带文档来源引用**，可点击跳转到 ROS 2 官方文档原文。

## 技术栈

- **前端**：React 18 / TypeScript 5 / Vite 5 / `@xyflow/react` / `react-markdown` + `remark-gfm`
- **后端**：Python 3.12 / FastAPI / httpx（SSE 流式代理）/ Pydantic 2
- **LLM**：DeepSeek（`deepseek-chat`，支持 `response_format=json_object`）或 Ollama（任意本地模型，如 `qwen2.5:7b`）
- **RAG**：
  - 向量库：[Qdrant](https://qdrant.tech)（本地嵌入式模式，多数据集并查 + url 去重）
  - 向量化：[BGE-M3](https://huggingface.co/BAAI/bge-m3)（dense + sparse 混合）
  - 重排：[BAAI bge-reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- **包管理**：后端 [`uv`](https://github.com/astral-sh/uv)，前端 `pnpm`
- **代码质量**：[`ruff`](https://docs.astral.sh/ruff/)（lint + format）+ [`gitleaks`](https://github.com/gitleaks/gitleaks)（密钥扫描），统一由 `pre-commit` 钩子驱动

## 项目结构

```
.
├── backend/                # FastAPI 应用（已模块化拆分）
│   ├── main.py             # 应用装配器（CORS + router 挂载）
│   ├── config.py           # 环境变量与常量
│   ├── state.py            # RAG 资源全局注入点（启动时被 run_backend.py 填充）
│   ├── prompts.py          # 通用 system prompts
│   ├── schemas.py          # Pydantic 请求模型
│   ├── llm.py              # DeepSeek / Ollama 调用（流式 SSE + JSON 模式）
│   ├── rag.py              # 混合检索 + 上下文拼装 + 意图识别
│   ├── routers/
│   │   ├── explain.py      # /explain/node, /explain/edge
│   │   ├── chat.py         # /chat（自动决定是否走 RAG）
│   │   ├── quiz.py         # /quiz/generate, /quiz/grade, /quiz/explain
│   │   ├── roadmap.py      # /roadmap/presets, /roadmap/generate, /roadmap/section/explain
│   │   └── health.py       # /health
│   └── .env.example
│
├── frontend/               # React + Vite SPA
│   ├── App.tsx             # 主布局：侧栏导航 + 4 大主视图
│   ├── App.css
│   ├── components/         # ChatPanel / QuizPanel / RoadmapPanel / DetailPanel / Markdown / ...
│   ├── hooks/              # useChat / useQuiz / useRoadmap / useAiExplain
│   ├── types/              # ros2.ts / roadmap.ts
│   └── data/scenarios.ts   # 三个场景的拓扑数据
│
├── scripts/                # RAG 数据流水线
│   ├── crawl_ros2_kilted.py     # 抓取 docs.ros.org（kilted 分支）
│   ├── crawl_ros2_tutorial.py   # 抓取 ros2-tutorial
│   ├── clean_rag_database.py    # 清洗 / 去重 / 切块
│   ├── build_vector_index.py    # BGE-M3 编码 → Qdrant 入库
│   ├── query_rag.py             # CLI 检索调试工具
│   └── rag_common.py            # 公共：模型加载 / 混合搜索
│
├── database/               # 由 scripts 重建（已 .gitignore，不入库）
├── run_backend.py          # 启动入口：先加载 RAG 模型再注入 FastAPI
├── pyproject.toml          # 后端依赖 + uv 索引 + ruff 配置
├── package.json            # 前端依赖
├── .pre-commit-config.yaml
├── .gitattributes          # 行尾归一 / 二进制标记 / lock 文件 -diff
└── .gitignore
```

## 快速启动

### 1. 准备环境

需要：**Python ≥ 3.12**、**Node.js ≥ 18**、`uv`、`pnpm`、（可选）NVIDIA GPU + CUDA 12.8 用于加速 RAG。

```bash
# 安装 uv（如已有可跳过）
pip install uv
# 或：curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 后端依赖与配置

```bash
uv sync                           # 安装 backend + RAG 全部依赖到 .venv
cp backend/.env.example backend/.env
# 编辑 backend/.env：填入 DEEPSEEK_API_KEY（或切到 LLM_PROVIDER=ollama）
```

> 申请 DeepSeek key：<https://platform.deepseek.com/api_keys>

### 3. 构建 RAG 知识库（首次）

```bash
# 抓取官方文档（任选一个或全部；产物落到 database/<name>-raw/）
uv run python scripts/crawl_ros2_kilted.py
uv run python scripts/crawl_ros2_tutorial.py

# 清洗 + 切块
uv run python scripts/clean_rag_database.py

# BGE-M3 编码 + 入 Qdrant（每个数据集分别跑一次）
uv run python scripts/build_vector_index.py \
    --input  database/ros2-kilted-clean/chunks.jsonl \
    --output database/ros2-kilted-clean/qdrant_store \
    --collection ros2_kilted_chunks
```

`backend/.env` 中通过 `QDRANT_DATASETS=path1:coll1,path2:coll2` 指定多数据集并查。

### 4. 启动后端

```bash
uv run python run_backend.py                 # 默认 0.0.0.0:8000，加载 RAG
uv run python run_backend.py --no-rag        # 跳过 RAG（仅 LLM 模式）
uv run python run_backend.py --reload        # 开发热重载（自动 --no-rag）
```

启动期会先加载 BGE-M3 + reranker，CUDA 模式下还会做一次 GPU 预热。完成后 API 文档在 <http://localhost:8000/docs>。

### 5. 启动前端

```bash
pnpm install
pnpm dev                   # http://localhost:5173
```

## 关键 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET`  | `/health` | LLM provider / RAG 状态 / API key 是否配置 |
| `POST` | `/explain/node` | 流式解释一个 ROS 2 节点 |
| `POST` | `/explain/edge` | 流式解释一条 topic / service / action 连线 |
| `POST` | `/chat` | 多轮对话；`use_rag: auto/on/off` 控制是否检索 |
| `POST` | `/quiz/generate` | 出一道 mcq / short 题（基于 RAG） |
| `POST` | `/quiz/grade` | 评分 + 反馈 |
| `POST` | `/quiz/explain` | 流式详细讲解 |
| `GET`  | `/roadmap/presets` | 列出预制学习路线 |
| `POST` | `/roadmap/generate` | 取预制 / 自定义生成（LLM + RAG） |
| `POST` | `/roadmap/section/explain` | 流式讲解路线中的某节 |

所有流式接口走 SSE：`data: {...}\n\n`，约定字段为 `meta`（首帧附带 `used_rag` 与 `sources`）和 `content`（增量文本）。

## 环境变量

见 [`backend/.env.example`](backend/.env.example)，关键项：

- `LLM_PROVIDER`：`deepseek` | `ollama`
- `DEEPSEEK_API_KEY`：DeepSeek key（provider 为 deepseek 时必填）
- `OLLAMA_BASE_URL` / `OLLAMA_MODEL`：本地 Ollama 配置
- `RAG_ENABLED`：`true` / `false`（关闭后所有接口降级为纯 LLM）
- `QDRANT_DATASETS`：多数据集 `path:collection` 列表
- `RAG_TOP_K` / `RAG_RERANK_POOL`：检索召回与重排候选数量
- `RAG_DEVICE`：`cuda:0` / `cpu`

## 开发约定

```bash
pre-commit install                 # 启用钩子（一次性）
pre-commit run --all-files         # 全量自检
pnpm lint                          # 前端 tsc --noEmit
```

钩子链路：行尾/换行符归一 → yaml/toml/json 校验 → ruff lint+format → gitleaks 扫密钥。

`.gitattributes` 已统一行尾：仓库内文本一律 LF，仅 `*.bat/*.cmd/*.ps1` 强制 CRLF；`package-lock.json` / `uv.lock` 标记为 `linguist-generated` 并禁用 diff，减少噪音。
