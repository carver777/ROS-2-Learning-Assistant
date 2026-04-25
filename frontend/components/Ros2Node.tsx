import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { Ros2NodeData, Ros2NodeType } from '../types/ros2'

const STYLE_MAP: Record<Ros2NodeType, { bg: string; border: string; label: string; tag: string }> = {
  publisher: { bg: '#E1F5EE', border: '#1D9E75', label: '#085041', tag: 'Publisher' },
  subscriber: { bg: '#E6F1FB', border: '#378ADD', label: '#0C447C', tag: 'Subscriber' },
  service_server: { bg: '#EEEDFE', border: '#7F77DD', label: '#3C3489', tag: 'Service Server' },
  service_client: { bg: '#EEEDFE', border: '#AFA9EC', label: '#3C3489', tag: 'Service Client' },
  action_server: { bg: '#FAEEDA', border: '#BA7517', label: '#633806', tag: 'Action Server' },
  action_client: { bg: '#FAEEDA', border: '#EF9F27', label: '#633806', tag: 'Action Client' },
  lifecycle: { bg: '#FAECE7', border: '#993C1D', label: '#712B13', tag: 'Lifecycle' },
}

function Ros2NodeImpl({ data, selected }: NodeProps) {
  const nodeData = data as Ros2NodeData
  const style = STYLE_MAP[nodeData.nodeType] || STYLE_MAP.publisher

  return (
    <div
      className="ros2-node"
      style={{
        background: style.bg,
        border: `1.5px solid ${style.border}`,
        boxShadow: selected ? `0 0 0 3px ${style.border}40, 0 4px 12px rgba(0,0,0,.08)` : '0 1px 3px rgba(0,0,0,.06)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: style.border, width: 8, height: 8, border: 'none' }} />
      <div className="ros2-node-tag" style={{ color: style.border }}>{style.tag}</div>
      <div className="ros2-node-label" style={{ color: style.label }}>{nodeData.label}</div>
      {nodeData.package && (
        <div className="ros2-node-pkg">{nodeData.package}</div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: style.border, width: 8, height: 8, border: 'none' }} />
    </div>
  )
}

export const Ros2Node = memo(Ros2NodeImpl)
