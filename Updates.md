## 2026-04-24 (RAG 向量管线)

- 确定最终 RAG 组合：BGE-M3 (dense+sparse) + Qdrant local hybrid + RRF + bge-reranker-v2-m3 + DeepSeek/Ollama 双后端。
- 安装 GPU 版 torch (2.6.0+cu124)、FlagEmbedding 1.4、qdrant-client 1.17，解决 Windows CUDA DLL 顺序冲突（torch 须最先导入）。
- 新增 `scripts/rag_common.py`：共享模型加载、Qdrant 适配、hybrid search、DeepSeek/Ollama 双 LLM 流式接口。
- 新增 `scripts/build_vector_index.py`：BGE-M3 编码全量 16219 chunks，写入 `database/ros2-kilted-clean/qdrant_store`（RTX 4060 约 28 分钟，9.7 chunks/s）。
- 新增 `scripts/query_rag.py`：hybrid 检索 + reranker 精排 + 流式生成 CLI（支持 `--llm deepseek/ollama/none`，`--no-rerank` 等选项）。
- 全管线端到端验证通过：中文/英文提问均能命中高置信度文档（rerank≥0.96），DeepSeek 生成含引用编号。

## 2026-04-24

- 将根目录错误的 `.cursor` 配置文件迁移为标准路径 `./.cursor/mcp.json`。
- 配置 Apify MCP 服务地址为 `https://mcp.apify.com`（OAuth 推荐方式）。
- 新增 `scripts/crawl_ros2_kilted.py`，抓取 `https://docs.ros.org/en/kilted/` 并导出到 `docs/ros2-kilted/`（本次 `max-pages=120`，成功 110 页）。
- 将 `scripts/crawl_ros2_kilted.py` 升级为 RAG 友好导出：`documents.jsonl`、`chunks.jsonl`、`graph_edges.jsonl`、`crawl_records.jsonl`，默认输出目录改为 `database/ros2-kilted/`。
- 已重新爬取 Kilted 文档（`max-pages=200`）：成功文档 191、切片 3764、链接边 59373。
- 新增 `scripts/clean_rag_database.py`，对 `database/ros2-kilted/` 做二次清洗：HTML 实体还原、跨页模板（Sphinx 侧边栏/页脚）自动识别与剥离、碎片行重建段落、段落感知重切分、`title+breadcrumb` 注入 `embed_text`、图边过滤静态资源/无效目标。
- 清洗结果写入 `database/ros2-kilted-clean/`：文档 185（6 个索引页无正文被剔除）、切片 3716、链接边 35720、模板行 366；平均切片 1106 chars（目标 1000）。
- 升级 `scripts/crawl_ros2_kilted.py`：新增 `--limit-package-docs`、静态资源扩展名过滤、Apache 目录排序参数过滤、进度日志。
- 完整重爬 Kilted：1947 页成功（真正文档 ~280 + 各 ROS 包 `/p/<pkg>/` 落地页 ~1660，已排除 Doxygen class/file 子页）、12820 切片、105576 边。
- 二次清洗后 `database/ros2-kilted-clean/`：1760 篇文档、16219 切片、91220 边；平均切片 1257 chars；chunks.jsonl ~50MB。
