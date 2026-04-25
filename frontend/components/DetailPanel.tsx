import type { Ros2NodeData, Ros2EdgeData, Ros2NodeType } from '../types/ros2'
import type { AiSource } from '../hooks/useAiExplain'
import { Markdown } from './Markdown'

type SelectedItem =
  | { type: 'node'; data: Ros2NodeData; id: string }
  | { type: 'edge'; data: Ros2EdgeData; id: string }
  | null

interface DetailPanelProps {
  selected: SelectedItem
  onSimulate: (nodeId: string) => void
  onAiExplain: () => void
  text: string
  loading: boolean
  error: string | null
  sources?: AiSource[]
  usedRag?: boolean
}

const NODE_TYPE_LABEL: Record<Ros2NodeType, string> = {
  publisher: 'Publisher 发布者',
  subscriber: 'Subscriber 订阅者',
  service_server: 'Service Server',
  service_client: 'Service Client',
  action_server: 'Action Server',
  action_client: 'Action Client',
  lifecycle: 'Lifecycle Node',
}

export function DetailPanel({
  selected, onSimulate, onAiExplain, text, loading, error, sources, usedRag,
}: DetailPanelProps) {
  if (!selected) {
    return (
      <div className="detail-empty">
        <div className="detail-empty-icon">👈</div>
        <div className="detail-empty-title">选择画布上的节点或连线</div>
        <div className="detail-empty-sub">点击后可查看详情并获得 AI 讲解</div>
      </div>
    )
  }

  if (selected.type === 'node') {
    const d = selected.data
    const isPublisher = d.nodeType === 'publisher' || d.nodeType === 'action_client' || d.nodeType === 'service_client'
    return (
      <div className="detail-wrap">
        <div className="detail-header">
          <div className="detail-kind">{NODE_TYPE_LABEL[d.nodeType]}</div>
          <div className="detail-title">{d.label}</div>
          {d.package && <div className="detail-meta">📦 {d.package}</div>}
        </div>

        {d.description && (
          <div className="detail-section">
            <div className="detail-section-label">说明</div>
            <div className="detail-section-body">{d.description}</div>
          </div>
        )}

        {d.qos && (
          <div className="detail-section">
            <div className="detail-section-label">QoS 策略</div>
            <div className="detail-qos">
              {Object.entries(d.qos).map(([k, v]) => (
                <span key={k} className="qos-chip"><b>{k}</b>: {String(v)}</span>
              ))}
            </div>
          </div>
        )}

        <div className="detail-actions">
          {isPublisher && (
            <button className="btn btn-ghost" onClick={() => onSimulate(selected.id)}>
              ▶ 模拟发布消息
            </button>
          )}
          <button className="btn btn-primary" onClick={onAiExplain} disabled={loading}>
            {loading ? 'AI 正在思考…' : '✨ AI 解释'}
          </button>
        </div>

        <AiOutput text={text} loading={loading} error={error} sources={sources} usedRag={usedRag} />
      </div>
    )
  }

  const d = selected.data
  return (
    <div className="detail-wrap">
      <div className="detail-header">
        <div className="detail-kind">{d.edgeType === 'topic' ? 'Topic 话题' : d.edgeType === 'service' ? 'Service 服务' : 'Action 行为'}</div>
        <div className="detail-title">{d.topicName}</div>
      </div>

      <div className="detail-section">
        <div className="detail-section-label">基本信息</div>
        <div className="detail-qos">
          {d.msgType && <span className="qos-chip"><b>消息类型</b>: {d.msgType}</span>}
          {d.hz != null && <span className="qos-chip"><b>频率</b>: {d.hz} Hz</span>}
        </div>
      </div>

      <div className="detail-actions">
        <button className="btn btn-primary" onClick={onAiExplain} disabled={loading}>
          {loading ? 'AI 正在思考…' : '✨ AI 解释'}
        </button>
      </div>

      <AiOutput text={text} loading={loading} error={error} sources={sources} usedRag={usedRag} />
    </div>
  )
}

interface AiOutputProps {
  text: string
  loading: boolean
  error: string | null
  sources?: AiSource[]
  usedRag?: boolean
}

function AiOutput({ text, loading, error, sources, usedRag }: AiOutputProps) {
  if (error) return <div className="ai-error">⚠️ {error}</div>
  if (!text && !loading) return null
  return (
    <div className="ai-output">
      <div className="ai-output-label">
        AI 讲解
        {usedRag && sources && sources.length > 0 && (
          <span className="ai-rag-badge">📚 已检索 {sources.length} 篇文档</span>
        )}
      </div>
      <div className="ai-output-body">
        <Markdown text={text} streaming={loading} />
      </div>
      {sources && sources.length > 0 && (
        <div className="ai-sources">
          <div className="ai-sources-label">参考来源</div>
          {sources.map((s, i) => (
            <a
              key={s.url + i}
              className="ai-source-item"
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              title={s.breadcrumb || s.url}
            >
              <span className="ai-source-idx">[{i + 1}]</span>
              <span className="ai-source-title">{s.title || s.url}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
