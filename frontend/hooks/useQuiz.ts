import { useState, useCallback, useRef } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export type QType = 'mcq' | 'short'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Verdict = 'correct' | 'partially_correct' | 'incorrect'
export type Phase = 'idle' | 'generating' | 'answering' | 'grading' | 'graded' | 'explaining' | 'explained'

export interface QuizSource {
  title: string
  url: string
  breadcrumb: string
}

export interface QuizItem {
  type:        QType
  question:    string
  options:     string[] | null
  /** 选择题：'A'/'B'/'C'/'D'；简答题：参考答案文本 */
  answer:      string
  explanation: string
  sources:     QuizSource[]
  topic_used:  string
}

export interface GradeResult {
  score:    number
  verdict:  Verdict
  feedback: string
}

export interface UseQuizReturn {
  phase:        Phase
  quiz:         QuizItem | null
  userAnswer:   string
  setUserAnswer:(v: string) => void
  grade:        GradeResult | null
  explanation:  string
  explainSources: QuizSource[]
  error:        string | null
  // 操作
  generate: (opts: { topic?: string; qtype: QType; difficulty: Difficulty }) => Promise<void>
  submit:   () => Promise<void>
  explain:  () => Promise<void>
  reset:    () => void
}

export function useQuiz(): UseQuizReturn {
  const [phase, setPhase]               = useState<Phase>('idle')
  const [quiz, setQuiz]                 = useState<QuizItem | null>(null)
  const [userAnswer, setUserAnswer]     = useState<string>('')
  const [grade, setGrade]               = useState<GradeResult | null>(null)
  const [explanation, setExplanation]   = useState<string>('')
  const [explainSources, setExplainSources] = useState<QuizSource[]>([])
  const [error, setError]               = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setPhase('idle')
    setQuiz(null)
    setUserAnswer('')
    setGrade(null)
    setExplanation('')
    setExplainSources([])
    setError(null)
  }, [])

  const generate = useCallback(async (opts: { topic?: string; qtype: QType; difficulty: Difficulty }) => {
    setError(null)
    setQuiz(null)
    setUserAnswer('')
    setGrade(null)
    setExplanation('')
    setExplainSources([])
    setPhase('generating')
    try {
      const res = await fetch(`${BACKEND_URL}/quiz/generate`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          topic:      opts.topic?.trim() || null,
          qtype:      opts.qtype,
          difficulty: opts.difficulty,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`出题失败 (${res.status}): ${text}`)
      }
      const data = await res.json() as QuizItem
      setQuiz(data)
      setPhase('answering')
    } catch (e) {
      setError((e as Error).message)
      setPhase('idle')
    }
  }, [])

  const submit = useCallback(async () => {
    if (!quiz) return
    if (!userAnswer.trim()) {
      setError('请先作答')
      return
    }
    setError(null)
    setPhase('grading')
    try {
      const res = await fetch(`${BACKEND_URL}/quiz/grade`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          question:         quiz.question,
          qtype:            quiz.type,
          options:          quiz.options,
          reference_answer: quiz.answer,
          user_answer:      userAnswer,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`评分失败 (${res.status}): ${text}`)
      }
      const data = await res.json() as GradeResult
      setGrade(data)
      setPhase('graded')
    } catch (e) {
      setError((e as Error).message)
      setPhase('answering')
    }
  }, [quiz, userAnswer])

  const explain = useCallback(async () => {
    if (!quiz) return
    setError(null)
    setExplanation('')
    setExplainSources([])
    setPhase('explaining')

    abortRef.current?.abort()
    abortRef.current = new AbortController()
    try {
      const res = await fetch(`${BACKEND_URL}/quiz/explain`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          question:         quiz.question,
          qtype:            quiz.type,
          options:          quiz.options,
          reference_answer: quiz.answer,
          explanation_hint: quiz.explanation,
          sources:          quiz.sources,
        }),
        signal: abortRef.current.signal,
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`讲解失败 (${res.status}): ${text}`)
      }
      const reader = res.body?.getReader()
      if (!reader) throw new Error('无法读取响应流')
      const decoder = new TextDecoder()
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
              setError(parsed.error)
              continue
            }
            if (parsed.meta) {
              setExplainSources(parsed.meta.sources || [])
              continue
            }
            if (parsed.content) {
              setExplanation(prev => prev + parsed.content)
            }
          } catch { /* skip */ }
        }
      }
      setPhase('explained')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError((e as Error).message)
      }
      setPhase('graded')
    }
  }, [quiz])

  return {
    phase, quiz, userAnswer, setUserAnswer,
    grade, explanation, explainSources, error,
    generate, submit, explain, reset,
  }
}
