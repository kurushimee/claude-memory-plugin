import { expect, mock, test } from 'claude-code/testing'

const PANE = {
  plugin: 'memory-pane',
  component: 'Pane',
  requestId: 'memory',
  props: {
    title: 'Memory',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

const paneJson = {
  project: 'F:/radiance-cascades',
  vault: 'F:/claude-memory',
  health: { line: '3 open, 1 older than 30d, 0 dupes, 2 stale, 0 conflicts, 0 errors, last pass 3d ago', open: 3, open_old: 1, dupes: 0, stale: 2, conflicts: 0, errors: 0, unpushed: 0, days_since_pass: 3, feedback_week: 1 },
  leftovers: [{ slug: 'finish-cascade-probe-debug', title: 'finish the cascade probe debug view', path: 'F:/claude-memory/leftovers/finish-cascade-probe-debug.md', project: 'F:/radiance-cascades', age_days: 4 }],
  injected: [{ slug: 'godot-runs-must-end-themselves', title: 'godot runs must end themselves', path: 'F:/claude-memory/facts/godot-runs-must-end-themselves.md', source: 'tool', at: '2026-10-22T12:00:00' }],
  counts: { notes: 40, open: 3, recalled: 2 },
}

const searchJson = {
  hits: [{ slug: 'godot-runs-must-end-themselves', title: 'godot runs must end themselves', path: 'F:/claude-memory/facts/godot-runs-must-end-themselves.md', type: 'facts', score: 0.81, body: '...' }],
  maybe: [{ slug: 'one-gpu-job-at-a-time', title: 'one gpu job at a time', path: 'F:/claude-memory/facts/one-gpu-job-at-a-time.md', type: 'facts' }],
}

const exited = (stdout: string) => ({
  value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

test('the pane lists notes, marks a leftover done and searches, on terminal and desktop', async ($, on) => {
  const runs: string[][] = []
  mock.clock(on)
  on('process.run', (_, e) => {
    runs.push([...e.argv])
    if (e.argv[1] === 'pane') return exited(JSON.stringify(paneJson))
    if (e.argv[1] === 'search') return exited(JSON.stringify(searchJson))

    return exited('')
  })
  on('session.id', () => ({ value: 'abc' }))
  on('session.cwd', () => ({ value: 'F:/radiance-cascades' }))
  on('command.register', () => ({ value: { command: 'mem' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.status', () => ({ value: undefined }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: 'F:/radiance-cascades', surface: 'desktop', isInteractive: true })
  expect(runs[0]).toEqual(['mem', 'pane', '--json', '--session', 'abc', '--cwd', 'F:/radiance-cascades'])

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Button', text: /finish the cascade probe debug view/ })).toBeDefined()
    expect(await ui.find({ type: 'Button', text: /godot runs must end themselves/ })).toBeDefined()

    await ui.press({ key: 'done-finish-cascade-probe-debug' })
    expect(runs).toContainEqual(['mem', 'done', 'finish-cascade-probe-debug'])

    await ui.input({ key: 'query', text: 'gpu' })
    expect(runs).toContainEqual(['mem', 'search', '--json', 'gpu'])
    expect(await ui.find({ type: 'Button', text: /one gpu job at a time/ })).toBeDefined()
    await ui.unmount()
  }
})
