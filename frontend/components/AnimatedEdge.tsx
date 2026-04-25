import { memo } from 'react'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'
import type { Ros2EdgeData, Ros2EdgeType } from '../types/ros2'

const EDGE_STYLE: Record<Ros2EdgeType, { color: string; dash?: string }> = {
  topic: { color: '#1D9E75' },
  service: { color: '#7F77DD', dash: '5 3' },
  action: { color: '#BA7517', dash: '8 3 2 3' },
}

function AnimatedEdgeImpl({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected,
}: EdgeProps) {
  const edgeData = data as Ros2EdgeData | undefined
  const edgeType: Ros2EdgeType = edgeData?.edgeType ?? 'topic'
  const style = EDGE_STYLE[edgeType]
  const isAnimating = !!edgeData?.isAnimating

  const [path, labelX, labelY] = getBezierPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  })

  const strokeWidth = selected ? 3 : 2

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={`url(#arrow-${edgeType})`}
        style={{
          stroke: style.color,
          strokeWidth,
          strokeDasharray: style.dash,
          filter: selected ? `drop-shadow(0 0 4px ${style.color}80)` : undefined,
          opacity: isAnimating ? 0.4 : 1,
          transition: 'opacity .2s',
        }}
      />
      {isAnimating && (
        <>
          <circle r="4" fill={style.color}>
            <animateMotion dur="1.4s" repeatCount="indefinite" path={path} rotate="auto" />
          </circle>
          <circle r="4" fill={style.color} opacity="0.6">
            <animateMotion dur="1.4s" begin="0.35s" repeatCount="indefinite" path={path} rotate="auto" />
          </circle>
          <circle r="4" fill={style.color} opacity="0.3">
            <animateMotion dur="1.4s" begin="0.7s" repeatCount="indefinite" path={path} rotate="auto" />
          </circle>
        </>
      )}
      {edgeData?.topicName && (
        <EdgeLabelRenderer>
          <div
            className="edge-label"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              borderColor: style.color,
              color: style.color,
            }}
          >
            {edgeData.topicName}
            {edgeData.hz ? <span className="edge-hz">{edgeData.hz} Hz</span> : null}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export const AnimatedEdge = memo(AnimatedEdgeImpl)
