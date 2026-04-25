import { useState } from 'react'
import type { UseRoadmapReturn } from '../hooks/useRoadmap'
import type { RoadmapLevel } from '../types/roadmap'
import { Markdown } from './Markdown'

interface Props {
  roadmap: UseRoadmapReturn
  /** 用户点击「开始练习」时回调，传当前章节的关键词列表，由 App 跳转到 quiz tab。 */
  onPracticeSection: (topic: string) => void
}

const LEVEL_LABEL: Record<RoadmapLevel, string> = {
  beginner:     '入门',
  intermediate: '进阶',
  advanced:     '高级',
}

const LEVEL_COLOR: Record<RoadmapLevel, string> = {
  beginner:     '#1D9E75',
  intermediate: '#378ADD',
  advanced:     '#BA7517',
}

type Mode = 'preset' | 'custom'

export function RoadmapPanel({ roadmap, onPracticeSection }: Props) {
  const {
    phase, presets, roadmap: rm, error, sectionStates, expandedIdx,
    generateFromPreset, generateCustom, explainSection, toggleSection, reset,
  } = roadmap

  const [mode, setMode]     = useState<Mode>('preset')
  const [goal, setGoal]     = useState('')
  const [level, setLevel]   = useState<RoadmapLevel>('beginner')
  const [focus, setFocus]   = useState('')

  const isGenerating = phase === 'generating'
  const isLoading    = phase === 'loading-presets'

  const handleCustomGenerate = () => {
    if (!goal.trim()) return
    void generateCustom({ goal, level, focus: focus || undefined })
  }

  return (
    <div className="rm-wrap">
      {/* —— 顶部表单 —— */}
      <div className="rm-toolbar">
        <div className="rm-mode-row">
          <div className="rm-mode-seg">
            {(['preset', 'custom'] as Mode[]).map(m => (
              <button
                key={m}
                className={`rm-mode-btn ${mode === m ? 'active' : ''}`}
                onClick={() => setMode(m)}
                disabled={isGenerating}
              >
                {m === 'preset' ? '经典路线' : '自定义生成'}
              </button>
            ))}
          </div>
          {rm && (
            <button className="chat-clear-btn" onClick={reset} disabled={isGenerating}>
              重新选择
            </button>
          )}
        </div>

        {mode === 'preset' ? (
          <div className="rm-presets-grid">
            {isLoading && <div className="quiz-loading">加载预制路线…</div>}
            {!isLoading && presets.map(p => {
              const active = rm?.id === p.id
              return (
                <button
                  key={p.id}
                  className={`rm-preset-card ${active ? 'active' : ''}`}
                  onClick={() => generateFromPreset(p.id)}
                  disabled={isGenerating}
                >
                  <div className="rm-preset-head">
                    <span className="rm-preset-title">{p.title}</span>
                    <span
                      className="rm-level-badge"
                      style={{
                        color:       LEVEL_COLOR[p.level],
                        background: `${LEVEL_COLOR[p.level]}1f`,
                        borderColor: `${LEVEL_COLOR[p.level]}55`,
                      }}
                    >{LEVEL_LABEL[p.level]}</span>
                  </div>
                  <div className="rm-preset-summary">{p.summary}</div>
                  <div className="rm-preset-meta">{p.section_count} 个章节</div>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="rm-custom-form">
            <input
              className="quiz-topic-input"
              placeholder="学习目标：例如「能用 Nav2 让差速底盘自主导航并避障」"
              value={goal}
              onChange={e => setGoal(e.target.value)}
              disabled={isGenerating}
            />
            <div className="quiz-form-row">
              <div className="quiz-seg">
                <span className="quiz-seg-label">水平</span>
                {(['beginner', 'intermediate', 'advanced'] as RoadmapLevel[]).map(l => (
                  <button
                    key={l}
                    className={`quiz-seg-btn ${level === l ? 'active' : ''}`}
                    onClick={() => setLevel(l)}
                    disabled={isGenerating}
                  >{LEVEL_LABEL[l]}</button>
                ))}
              </div>
              <input
                className="quiz-topic-input rm-focus-input"
                placeholder="重点方向（可选）：导航 / 控制 / 仿真 …"
                value={focus}
                onChange={e => setFocus(e.target.value)}
                disabled={isGenerating}
              />
              <button
                className="btn btn-primary"
                onClick={handleCustomGenerate}
                disabled={isGenerating || !goal.trim()}
              >
                {isGenerating ? '生成中…' : '生成路线'}
              </button>
            </div>
            <div className="rm-custom-hint">
              生成会基于本地 ROS 2 知识库（Foxy / Humble / Jazzy 等官方文档）
            </div>
          </div>
        )}
      </div>

      {/* —— 内容区 —— */}
      <div className="rm-body">
        {error && <div className="ai-error">⚠️ {error}</div>}

        {!rm && !isGenerating && !error && (
          <div className="quiz-empty">
            <div className="quiz-empty-icon">🧭</div>
            <div className="quiz-empty-title">选一条学习路线</div>
            <div className="quiz-empty-sub">
              选「经典路线」一键开始，或「自定义生成」让 AI 基于知识库为你定制
              <br /><br />
              每个章节都可点击 <b>展开讲解</b> 看 AI 详细讲解，
              或 <b>开始练习</b> 跳转到测验
            </div>
          </div>
        )}

        {isGenerating && (
          <div className="quiz-loading">
            <span className="ai-cursor" /> 路线设计师正在翻阅知识库…
          </div>
        )}

        {rm && (
          <div className="rm-content">
            <div className="rm-header">
              <div className="rm-header-top">
                <div className="rm-title">{rm.title}</div>
                <span
                  className="rm-level-badge"
                  style={{
                    color:       LEVEL_COLOR[rm.level],
                    background: `${LEVEL_COLOR[rm.level]}1f`,
                    borderColor: `${LEVEL_COLOR[rm.level]}55`,
                  }}
                >{LEVEL_LABEL[rm.level]}</span>
                {rm.is_preset && <span className="rm-tag-preset">预制</span>}
                {!rm.is_preset && <span className="rm-tag-custom">AI 定制</span>}
              </div>
              <div className="rm-summary">{rm.summary}</div>
              {rm.sources.length > 0 && (
                <details className="rm-sources">
                  <summary>📚 路线参考来源（{rm.sources.length} 篇）</summary>
                  <div className="chat-sources">
                    {rm.sources.map((s, i) => (
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
                </details>
              )}
            </div>

            <ol className="rm-sections">
              {rm.sections.map((s, idx) => {
                const expanded = expandedIdx === idx
                const ss = sectionStates[idx]
                return (
                  <li key={s.title + idx} className={`rm-section ${expanded ? 'expanded' : ''}`}>
                    <div className="rm-section-row" onClick={() => toggleSection(idx)}>
                      <div className="rm-section-num">{idx + 1}</div>
                      <div className="rm-section-main">
                        <div className="rm-section-title">{s.title}</div>
                        <div className="rm-section-meta">
                          <span className="rm-time-chip">⏱ {s.estimated_minutes} 分钟</span>
                          {s.key_concepts.slice(0, 4).map(k => (
                            <span key={k} className="rm-concept-chip">{k}</span>
                          ))}
                        </div>
                      </div>
                      <div className={`rm-arrow ${expanded ? 'open' : ''}`}>▾</div>
                    </div>

                    {expanded && (
                      <div className="rm-section-detail" onClick={e => e.stopPropagation()}>
                        <div className="rm-detail-block">
                          <div className="rm-detail-label">学习目标</div>
                          <ul className="rm-objective-list">
                            {s.objectives.map((o, i) => <li key={i}>{o}</li>)}
                          </ul>
                        </div>

                        <div className="rm-section-actions">
                          {!ss?.text && !ss?.loading && (
                            <button
                              className="btn btn-primary"
                              onClick={() => explainSection(idx)}
                            >展开讲解</button>
                          )}
                          <button
                            className="btn btn-ghost"
                            onClick={() => onPracticeSection(s.key_concepts.slice(0, 3).join(' '))}
                          >开始练习 →</button>
                        </div>

                        {ss && (ss.loading || ss.text || ss.error) && (
                          <div className="rm-explain">
                            <div className="rm-explain-title">
                              AI 讲解
                              {ss.loading && <span className="ai-cursor" />}
                            </div>
                            {ss.error && <div className="ai-error">⚠️ {ss.error}</div>}
                            <div className="rm-explain-body">
                              {ss.text
                                ? <Markdown text={ss.text} streaming={ss.loading} />
                                : (ss.loading ? <span className="quiz-thinking">检索文档中… <span className="ai-cursor" /></span> : null)
                              }
                            </div>
                            {ss.sources.length > 0 && (
                              <div className="chat-sources">
                                {ss.sources.map((src, i) => (
                                  <a
                                    key={src.url + i}
                                    className="chat-source-item"
                                    href={src.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title={src.breadcrumb || src.url}
                                  >
                                    <span className="chat-source-idx">[{i + 1}]</span>
                                    <span className="chat-source-title">{src.title || src.url}</span>
                                  </a>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
