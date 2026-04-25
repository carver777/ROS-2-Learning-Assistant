export type Ros2NodeType =
  | 'publisher'
  | 'subscriber'
  | 'service_server'
  | 'service_client'
  | 'action_server'
  | 'action_client'
  | 'lifecycle'

export type Ros2EdgeType = 'topic' | 'service' | 'action'

export interface Ros2QoS {
  reliability?: 'reliable' | 'best_effort'
  durability?: 'volatile' | 'transient_local'
  history?: 'keep_last' | 'keep_all'
  depth?: number
}

export interface Ros2NodeData {
  label: string
  nodeType: Ros2NodeType
  package?: string
  description?: string
  qos?: Ros2QoS
  [key: string]: unknown
}

export interface Ros2EdgeData {
  topicName: string
  edgeType: Ros2EdgeType
  msgType?: string
  hz?: number
  isAnimating?: boolean
  [key: string]: unknown
}

export interface Ros2NodeDef {
  id: string
  position: { x: number; y: number }
  data: Ros2NodeData
}

export interface Ros2EdgeDef {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  data: Ros2EdgeData
}

export interface Ros2Scenario {
  id: string
  name: string
  description: string
  icon: string
  nodes: Ros2NodeDef[]
  edges: Ros2EdgeDef[]
}
