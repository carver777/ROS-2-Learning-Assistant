"""学习路线接口：预制路线 + LLM/RAG 自定义生成 + 章节流式讲解。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.llm import call_llm_json, llm_gen
from backend.prompts import MARKDOWN_FORMAT_RULES
from backend.rag import build_rag_context, chunks_to_sources, retrieve_context
from backend.schemas import RoadmapGenerateRequest, RoadmapSectionExplainRequest

router = APIRouter()


# ── 预制路线（覆盖大部分学习者诉求；调 /roadmap/generate 传 preset_id 即可使用）
PRESETS: dict[str, dict] = {
    "beginner": {
        "id": "beginner",
        "title": "ROS 2 入门必修",
        "summary": "从零理解节点、话题、服务、参数、launch 的全套基础概念，约 4-6 小时学完",
        "level": "beginner",
        "sections": [
            {
                "title": "理解 ROS 2 与节点（Node）",
                "objectives": [
                    "说清楚 ROS 2 解决的核心问题以及与 ROS 1 的关键差异",
                    "能用 `ros2 run` 启动一个节点并用 `ros2 node list/info` 观察",
                ],
                "key_concepts": ["ros2", "node", "ros2 run", "ros2 node", "rclpy", "rclcpp"],
                "estimated_minutes": 30,
            },
            {
                "title": "话题 Topic：发布与订阅",
                "objectives": [
                    "理解发布订阅模型与单向数据流的语义",
                    "能编写最小 publisher / subscriber 并互相通信",
                    "掌握 `ros2 topic echo/hz/info` 调试三件套",
                ],
                "key_concepts": ["topic", "publisher", "subscriber", "msg", "ros2 topic"],
                "estimated_minutes": 45,
            },
            {
                "title": "服务 Service：请求与应答",
                "objectives": [
                    "区分 topic 与 service 的适用场景",
                    "能定义 .srv 接口并实现服务端 / 客户端",
                ],
                "key_concepts": ["service", "client", "server", "srv", "ros2 service"],
                "estimated_minutes": 30,
            },
            {
                "title": "参数 Parameter 与节点配置",
                "objectives": [
                    "通过 declare_parameter / get_parameter 读取配置",
                    "能从命令行 / yaml / launch 三种方式注入参数",
                ],
                "key_concepts": ["parameter", "declare_parameter", "yaml", "ros2 param"],
                "estimated_minutes": 25,
            },
            {
                "title": "Launch 文件：批量启动与参数化",
                "objectives": [
                    "掌握 Python launch 文件的常用 Action（Node / IncludeLaunchDescription / DeclareLaunchArgument）",
                    "理解 substitution 的作用",
                ],
                "key_concepts": ["launch", "launch.py", "substitution", "DeclareLaunchArgument"],
                "estimated_minutes": 40,
            },
            {
                "title": "调试与可视化基础（rqt / rviz2 / bag）",
                "objectives": [
                    "用 rqt_graph 看节点拓扑，rqt_plot 绘曲线",
                    "能用 ros2 bag 录制 / 回放话题",
                ],
                "key_concepts": ["rqt", "rviz2", "ros2 bag", "rosbag2"],
                "estimated_minutes": 30,
            },
        ],
    },
    "intermediate": {
        "id": "intermediate",
        "title": "ROS 2 中级进阶",
        "summary": "深入 QoS、Lifecycle、组件化、Executor 与回调组等并发模型，约 6-8 小时",
        "level": "intermediate",
        "sections": [
            {
                "title": "QoS 策略与可靠性矩阵",
                "objectives": [
                    "理解 Reliability / Durability / History / Deadline 等核心 QoS 维度",
                    "能根据传感器类型选择合理 QoS Profile",
                ],
                "key_concepts": ["qos", "reliability", "durability", "history", "best_effort"],
                "estimated_minutes": 50,
            },
            {
                "title": "Action：长时任务与反馈",
                "objectives": [
                    "区分 Action 与 Service 的适用场景",
                    "能编写 ActionServer，处理 goal/feedback/result",
                ],
                "key_concepts": ["action", "goal", "feedback", "rclpy.action", "rclcpp_action"],
                "estimated_minutes": 45,
            },
            {
                "title": "Lifecycle 节点与状态机",
                "objectives": [
                    "理解 unconfigured / inactive / active / finalized 状态切换",
                    "能在 on_configure / on_activate 中正确管理资源",
                ],
                "key_concepts": ["lifecycle", "managed node", "on_configure", "on_activate"],
                "estimated_minutes": 50,
            },
            {
                "title": "Executor 与 Callback Group",
                "objectives": [
                    "理解单线程 / 多线程 executor 的差异与死锁风险",
                    "用 mutually_exclusive / reentrant callback group 控制并发",
                ],
                "key_concepts": [
                    "executor",
                    "callback group",
                    "MultiThreadedExecutor",
                    "reentrant",
                ],
                "estimated_minutes": 50,
            },
            {
                "title": "组件化（Composition）",
                "objectives": [
                    "把节点编译为 component 并在同进程内加载",
                    "理解进程内零拷贝通信带来的性能收益",
                ],
                "key_concepts": ["component", "composition", "rclcpp_components", "container"],
                "estimated_minutes": 40,
            },
            {
                "title": "DDS 与中间件调优",
                "objectives": [
                    "理解 RMW 抽象层与常见 DDS 实现的差别",
                    "用 ROS_DOMAIN_ID / discovery server 隔离网络",
                ],
                "key_concepts": ["dds", "rmw", "fastdds", "cyclonedds", "discovery", "domain id"],
                "estimated_minutes": 45,
            },
        ],
    },
    "navigation": {
        "id": "navigation",
        "title": "Nav2 移动机器人导航",
        "summary": "tf2 坐标系、传感器融合、SLAM、Nav2 行为树与代价地图实战",
        "level": "intermediate",
        "sections": [
            {
                "title": "tf2 坐标系与变换树",
                "objectives": [
                    "理解 frame、parent、broadcaster、listener 概念",
                    "用 static_transform_publisher 与 robot_state_publisher 搭起 base_link → odom → map",
                ],
                "key_concepts": ["tf2", "transform", "base_link", "odom", "map"],
                "estimated_minutes": 50,
            },
            {
                "title": "URDF / Xacro 机器人描述",
                "objectives": [
                    "用 link/joint 描述刚体结构",
                    "理解 xacro 宏的复用模式",
                ],
                "key_concepts": ["urdf", "xacro", "link", "joint", "robot_state_publisher"],
                "estimated_minutes": 40,
            },
            {
                "title": "传感器消息与同步（sensor_msgs）",
                "objectives": [
                    "区分 LaserScan / Imu / PointCloud2 / Image 等消息类型",
                    "用 message_filters 做时间近似同步",
                ],
                "key_concepts": ["sensor_msgs", "LaserScan", "Imu", "message_filters"],
                "estimated_minutes": 40,
            },
            {
                "title": "SLAM 与建图（slam_toolbox）",
                "objectives": [
                    "在仿真里跑通 slam_toolbox 在线建图",
                    "理解 odom 漂移与回环检测的关系",
                ],
                "key_concepts": ["slam", "slam_toolbox", "mapping", "odometry"],
                "estimated_minutes": 60,
            },
            {
                "title": "Nav2：行为树与规划器",
                "objectives": [
                    "理解 Nav2 的 behavior tree / planner / controller / recovery 四件套",
                    "能改写 BT XML 自定义行为",
                ],
                "key_concepts": ["nav2", "behavior tree", "planner", "controller", "bt_navigator"],
                "estimated_minutes": 70,
            },
            {
                "title": "Costmap 与避障",
                "objectives": [
                    "区分 global_costmap 与 local_costmap 的层结构",
                    "调 inflation_layer / obstacle_layer 解决卡墙问题",
                ],
                "key_concepts": ["costmap", "inflation_layer", "obstacle_layer", "voxel"],
                "estimated_minutes": 45,
            },
        ],
    },
    "manipulation": {
        "id": "manipulation",
        "title": "MoveIt 2 机械臂操控",
        "summary": "机械臂建模、运动规划、轨迹执行与抓取的端到端入门",
        "level": "advanced",
        "sections": [
            {
                "title": "机械臂 URDF 与 SRDF",
                "objectives": [
                    "区分 URDF（描述结构）与 SRDF（描述规划组）",
                    "用 MoveIt Setup Assistant 生成配置包",
                ],
                "key_concepts": ["moveit", "urdf", "srdf", "setup assistant", "planning group"],
                "estimated_minutes": 50,
            },
            {
                "title": "运动规划：OMPL 与 Pilz",
                "objectives": [
                    "理解采样规划（OMPL）与工业插补（Pilz）的差异",
                    "能为不同任务挑合适规划器",
                ],
                "key_concepts": ["ompl", "pilz", "motion planning", "rrt"],
                "estimated_minutes": 45,
            },
            {
                "title": "MoveGroupInterface 编程",
                "objectives": [
                    "用 C++/Python API 设置目标位姿并调 plan/execute",
                    "处理规划失败与碰撞冲突",
                ],
                "key_concepts": ["MoveGroupInterface", "plan", "execute", "pose goal"],
                "estimated_minutes": 50,
            },
            {
                "title": "PlanningScene 与碰撞检测",
                "objectives": [
                    "向场景动态添加 / 移除碰撞物体",
                    "理解 ACM（允许碰撞矩阵）的语义",
                ],
                "key_concepts": ["planning scene", "collision", "ACM", "octomap"],
                "estimated_minutes": 40,
            },
            {
                "title": "抓取与 Gripper 控制",
                "objectives": [
                    "用 GraspGenerator / Pick-Place 接口完成简单抓取",
                    "对接真实 / 仿真 gripper 控制器",
                ],
                "key_concepts": ["grasp", "pick", "place", "gripper", "controller"],
                "estimated_minutes": 50,
            },
        ],
    },
}


# ── Prompt：自定义路线生成（出 JSON） ─────────────────────────────────────────
SYSTEM_PROMPT_ROADMAP_GENERATOR = """你是 ROS 2 课程总设计师，根据【知识库素材】和学习者诉求，
设计一条**结构化学习路线**。

