import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import type { ChatMessage, RagMode, UseChatReturn } from '../hooks/useChat'
import { Markdown } from './Markdown'

interface Props {
  chat: UseChatReturn
}

const RAG_MODE_LABEL: Record<RagMode, string> = {
  auto: '智能',
  on:   '强制 RAG',
  off:  '纯 LLM',
}

export function ChatPanel({ chat }: Props) {
  const { messages, isLoading, ragMode, setRagMode, send, stop, reset } = chat
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top:      scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  const submit = () => {
    const text = input.trim()
    if (!text || isLoading) return
    send(text)
    setInput('')
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="chat-wrap">
      <div className="chat-toolbar">
        <div className="chat-toolbar-left">
          <span className="chat-toolbar-label">检索模式</span>
          <div className="chat-mode-group">
            {(['auto', 'on', 'off'] as RagMode[]).map(m => (
              <button
                key={m}
                className={`chat-mode-btn ${ragMode === m ? 'active' : ''}`}
                onClick={() => setRagMode(m)}
                title={
                  m === 'auto' ? '根据问题内容自动判断是否检索文档'
                  : m === 'on' ? '总是检索 ROS 2 文档'
                  : '不检索，仅靠模型自身知识'
                }
              >
                {RAG_MODE_LABEL[m]}
              </button>
            ))}
          </div>
        </div>
        {messages.length > 0 && (
          <button className="chat-clear-btn" onClick={reset} title="清空对话">
            清空
          </button>
        )}
      </div>

      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">🤖</div>
            <div className="chat-empty-title">AI 助手</div>
            <div className="chat-empty-sub">
              问我任何 ROS 2 相关问题，我会基于官方文档回答
              <br />
              其它话题也欢迎聊
            </div>
            <div className="chat-suggest-list">
              {[
                '什么是 ROS 2 的 QoS？',
                'topic 和 service 有什么区别？',
                '如何在 launch 文件里启动多个节点？',
              ].map(q => (
                <button key={q} className="chat-suggest-btn" onClick={() => send(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(m => <Bubble key={m.id} msg={m} />)}
      </div>

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          placeholder="发消息…  (Enter 发送 / Shift+Enter 换行)"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKey}
          rows={2}
          disabled={isLoading}
        />
        {isLoading
          ? <button className="btn btn-ghost chat-send-btn" onClick={stop}>停止</button>
          : <button
              className="btn btn-primary chat-send-btn"
              onClick={submit}
              disabled={!input.trim()}
            >发送</button>
        }
      </div>
    </div>
  )
}

function Bubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div className="chat-bubble user">
        <div className="chat-bubble-body">{msg.content}</div>
      </div>
    )
  }
  return (
    <div className="chat-bubble assistant">
      {msg.usedRag && (
        <div className="chat-rag-badge">📚 已检索 {msg.sources?.length ?? 0} 篇文档</div>
      )}
      <div className="chat-bubble-body">
        <Markdown text={msg.content} streaming={msg.streaming} />
      </div>
      {msg.error && <div className="ai-error" style={{ marginTop: 8 }}>⚠️ {msg.error}</div>}
      {msg.sources && msg.sources.length > 0 && (
        <div className="chat-sources">
          {msg.sources.map((s, i) => (
            <a
              key={s.url + i}
              className="chat-source-item"
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              title={s.breadcrumb || s.url}
            >
              <span className="chat-source-idx">[{i + 1}]</span>
              <span className="chat-source-title">{s.title || s.url}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
