export type Note = { slug: string; title: string; path: string; type?: string }
export type Leftover = Note & { age_days: number }
export type Injected = Note & { source: 'prompt'; at: string }

export type Health = {
  line: string
  open: number
  open_old: number
  dupes: number
  stale: number
  conflicts: number
  errors: number
  unpushed: number
  dead: number
  long: number
  days_since_pass: number | null
  lessons_week: number
  lessons_by_user: number
  lessons_repeats: number
}

export type PaneData = {
  project: string
  vault: string
  health: Health
  leftovers: Leftover[]
  opened: Note[]
  injected: Injected[]
  counts: { notes: number; open: number; opened: number; recalled: number }
}

export type SearchData = { hits: Note[]; maybe: Note[] }

export type View = { pane: PaneData | null; search: SearchData | null; isUnavailable: boolean }

declare module 'claude-code' {
  interface PluginState {
    'memory-pane': { view: View }
  }
}
