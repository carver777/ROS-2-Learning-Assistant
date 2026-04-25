import { useState, useCallback, useEffect } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  addEdge, useNodesState, useEdgesState, BackgroundVariant,
} from '@xyflow/react'
import type { Connection, Node, Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { Ros2Node } from './components/Ros2Node'
import { AnimatedEdge } from './components/AnimatedEdge'
import { DetailPanel } from './components/DetailPanel'
import { ChatPanel } from './components/ChatPanel'
import { QuizPanel } from './components/QuizPanel'
import { scenarios } from './data/scenarios'
import type { Ros2NodeData, Ros2EdgeData } from './types/ros2'
import { useAiExplain } from './hooks/useAiExplain'
import { useChat } from './hooks/useChat'
import { useQuiz } from './hooks/useQuiz'
import './App.css'

const nodeTypes = { ros2Node: Ros2Node }
const edgeTypes = { animatedEdge: AnimatedEdge }

type SelectedItem =
  | { type: 'node'; data: Ros2NodeData; id: string }
  | { type: 'edge'; data: Ros2EdgeData; id: string }
  | null

export default function App() {
  const [activeScenario, setActiveScenario] = useState(scenarios[0])
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<SelectedItem>(null)
  const [mainView, setMainView] = useState<'graph' | 'chat' | 'quiz'>('graph')
  const { explanation, sources, usedRag, isLoading, error, explainNode, explainEdge } = useAiExplain()
  const chat = useChat()
  const quiz = useQuiz()

  useEffect(() => {
    setNodes(activeScenario.nodes.map(n => ({ ...n, type: 'ros2Node' })))
    setEdges(activeScenario.edges.map(e => ({ ...e, type: 'animatedEdge' })))
    setSelected(null)
  }, [activeScenario, setNodes, setEdges])

  const onConnect = useCallback(
    (params: Connection) =>
      setEdges(eds => addEdge({ ...params, type: 'animatedEdge', data: { topicName: '/new_topic', edgeType: 'topic' } }, eds)),
    [setEdges]
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelected({ type: 'node', data: node.data as Ros2NodeData, id: node.id })
  }, [])

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelected({ type: 'edge', data: edge.data as Ros2EdgeData, id: edge.id })
  }, [])

  const onPaneClick = useCallback(() => setSelected(null), [])

  const handleSimulate = useCallback((nodeId: string) => {
    setEdges(eds => eds.map(e => e.source === nodeId ? { ...e, data: { ...e.data, isAnimating: true } } : e))
    setTimeout(() => setEdges(eds => eds.map(e => e.source === nodeId ? { ...e, data: { ...e.data, isAnimating: false } } : e)), 3000)
  }, [setEdges])

  const handleAiExplain = useCallback(() => {
    if (!selected) return
    if (selected.type === 'node') explainNode(selected.data)
    else explainEdge(selected.data)
  }, [selected, explainNode, explainEdge])

  const navItems: { id: typeof mainView; label: string; icon: string; busy?: boolean }[] = [
    { id: 'graph', label: '可视化', icon: '🗺️' },
    { id: 'chat',  label: 'AI 助手', icon: '💬', busy: chat.isLoading },
    { id: 'quiz',  label: '知识测验', icon: '📝',
      busy: quiz.phase === 'generating' || quiz.phase === 'grading' || quiz.phase === 'explaining' },
  ]

  return (
    <div className={`app-layout view-${mainView}`}>
      <svg width="0" height="0" style={{ position: 'absolute' }}>
        <defs>
          {(['topic', 'service', 'action'] as const).map(t => (
            <marker key={t} id={`arrow-${t}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M2 1L8 5L2 9" fill="none"
                stroke={t === 'topic' ? '#1D9E75' : t === 'service' ? '#7F77DD' : '#BA7517'}
                strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </marker>
          ))}
        </defs>
      </svg>

      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo-mark">ROS2</div>
          <div className="logo-sub">Visual Explorer</div>
        </div>

        {/* —— 主视图导航 —— */}
        <nav className="nav-section">
          <div className="section-label">功能</div>
          <div className="nav-list">
            {navItems.map(it => (
              <button
                key={it.id}
                className={`nav-btn ${mainView === it.id ? 'active' : ''}`}
                onClick={() => setMainView(it.id)}
              >
                <span className="nav-icon">{it.icon}</span>
                <span className="nav-label">{it.label}</span>
                {it.busy && <span className="right-tab-dot" />}
              </button>
            ))}
          </div>
        </nav>

        {/* 仅可视化视图下展示场景与图例 */}
        {mainView === 'graph' && (
          <>
            <div className="scenario-section">
              <div className="section-label">场景</div>
              {scenarios.map(s => (
                <button key={s.id} className={`scenario-btn ${activeScenario.id === s.id ? 'active' : ''}`} onClick={() => setActiveScenario(s)}>
                  <span className="scenario-icon">{s.icon}</span>
                  <div>
                    <div className="scenario-name">{s.name}</div>
                    <div className="scenario-desc">{s.description}</div>
                  </div>
                </button>
              ))}
            </div>
            <div className="legend-section">
              <div className="section-label">节点类型</div>
              {[
                { label: 'Publisher', color: '#1D9E75', bg: '#E1F5EE' },
                { label: 'Subscriber', color: '#378ADD', bg: '#E6F1FB' },
                { label: 'Service', color: '#7F77DD', bg: '#EEEDFE' },
                { label: 'Action', color: '#BA7517', bg: '#FAEEDA' },
              ].map(item => (
                <div key={item.label} className="legend-item">
                  <span className="legend-dot" style={{ background: item.bg, border: `1.5px solid ${item.color}` }} />
                  <span className="legend-text">{item.label}</span>
                </div>
              ))}
              <div style={{ marginTop: 10 }}>
                <div className="section-label" style={{ marginBottom: 6 }}>连线类型</div>
                {[
                  { label: 'Topic', color: '#1D9E75', dash: undefined },
                  { label: 'Service', color: '#7F77DD', dash: '5 3' },
                  { label: 'Action', color: '#BA7517', dash: '8 3 2 3' },
                ].map(item => (
                  <div key={item.label} className="legend-item">
                    <svg width="28" height="10" style={{ flexShrink: 0 }}>
                      <line x1="0" y1="5" x2="28" y2="5" stroke={item.color} strokeWidth="2" strokeDasharray={item.dash} />
                    </svg>
                    <span className="legend-text">{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </aside>

      {/* —— 主内容区 —— */}
      {mainView === 'graph' && (
        <>
          <main className="canvas-area">
            <ReactFlow
              nodes={nodes} edges={edges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick} onPaneClick={onPaneClick}
              nodeTypes={nodeTypes} edgeTypes={edgeTypes}
              fitView fitViewOptions={{ padding: 0.3 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#d1d0c8" />
              <Controls style={{ bottom: 24, left: 24 }} />
              <MiniMap
                nodeColor={(n) => {
                  const d = n.data as Ros2NodeData
                  const m: Record<string, string> = { publisher: '#5DCAA5', subscriber: '#85B7EB', service_server: '#AFA9EC', service_client: '#AFA9EC', action_server: '#EF9F27', action_client: '#EF9F27', lifecycle: '#F0997B' }
                  return m[d?.nodeType] || '#ccc'
                }}
                style={{ bottom: 24, right: 16 }}
              />
            </ReactFlow>
          </main>

          <aside className="detail-panel">
            <div className="right-tab-body">
              <DetailPanel
                selected={selected}
                onSimulate={handleSimulate}
                text={explanation}
                loading={isLoading}
                error={error}
                sources={sources}
                usedRag={usedRag}
                onAiExplain={handleAiExplain}
              />
            </div>
          </aside>
        </>
      )}

      {mainView === 'chat' && (
        <main className="full-view">
          <ChatPanel chat={chat} />
        </main>
      )}

      {mainView === 'quiz' && (
        <main className="full-view">
          <QuizPanel quiz={quiz} />
        </main>
      )}
    </div>
  )
}
