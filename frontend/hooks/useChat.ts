import { useState, useCallback, useRef } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export type ChatRole = 'user' | 'assistant'
export type RagMode = 'auto' | 'on' | 'off'

export interface ChatSource {
  title: string
  url: string
  breadcrumb: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  /** 仅 assistant 消息：本轮 RAG 命中的文档片段 */
  sources?: ChatSource[]
  /** 仅 assistant 消息：是否实际使用了 RAG */
  usedRag?: boolean
  /** 仅 assistant 消息：是否还在流式生成中 */
  streaming?: boolean
  error?: string
}

export interface UseChatReturn {
  messages: ChatMessage[]
  isLoading: boolean
  ragMode: RagMode
  setRagMode: (m: RagMode) => void
  send: (text: string) => void
  stop: () => void
  reset: () => void
}

const newId = () => Math.random().toString(36).slice(2, 10)

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [ragMode, setRagMode] = useState<RagMode>('auto')
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(async (text: string) => {
    const userMsg: ChatMessage = { id: newId(), role: 'user', content: text }
    const asstId = newId()
    const asstMsg: ChatMessage = {
      id: asstId, role: 'assistant', content: '', streaming: true,
    }
    // 用最新 messages 拼请求体（避免 setState 异步带来的 stale 闭包）
    let history: ChatMessage[] = []
    setMessages(prev => {
      history = [...prev, userMsg]
      return [...prev, userMsg, asstMsg]
    })

    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setIsLoading(true)
    try {
      const res = await fetch(`${BACKEND_URL}/chat`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          messages: history.map(m => ({ role: m.role, content: m.content })),
          use_rag:  ragMode,
        }),
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
          if (data === '[DONE]') continue
          try {
            const parsed = JSON.parse(data)
            if (parsed.error) {
              setMessages(prev => prev.map(m => m.id === asstId
                ? { ...m, error: parsed.error, streaming: false } : m))
              continue
            }
            if (parsed.meta) {
              setMessages(prev => prev.map(m => m.id === asstId
                ? { ...m, sources: parsed.meta.sources, usedRag: parsed.meta.used_rag } : m))
              continue
            }
            if (parsed.content) {
              setMessages(prev => prev.map(m => m.id === asstId
                ? { ...m, content: m.content + parsed.content } : m))
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        setMessages(prev => prev.map(m => m.id === asstId
          ? { ...m, streaming: false } : m))
      } else {
        const msg = (err as Error).message || '请求失败'
        setMessages(prev => prev.map(m => m.id === asstId
          ? { ...m, error: msg, streaming: false } : m))
      }
    } finally {
      setMessages(prev => prev.map(m => m.id === asstId
        ? { ...m, streaming: false } : m))
      setIsLoading(false)
    }
  }, [ragMode])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setIsLoading(false)
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setIsLoading(false)
  }, [])

  return { messages, isLoading, ragMode, setRagMode, send, stop, reset }
}
