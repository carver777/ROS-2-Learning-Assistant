import { useState, useCallback, useRef } from 'react'
import type { Ros2NodeData, Ros2EdgeData } from '../types/ros2'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export interface AiSource {
  title: string
  url: string
  breadcrumb: string
}

export interface UseAiExplainReturn {
  explanation: string
  sources: AiSource[]
  usedRag: boolean
  isLoading: boolean
  error: string | null
  explainNode: (data: Ros2NodeData) => void
  explainEdge: (data: Ros2EdgeData) => void
  clear: () => void
}

export function useAiExplain(): UseAiExplainReturn {
  const [explanation, setExplanation] = useState('')
  const [sources, setSources] = useState<AiSource[]>([])
  const [usedRag, setUsedRag] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const streamFromEndpoint = useCallback(async (endpoint: string, body: object) => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setExplanation('')
    setSources([])
    setUsedRag(false)
    setError(null)
    setIsLoading(true)
    try {
      const res = await fetch(`${BACKEND_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abortRef.current.signal,
      })
      if (!res.ok) throw new Error(`后端错误: ${res.status}`)
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error('无法读取响应流')
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6)
          if (data === '[DONE]') break
          try {
            const parsed = JSON.parse(data)
            if (parsed.error) { setError(parsed.error); return }
            if (parsed.meta) {
              setSources(parsed.meta.sources ?? [])
              setUsedRag(Boolean(parsed.meta.used_rag))
              continue
            }
            if (parsed.content) setExplanation(prev => prev + parsed.content)
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      setError((err as Error).message || '请求失败，请检查后端是否启动')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const explainNode = useCallback((data: Ros2NodeData) => {
    streamFromEndpoint('/explain/node', {
      node_label: data.label, node_type: data.nodeType,
      package: data.package, description: data.description, qos: data.qos,
    })
  }, [streamFromEndpoint])

  const explainEdge = useCallback((data: Ros2EdgeData) => {
    streamFromEndpoint('/explain/edge', {
      topic_name: data.topicName, edge_type: data.edgeType,
      msg_type: data.msgType, hz: data.hz,
    })
  }, [streamFromEndpoint])

  const clear = useCallback(() => {
    abortRef.current?.abort()
    setExplanation('')
    setSources([])
    setUsedRag(false)
    setError(null)
    setIsLoading(false)
  }, [])

  return { explanation, sources, usedRag, isLoading, error, explainNode, explainEdge, clear }
}
