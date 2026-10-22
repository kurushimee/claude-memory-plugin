import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Injected, Note, PaneData, SearchData, View } from '../types'

const PANE = 'memory'
const EMPTY: View = { pane: null, search: null, isUnavailable: false }
const view = atom({ plugin: 'memory-pane', key: 'view' } as const, EMPTY)

let pending: Timer | undefined

async function memJson<T>($: EngineInterface, ...args: string[]): Promise<T | undefined> {
  try {
    const ran = await $.process.run(['mem', ...args])

    return ran.exitCode === 0 ? (JSON.parse(ran.stdout) as T) : undefined
  } catch {
    return undefined
  }
}

async function markUnavailable($: EngineInterface) {
  $.ui.status(undefined)
  await update($, view, v => ({ ...v, isUnavailable: true }))
}

async function refresh($: EngineInterface) {
  const id = await $.session.id()
  const cwd = await $.session.cwd()
  const pane = await memJson<PaneData>($, 'pane', '--json', '--session', id, '--cwd', cwd)
  if (pane === undefined) return markUnavailable($)

  $.ui.status(`mem: ${pane.counts.open} open, ${pane.counts.recalled} recalled`)
  await update($, view, v => ({ ...v, pane, isUnavailable: false }))
}

async function search($: EngineInterface, query: string) {
  const found = await memJson<SearchData>($, 'search', '--json', query)
  if (found === undefined) return markUnavailable($)

  await update($, view, v => ({ ...v, search: found, isUnavailable: false }))
}

async function runThenRefresh($: EngineInterface, ...args: string[]) {
  await $.process.run(['mem', ...args]).catch(() => undefined)
  await refresh($)
}

function openInObsidian($: EngineInterface, path: string) {
  void $.process.run(['cmd', '/c', 'start', '', `obsidian://open?path=${path}`]).catch(() => undefined)
}

function scheduleRefresh($: EngineInterface) {
  if (pending) return

  pending = $.clock.after(2000, () => {
    pending = undefined
    void refresh($)
  })
}

function newestFirst(notes: Injected[]) {
  return [...notes].sort((a, b) => b.at.localeCompare(a.at))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    void $.ui.open({ id: PANE, title: 'Memory' })
    await $.command.register({ name: 'mem', description: 'Open the Memory pane' }).catch(() => undefined)
    await refresh($)
    $.clock.every(60_000, () => void refresh($))

    return next(e)
  })

  on('command.run', { command: 'mem' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Memory' })

    return { text: 'Memory pane opened.' }
  })

  on('prompt.submit', ($, e, next) => {
    scheduleRefresh($)

    return next(e)
  })

  on('tool.call', ($, e, next) => {
    scheduleRefresh($)

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const table = $.ui.resolve(e)
    const { Box, Text, Button } = table
    const { pane, search: found, isUnavailable } = await read($, view)

    const row = (prefix: string, note: Note, tag?: string) => (
      <Button key={`${prefix}-${note.slug}`} plain onPress={() => openInObsidian($, note.path)}>
        {note.title}
        {tag && <Text dimColor> {tag}</Text>}
      </Button>
    )

    return (
      <Box flexDirection="column" gap={1}>
        {pane && (
          <Box flexDirection="column">
            <Text>{pane.project}</Text>
            <Text dimColor>{pane.health.line}</Text>
          </Box>
        )}
        {isUnavailable && <Text dimColor>mem is unavailable</Text>}
        {pane && (
          <Box flexDirection="column">
            <Text dimColor>open leftovers</Text>
            {pane.leftovers.map(left => (
              <Box key={`left-${left.slug}`} gap={1}>
                {row('leftover', left, `${left.age_days}d`)}
                <Button key={`done-${left.slug}`} plain dimColor onPress={() => void runThenRefresh($, 'done', left.slug)}>
                  done
                </Button>
              </Box>
            ))}
          </Box>
        )}
        {pane && (
          <Box flexDirection="column">
            <Text dimColor>remembered this session</Text>
            {newestFirst(pane.injected).map(note => row('injected', note, note.source))}
          </Box>
        )}
        <Box flexDirection="column">
          {'Input' in table && (
            <table.Input key="query" placeholder="search" onSubmit={query => void search($, query)} />
          )}
          {found?.hits.map(hit => row('hit', hit))}
          {found && found.maybe.length > 0 && <Text dimColor>maybe</Text>}
          {found?.maybe.map(hit => row('maybe', hit))}
        </Box>
        <Box gap={1}>
          {pane && <Button key="vault" onPress={() => openInObsidian($, pane.vault)}>open vault</Button>}
          <Button key="reindex" onPress={() => void runThenRefresh($, 'index')}>reindex</Button>
        </Box>
      </Box>
    )
  })
}
