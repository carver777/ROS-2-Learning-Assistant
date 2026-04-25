import { useState, useEffect, useRef } from 'react'
import type { UseQuizReturn, QType, Difficulty, Verdict } from '../hooks/useQuiz'
import { Markdown } from './Markdown'

interface Props {
  quiz: UseQuizReturn
  /** 由学习路线等外部入口注入的题目主题；非空时会自动同步到表单并触发出题。 */
  injectedTopic?: string | null
  onTopicConsumed?: () => void
}

const QTYPE_LABEL: Record<QType, string> = {
  mcq:   '选择题',
  short: '简答题',
}

const DIFF_LABEL: Record<Difficulty, string> = {
  easy:   '简单',
  medium: '中等',
  hard:   '困难',
}

const VERDICT_LABEL: Record<Verdict, { text: string; color: string }> = {
  correct:           { text: '完全正确', color: '#1D9E75' },
  partially_correct: { text: '部分正确', color: '#BA7517' },
  incorrect:         { text: '答错了',   color: '#C0392B' },
}

const LETTERS = ['A', 'B', 'C', 'D']

export function QuizPanel({ quiz, injectedTopic, onTopicConsumed }: Props) {
  const {
    phase, quiz: q, userAnswer, setUserAnswer,
    grade, explanation, explainSources, error,
    generate, submit, explain, reset,
  } = quiz

  const [topic, setTopic]           = useState('')
  const [qtype, setQtype]           = useState<QType>('mcq')
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')

  const handleGenerate = () => {
    generate({ topic, qtype, difficulty })
  }

  const isAnswering = phase === 'answering' || phase === 'grading'
  const isGenerating = phase === 'generating'

  // 来自学习路线等外部入口的注入主题：填入表单后自动出一题
  const lastInjectedRef = useRef<string | null>(null)
  useEffect(() => {
    if (!injectedTopic) return
    if (injectedTopic === lastInjectedRef.current) return
    if (isGenerating || isAnswering) return
    lastInjectedRef.current = injectedTopic
    setTopic(injectedTopic)
    generate({ topic: injectedTopic, qtype, difficulty })
    onTopicConsumed?.()
  }, [injectedTopic, isGenerating, isAnswering, generate, qtype, difficulty, onTopicConsumed])

  return (
    <div className="quiz-wrap">
      {/* —— 顶部出题表单 —— */}
      <div className="quiz-toolbar">
        <div className="quiz-form-row">
          <input
            className="quiz-topic-input"
            placeholder="主题（可选）：QoS / lifecycle / launch …"
            value={topic}
            onChange={e => setTopic(e.target.value)}
            disabled={isGenerating || isAnswering}
          />
        </div>
        <div className="quiz-form-row">
          <div className="quiz-seg">
            <span className="quiz-seg-label">题型</span>
            {(['mcq', 'short'] as QType[]).map(t => (
              <button
                key={t}
                className={`quiz-seg-btn ${qtype === t ? 'active' : ''}`}
                onClick={() => setQtype(t)}
                disabled={isGenerating || isAnswering}
              >{QTYPE_LABEL[t]}</button>
            ))}
          </div>
          <div className="quiz-seg">
            <span className="quiz-seg-label">难度</span>
            {(['easy', 'medium', 'hard'] as Difficulty[]).map(d => (
              <button
                key={d}
                className={`quiz-seg-btn ${difficulty === d ? 'active' : ''}`}
                onClick={() => setDifficulty(d)}
                disabled={isGenerating || isAnswering}
              >{DIFF_LABEL[d]}</button>
            ))}
          </div>
        </div>
        <div className="quiz-form-row quiz-actions">
          <button
            className="btn btn-primary quiz-gen-btn"
            onClick={handleGenerate}
            disabled={isGenerating || isAnswering}
          >
            {isGenerating ? '出题中…' : (q ? '换一题' : '出题')}
          </button>
          {q && (
            <button className="btn btn-ghost" onClick={reset} disabled={isGenerating}>
              清空
            </button>
          )}
        </div>
      </div>

      {/* —— 内容区域 —— */}
      <div className="quiz-body">
        {error && <div className="ai-error">⚠️ {error}</div>}

        {phase === 'idle' && !q && (
          <div className="quiz-empty">
            <div className="quiz-empty-icon">📝</div>
            <div className="quiz-empty-title">ROS 2 知识测验</div>
            <div className="quiz-empty-sub">
              三位 AI 老师协作：<b>出题人</b> 基于知识库出题，
              <b>判题人</b> 评判你的回答，
              <b>讲题人</b> 给出详细解析
              <br /><br />
              选择题型、难度后点击 <b>出题</b> 开始
            </div>
          </div>
        )}

        {isGenerating && (
          <div className="quiz-loading">
            <span className="ai-cursor" /> 出题人正在翻阅文档…
          </div>
        )}

        {q && (
          <div className="quiz-card">
            <div className="quiz-card-meta">
              <span className="quiz-tag">{QTYPE_LABEL[q.type]}</span>
              <span className="quiz-tag quiz-tag-secondary">{DIFF_LABEL[difficulty]}</span>
            </div>
            <div className="quiz-question">{q.question}</div>

            {/* 选择题选项 */}
            {q.type === 'mcq' && q.options && (
              <div className="quiz-options">
                {q.options.map((opt, i) => {
                  const letter = LETTERS[i]
                  const selected = userAnswer.toUpperCase() === letter
                  const locked = phase === 'graded' || phase === 'explaining' || phase === 'explained'
                  const isAnswer = locked && letter === q.answer.toUpperCase()
                  const isWrong  = locked && selected && letter !== q.answer.toUpperCase()
                  return (
                    <button
                      key={letter}
                      className={`quiz-option ${selected ? 'selected' : ''} ${isAnswer ? 'is-answer' : ''} ${isWrong ? 'is-wrong' : ''}`}
                      onClick={() => !locked && phase !== 'grading' && setUserAnswer(letter)}
                      disabled={locked || phase === 'grading'}
                    >
                      <span className="quiz-option-letter">{letter}</span>
                      <span className="quiz-option-text">{opt}</span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* 简答题输入 */}
            {q.type === 'short' && (
              <textarea
                className="quiz-short-input"
                placeholder="在这里输入你的答案…"
                rows={5}
                value={userAnswer}
                onChange={e => setUserAnswer(e.target.value)}
                disabled={phase === 'grading' || phase === 'graded' || phase === 'explaining' || phase === 'explained'}
              />
            )}

            {/* 提交按钮 */}
            {(phase === 'answering' || phase === 'grading') && (
              <div className="quiz-actions">
                <button
                  className="btn btn-primary"
                  onClick={submit}
                  disabled={phase === 'grading' || !userAnswer.trim()}
                >
                  {phase === 'grading' ? '判分中…' : '提交答案'}
                </button>
              </div>
            )}

            {/* 评分结果 */}
            {grade && (
              <div className="quiz-grade">
                <div className="quiz-grade-head">
                  <div
                    className="quiz-grade-score"
                    style={{ color: VERDICT_LABEL[grade.verdict].color }}
                  >
                    {grade.score}
                  </div>
                  <div className="quiz-grade-meta">
                    <div
                      className="quiz-grade-verdict"
                      style={{ color: VERDICT_LABEL[grade.verdict].color }}
                    >
                      {VERDICT_LABEL[grade.verdict].text}
                    </div>
                    <div className="quiz-grade-label">判题人评分</div>
                  </div>
                </div>
                <div className="quiz-grade-feedback">{grade.feedback}</div>

                {(phase === 'graded' || phase === 'explaining' || phase === 'explained') && (
                  <div className="quiz-actions" style={{ marginTop: 12 }}>
                    {phase === 'graded' && (
                      <button className="btn btn-primary" onClick={explain}>
                        查看详细讲解
                      </button>
                    )}
                    {(phase === 'explaining' || phase === 'explained') && (
                      <button
                        className="btn btn-ghost"
                        onClick={handleGenerate}
                        disabled={isGenerating}
                      >下一题</button>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* 讲解 */}
            {(phase === 'explaining' || phase === 'explained') && (
              <div className="quiz-explain">
                <div className="quiz-explain-title">
                  讲题人解析
                  {phase === 'explaining' && <span className="ai-cursor" />}
                </div>
                <div className="quiz-explain-body">
                  {explanation
                    ? <Markdown text={explanation} streaming={phase === 'explaining'} />
                    : (phase === 'explaining' ? <span className="quiz-thinking">思考中… <span className="ai-cursor" /></span> : null)
                  }
                </div>
                {explainSources.length > 0 && (
                  <div className="chat-sources">
                    {explainSources.map((s, i) => (
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
            )}

            {/* 出题来源（始终展示，方便用户查看出处） */}
            {q.sources.length > 0 && phase !== 'explaining' && phase !== 'explained' && (
              <div className="quiz-sources-hint">
                <div className="quiz-sources-label">📚 题目来源（{q.sources.length} 篇）</div>
                <div className="chat-sources">
                  {q.sources.map((s, i) => (
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
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
