import { useState, useCallback, useRef, useEffect } from 'react'
import type {
  Roadmap, RoadmapPresetOverview, RoadmapLevel, SectionExplainState,
} from '../types/roadmap'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export type RoadmapPhase = 'idle' | 'loading-presets' | 'generating' | 'ready'

export interface UseRoadmapReturn {
  phase: RoadmapPhase
  presets: RoadmapPresetOverview[]
  roadmap: Roadmap | null
  error: string | null
  // 章节讲解状态：key = section index
  sectionStates: Record<number, SectionExplainState>
  expandedIdx: number | null
  // 操作
  loadPresets: () => Promise<void>
  generateFromPreset: (presetId: string) => Promise<void>
  generateCustom: (opts: { goal: string; level: RoadmapLevel; focus?: string }) => Promise<void>
  explainSection: (idx: number) => Promise<void>
  toggleSection: (idx: number) => void
  reset: () => void
}

export function useRoadmap(): UseRoadmapReturn {
  const [phase, setPhase]       = useState<RoadmapPhase>('idle')
  const [presets, setPresets]   = useState<RoadmapPresetOverview[]>([])
  const [roadmap, setRoadmap]   = useState<Roadmap | null>(null)
  const [error, setError]       = useState<string | null>(null)
  const [sectionStates, setSectionStates] = useState<Record<number, SectionExplainState>>({})
  const [expandedIdx, setExpandedIdx]     = useState<number | null>(null)
  const abortRefs = useRef<Record<number, AbortController>>({})

  // 首次挂载拉一次预制清单
  useEffect(() => {
    void loadPresetsImpl()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadPresetsImpl = async () => {
    setPhase('loading-presets')
    try {
      const res = await fetch(`${BACKEND_URL}/roadmap/presets`)
      if (!res.ok) throw new Error(`加载预制路线失败 (${res.status})`)
      const data = await res.json() as { presets: RoadmapPresetOverview[] }
      setPresets(data.presets)
      setPhase(prev => prev === 'loading-presets' ? 'idle' : prev)
    } catch (e) {
      setError((e as Error).message)
      setPhase('idle')
    }
  }
  const loadPresets = useCallback(loadPresetsImpl, [])

  const _consume = (data: Roadmap) => {
    setRoadmap(data)
    setPhase('ready')
    setSectionStates({})
    setExpandedIdx(null)
  }

  const generateFromPreset = useCallback(async (presetId: string) => {
    setError(null)
    setPhase('generating')
    setRoadmap(null)
    try {
      const res = await fetch(`${BACKEND_URL}/roadmap/generate`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ preset_id: presetId }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`加载预制路线失败 (${res.status}): ${text}`)
      }
      _consume(await res.json() as Roadmap)
    } catch (e) {
      setError((e as Error).message)
      setPhase('idle')
    }
  }, [])

  const generateCustom = useCallback(async (
    opts: { goal: string; level: RoadmapLevel; focus?: string },
  ) => {
    setError(null)
    setPhase('generating')
    setRoadmap(null)
    try {
      const res = await fetch(`${BACKEND_URL}/roadmap/generate`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          goal:  opts.goal.trim(),
          level: opts.level,
          focus: opts.focus?.trim() || null,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`生成路线失败 (${res.status}): ${text}`)
      }
      _consume(await res.json() as Roadmap)
    } catch (e) {
      setError((e as Error).message)
      setPhase('idle')
    }
  }, [])

  const explainSection = useCallback(async (idx: number) => {
    if (!roadmap) return
    const section = roadmap.sections[idx]
    if (!section) return

    setExpandedIdx(idx)
    // 已经讲解过：复用缓存，不重发请求
    if (sectionStates[idx]?.text) return

    setSectionStates(prev => ({
      ...prev,
      [idx]: { loading: true, text: '', sources: [], error: null },
    }))

    abortRefs.current[idx]?.abort()
    abortRefs.current[idx] = new AbortController()

    try {
      const res = await fetch(`${BACKEND_URL}/roadmap/section/explain`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          roadmap_title: roadmap.title,
          section_title: section.title,
          objectives:    section.objectives,
          key_concepts:  section.key_concepts,
        }),
        signal: abortRefs.current[idx].signal,
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
              setSectionStates(prev => ({
                ...prev,
                [idx]: { ...prev[idx], error: parsed.error, loading: false },
              }))
              continue
            }
            if (parsed.meta) {
              setSectionStates(prev => ({
                ...prev,
                [idx]: { ...prev[idx], sources: parsed.meta.sources || [] },
              }))
              continue
            }
            if (parsed.content) {
              setSectionStates(prev => ({
                ...prev,
                [idx]: { ...prev[idx], text: prev[idx].text + parsed.content },
              }))
            }
          } catch { /* skip */ }
        }
      }
      setSectionStates(prev => ({
        ...prev,
        [idx]: { ...prev[idx], loading: false },
      }))
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      setSectionStates(prev => ({
        ...prev,
        [idx]: { ...prev[idx], loading: false, error: (e as Error).message },
      }))
    }
  }, [roadmap, sectionStates])

  const toggleSection = useCallback((idx: number) => {
    setExpandedIdx(prev => prev === idx ? null : idx)
  }, [])

  const reset = useCallback(() => {
    Object.values(abortRefs.current).forEach(c => c.abort())
    abortRefs.current = {}
    setRoadmap(null)
    setSectionStates({})
    setExpandedIdx(null)
    setError(null)
    setPhase('idle')
  }, [])

  return {
    phase, presets, roadmap, error, sectionStates, expandedIdx,
    loadPresets, generateFromPreset, generateCustom, explainSection, toggleSection, reset,
  }
}
