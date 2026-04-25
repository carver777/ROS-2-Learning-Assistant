export type RoadmapLevel = 'beginner' | 'intermediate' | 'advanced'

export interface RoadmapSource {
  title: string
  url: string
  breadcrumb: string
}

export interface RoadmapSection {
  title: string
  objectives: string[]
  key_concepts: string[]
  estimated_minutes: number
}

export interface Roadmap {
  id: string
  title: string
  summary: string
  level: RoadmapLevel
  sections: RoadmapSection[]
  sources: RoadmapSource[]
  is_preset: boolean
}

export interface RoadmapPresetOverview {
  id: string
  title: string
  summary: string
  level: RoadmapLevel
  section_count: number
}

export interface SectionExplainState {
  loading: boolean
  text: string
  sources: RoadmapSource[]
  error: string | null
}