请**严格输出 JSON**，不要任何额外文字、不要 Markdown 代码块。

JSON Schema：
{
  "title":   "路线标题（中文，10-20 字，体现目标）",
  "summary": "一段话概括路线（30-60 字）",
  "level":   "beginner / intermediate / advanced 之一",
  "sections": [
    {
      "title":             "章节标题（5-15 字）",
      "objectives":        ["学习目标1", "学习目标2"],
      "key_concepts":      ["concept1", "concept2"],
      "estimated_minutes": 30
    }
  ]
}

要求：
1. 章节数 4-7 个，循序渐进，相邻章节有清晰依赖
2. 每节 2-4 条 objective，动词开头（"理解 / 能 / 掌握"），可衡量
3. key_concepts 是英文/拼写正确的关键词（用于后续 RAG 检索 + 出题）
4. **必须基于【知识库素材】中的真实概念**，不要凭空捏造 ROS 2 不存在的术语
5. estimated_minutes ∈ [15, 90]
6. 只输出 JSON，无任何前后缀"""


SYSTEM_PROMPT_ROADMAP_SECTION = (
    """你是 ROS 2 资深讲师，给学生讲解学习路线中的某个章节。
请用中文 Markdown 输出，结构如下：

## 本节学习目标
（罗列对应 objective，逐条解释为什么要学）

