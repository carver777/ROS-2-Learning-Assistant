# ROS 2 Visual Explorer

交互式 ROS 2 概念可视化学习平台，支持 DeepSeek AI 即时解释。

## 功能
- 3 个真实 ROS 2 场景（TurtleBot 导航 / 相机流水线 / 机械臂控制）
- 节点按类型区分颜色（Publisher / Subscriber / Service / Action）
- Topic / Service / Action 三种连线样式
- 点击节点/连线 → DeepSeek AI 流式解释
- 点击发布者节点 → 粒子动画模拟消息传递

## 快速启动

### 1. 后端（FastAPI + DeepSeek）
```bash
cd backend
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
# 申请地址：https://platform.deepseek.com/api_keys

pip install -r requirements.txt
uvicorn main:app --reload
# 后端运行在 http://localhost:8000
```

### 2. 前端（React + Vite）
```bash
npm install
npm run dev
# 前端运行在 http://localhost:5173
```

## 技术栈
- **前端**: React 18 + TypeScript + Vite + ReactFlow (@xyflow/react)
- **后端**: Python FastAPI + httpx（流式代理）
- **AI**: DeepSeek Chat API（SSE 流式输出）
- **部署**: Vercel（前端）+ Railway/Render（后端）

## 项目结构
```
├── src/
│   ├── types/ros2.ts          # TypeScript 类型定义
│   ├── data/scenarios.ts      # 3 个场景数据
│   ├── hooks/useAiExplain.ts  # DeepSeek 流式 hook
│   └── components/
│       ├── Ros2Node.tsx        # 自定义节点组件
│       ├── AnimatedEdge.tsx    # 动态连线组件
│       └── DetailPanel.tsx     # 右侧详情面板
└── backend/
    ├── main.py                 # FastAPI 服务
    ├── requirements.txt
    └── .env.example
```
