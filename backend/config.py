"""集中式配置加载：从 .env / 环境变量读取，并暴露常量与数据集解析。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT: Path = Path(__file__).resolve().parent.parent
SCRIPTS_DIR: Path = ROOT / "scripts"

load_dotenv(ROOT / "backend" / ".env", override=True)

# ── LLM ──────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com") + "/v1"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "deepseek")  # deepseek | ollama
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# ── RAG ──────────────────────────────────────────────────────────────────────
RAG_ENABLED: bool = os.getenv("RAG_ENABLED", "true").lower() == "true"
QDRANT_PATH: Path = ROOT / os.getenv("QDRANT_PATH", "database/ros2-kilted-clean/qdrant_store")
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "ros2_kilted_chunks")
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "3"))
RAG_RERANK_POOL: int = int(os.getenv("RAG_RERANK_POOL", "15"))
RAG_DEVICE: str = os.getenv("RAG_DEVICE", "cpu")

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://localhost:4173",
    "http://localhost:3000",
]


def parse_datasets() -> list[tuple[str, str, str]]:
    """解析 ``QDRANT_DATASETS`` 配置。

    格式：``path1:collection1,path2:collection2``，路径相对项目根。
    返回 ``[(label, abs_path, collection_name), ...]``。
    未配置则退回单数据集（``QDRANT_PATH`` + ``QDRANT_COLLECTION``）。
    """
    raw = os.getenv("QDRANT_DATASETS", "").strip()
    if not raw:
        return [("default", str(QDRANT_PATH), QDRANT_COLLECTION)]
    out: list[tuple[str, str, str]] = []
    for i, part in enumerate(raw.split(",")):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"QDRANT_DATASETS 第 {i + 1} 项缺少冒号 (path:collection)：{part}")
        # Windows 路径里有 ':'（如 C:\xxx），所以从右侧切一刀
        path_part, _, coll = part.rpartition(":")
        abs_path = str(ROOT / path_part.strip())
        # 用 collection 名作 label，避免多库路径都以 qdrant_store 结尾时混淆
        label = coll.strip() or f"ds{i}"
        out.append((label, abs_path, coll.strip()))
    return out


RAG_DATASETS: list[tuple[str, str, str]] = parse_datasets()
