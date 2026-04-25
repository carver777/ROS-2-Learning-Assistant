"""FastAPI 应用装配器：仅做 app 创建、中间件、路由挂载。

业务逻辑分散在：
- ``backend.config``  : 环境变量与常量
- ``backend.state``   : RAG 资源全局注入点（由 ``run_backend.py`` 启动时填充）
- ``backend.prompts`` : 通用 system prompts
- ``backend.schemas`` : Pydantic 请求模型
- ``backend.llm``     : DeepSeek / Ollama 调用
- ``backend.rag``     : 混合检索 + 上下文拼装 + 意图识别
- ``backend.routers`` : explain / chat / quiz / health 路由
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import CORS_ORIGINS
from backend.routers import chat, explain, health, quiz


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="ROS2 Viz AI Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (explain, chat, quiz, health):
    app.include_router(module.router)
