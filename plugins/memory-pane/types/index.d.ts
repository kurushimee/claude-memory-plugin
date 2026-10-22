export type Note = { slug: string; title: string; path: string }
export type Leftover = Note & { age_days: number }
export type Injected = Note & { source: 'brief' | 'prompt' | 'tool' | 'compact'; at: string }

export type PaneData = {
  project: string
  vault: string
  health: { line: string }
  leftovers: Leftover[]
  injected: Injected[]
  counts: { open: number; recalled: number }
}

export type SearchData = { hits: Note[]; maybe: Note[] }

export type View = { pane: PaneData | null; search: SearchData | null; isUnavailable: boolean }

declare module 'claude-code' {
  interface PluginState {
    'memory-pane': { view: View }
  }
}
