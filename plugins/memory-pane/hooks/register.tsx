import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { Health, Injected, Note, PaneData, SearchData, View } from '../types'

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
  if (query.trim() === '') return clearSearch($)

  const found = await memJson<SearchData>($, 'search', '--json', query)
  if (found === undefined) return markUnavailable($)

  await update($, view, v => ({ ...v, search: found, isUnavailable: false }))
}

async function clearSearch($: EngineInterface) {
  await update($, view, v => ({ ...v, search: null }))
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

function count(n: number, word: string) {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function problems(h: Health) {
  const out: string[] = []
  if (h.open_old > 0) out.push(`${count(h.open_old, 'leftover')} past 30d`)
  if (h.dupes > 0) out.push(count(h.dupes, 'dupe pair'))
  if (h.stale > 0) out.push(`${h.stale} stale`)
  if (h.conflicts > 0) out.push(count(h.conflicts, 'conflict'))
  if (h.errors > 0) out.push(count(h.errors, 'hook error'))
  if (h.unpushed > 0) out.push(`${count(h.unpushed, 'commit')} not pushed`)
  if (h.dead > 0) out.push(count(h.dead, 'dead link'))
  if (h.long > 0) out.push(`${count(h.long, 'note')} too long`)
  if (h.days_since_pass !== null && h.days_since_pass > 14) out.push(`cleanup ${h.days_since_pass}d ago`)

  return out.join(', ')
}

function cleanupLine(h: Health) {
  const pass = h.days_since_pass === null ? 'no cleanup yet' : `last cleanup ${h.days_since_pass}d ago`

  return `${count(h.lessons_week, 'lesson')} this week, ${h.lessons_by_user} spotted by the user, ${count(h.lessons_repeats, 'repeat')}, ${pass}`
}

function projectName(project: string) {
  return project.split('/').pop() || project
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

    const row = (prefix: string, note: Note, tag: string) => (
      <Box key={`${prefix}-${note.slug}`} flexDirection="row" alignItems="center" gap="sm">
        <Box flexGrow={1} overflow="hidden">
          <Button key={`${prefix}-${note.slug}-open`} plain onPress={() => openInObsidian($, note.path)}>
            {note.title}
          </Button>
        </Box>
        <Text size="caption" dimColor>
          {tag}
        </Text>
      </Box>
    )

    const label = (text: string, empty: boolean) => (
      <Box flexDirection="row" alignItems="center" gap="sm">
        <Text size="footnote" weight="semibold" dimColor>
          {text}
        </Text>
        {empty && (
          <Text size="caption" dimColor>
            none
          </Text>
        )}
      </Box>
    )

    return (
      <Box flexDirection="column" gap="md">
        {isUnavailable && (
          <Text size="footnote" color="error">
            mem is not reachable, is it installed and on PATH
          </Text>
        )}
        {!pane && !isUnavailable && (
          <Text size="footnote" dimColor>
            loading
          </Text>
        )}
        {pane && (
          <Box flexDirection="column">
            <Text size="heading" weight="semibold">
              {projectName(pane.project)}
            </Text>
            {pane.project !== 'global' && (
              <Text size="caption" dimColor>
                {pane.project}
              </Text>
            )}
            <Text size="footnote" dimColor>
              {`${count(pane.counts.notes, 'note')}, ${pane.counts.open} open, ${pane.counts.recalled} recalled`}
            </Text>
          </Box>
        )}
        {pane && (
          <Box flexDirection="column">
            {problems(pane.health) === '' ? (
              <Text size="footnote" color="success">
                all clean
              </Text>
            ) : (
              <Text size="footnote" color="warning">
                {problems(pane.health)}
              </Text>
            )}
            <Text size="caption" dimColor>
              {cleanupLine(pane.health)}
            </Text>
          </Box>
        )}
        {pane && (
          <Box flexDirection="column" gap="xs">
            {label('open leftovers', pane.leftovers.length === 0)}
            {pane.leftovers.map(left => (
              <Box key={`left-${left.slug}`} flexDirection="row" alignItems="center" gap="sm">
                <Box flexGrow={1} overflow="hidden">
                  <Button key={`leftover-${left.slug}`} plain onPress={() => openInObsidian($, left.path)}>
                    {left.title}
                  </Button>
                </Box>
                <Text size="caption" dimColor>
                  {`${left.age_days}d`}
                </Text>
                <Button key={`done-${left.slug}`} plain dimColor onPress={() => void runThenRefresh($, 'done', left.slug)}>
                  done
                </Button>
              </Box>
            ))}
          </Box>
        )}
        {pane && (
          <Box flexDirection="column" gap="xs">
            {label('remembered this session', pane.injected.length === 0)}
            {newestFirst(pane.injected).map(note => row('injected', note, note.source))}
          </Box>
        )}
        <Box flexDirection="column" gap="xs">
          {'Input' in table && <table.Input key="query" placeholder="search memory" onSubmit={query => void search($, query)} />}
          {found && (
            <Box flexDirection="row" alignItems="center" gap="sm">
              <Text size="footnote" weight="semibold" dimColor>
                {found.hits.length === 0 ? 'no hits' : count(found.hits.length, 'hit')}
              </Text>
              <Button key="clear" plain dimColor onPress={() => void clearSearch($)}>
                clear
              </Button>
            </Box>
          )}
          {found?.hits.map(hit => row('hit', hit, hit.type ?? ''))}
          {found && found.maybe.length > 0 && label('maybe', false)}
          {found?.maybe.map(hit => row('maybe', hit, hit.type ?? ''))}
        </Box>
        <Box flexDirection="row" gap="sm">
          {pane && (
            <Button key="vault" variant="secondary" onPress={() => openInObsidian($, pane.vault)}>
              open vault
            </Button>
          )}
          <Button key="reindex" variant="secondary" onPress={() => void runThenRefresh($, 'index')}>
            reindex
          </Button>
        </Box>
      </Box>
    )
  })
}