## 核心概念
（对每个 key_concept 给一段精炼解释，必要时配最小代码片段）

## 实战建议
（1-3 条立即可做的练习或命令）

## 常见坑 / 注意事项
（1-2 条新手最容易踩的坑）

要求：
- 严格基于【参考文档】，不要编造
- 涉及对比时使用 Markdown 表格
- 引用文档来源用 [n] 标注
"""
    + MARKDOWN_FORMAT_RULES
)


def _preset_overview(p: dict) -> dict:
    """把预制路线缩成列表项（不含 sections 详情）。"""
    return {
        "id": p["id"],
        "title": p["title"],
        "summary": p["summary"],
        "level": p["level"],
        "section_count": len(p["sections"]),
    }


@router.get("/roadmap/presets")
async def list_presets():
    """列出所有预制学习路线。"""
    return {"presets": [_preset_overview(p) for p in PRESETS.values()]}


@router.post("/roadmap/generate")
async def generate_roadmap(req: RoadmapGenerateRequest):
    """生成路线：preset 直接返回 + RAG 补充来源；自定义则 LLM+RAG 现场生成。"""
    if req.preset_id:
        preset = PRESETS.get(req.preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail=f"未知 preset_id: {req.preset_id}")

        # 给预制路线附上 RAG 来源（用 title + 头两节关键词检索）
        first_concepts = " ".join(preset["sections"][0]["key_concepts"][:3])
        chunks = await retrieve_context(f"ROS 2 {preset['title']} {first_concepts}")
        return {**preset, "sources": chunks_to_sources(chunks), "is_preset": True}

    if not req.goal or not req.goal.strip():
        raise HTTPException(status_code=400, detail="自定义生成必须提供 goal")

    # 用 goal+focus 拉知识库素材，让 LLM 基于真实文档出路线
    query = f"ROS 2 {req.goal.strip()} {req.focus or ''} {req.level}"
    chunks = await retrieve_context(query)
    if not chunks:
        raise HTTPException(
            status_code=503,
            detail="知识库未返回内容，无法基于知识库生成路线。请检查 RAG 是否启用。",
        )

    user_prompt = (
        f"学习者目标：{req.goal.strip()}\n"
        f"当前水平：{req.level}\n"
        f"{f'重点方向：{req.focus.strip()}' if req.focus else ''}\n\n"
        f"【知识库素材】（请只基于以下内容生成路线，不要凭空捏造概念）：\n"
        f"{build_rag_context(chunks)}\n\n"
        f"请按 JSON Schema 输出学习路线。"
    )

    roadmap = await call_llm_json(SYSTEM_PROMPT_ROADMAP_GENERATOR, user_prompt, max_tokens=1800)

    # 校验 + 容错
    sections = roadmap.get("sections")
    if not isinstance(sections, list) or not sections:
        raise HTTPException(status_code=502, detail=f"路线生成 Agent 返回结构非法：{roadmap}")
    for s in sections:
        s.setdefault("objectives", [])
        s.setdefault("key_concepts", [])
        s.setdefault("estimated_minutes", 30)

    return {
        "id": "custom",
        "title": roadmap.get("title", req.goal.strip()),
        "summary": roadmap.get("summary", ""),
        "level": roadmap.get("level", req.level),
        "sections": sections,
        "sources": chunks_to_sources(chunks),
        "is_preset": False,
    }


@router.post("/roadmap/section/explain")
async def explain_section(req: RoadmapSectionExplainRequest):
    """对路线中某一节流式讲解。"""
    if not req.section_title.strip():
        raise HTTPException(status_code=400, detail="section_title 不能为空")

    # 用章节标题 + 关键词做检索
    query = f"ROS 2 {req.section_title} " + " ".join(req.key_concepts[:5])
    chunks = await retrieve_context(query)
    ctx_block = build_rag_context(chunks) if chunks else ""

    parts = [
        f"路线：{req.roadmap_title}",
        f"章节：{req.section_title}",
        "学习目标：\n" + "\n".join(f"- {o}" for o in req.objectives),
        "核心概念：" + "、".join(req.key_concepts),
    ]
    if ctx_block:
        parts.append(f"\n【参考文档】\n{ctx_block}")
    user_prompt = "\n\n".join(parts) + "\n\n请按系统提示的结构详细讲解本节内容。"

    meta = {"meta": {"used_rag": bool(chunks), "sources": chunks_to_sources(chunks)}}
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT_ROADMAP_SECTION},
        {"role": "user", "content": user_prompt},
    ]

    async def gen():
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        async for line in llm_gen(msgs, max_tokens=1100):
            yield line

    return StreamingResponse(gen(), media_type="text/event-stream")
